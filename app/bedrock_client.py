import json
import time
import re
from typing import List, Dict, Optional
import logging
import boto3
from botocore.exceptions import ClientError, ReadTimeoutError, ConnectTimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings
from app.models import (
    SearchStrategy, 
    LeaseInfo, 
    Violation, 
    Citation,
    AnalysisMetrics,
    CategorizedViolation,
    ViolationCategory,
    MaintenanceResponse,
    VendorWorkOrder,
    TenantMessageRewrite,
    MoveOutResponse,
    MaintenanceWorkflow,
    ChatMessage,
    MaintenanceChatResponse,
    MaintenanceRequestExtraction
)
from app.exceptions import AITimeoutError, AIModelError

# Import prompt builders
from app.prompts.lease_analysis_prompts import (
    build_lease_analysis_prompt,
    build_categorized_analysis_prompt,
    CATEGORIZED_ANALYSIS_SYSTEM_PROMPT
)
from app.prompts.maintenance_prompts import (
    build_maintenance_evaluation_prompt,
    build_vendor_work_order_prompt,
    build_maintenance_workflow_prompt
)
from app.prompts.tenant_communication_prompts import (
    build_tenant_message_rewrite_prompt,
    build_move_out_evaluation_prompt
)
from app.prompts.chat_prompts import (
    MAINTENANCE_CHAT_SYSTEM_PROMPT,
    build_maintenance_extraction_prompt,
    build_conversation_summary_prompt
)

logger = logging.getLogger(__name__)


class BedrockClient:
    """Client for interacting with AWS Bedrock API with timeout and retry support"""
    
    def __init__(self):
        """
        Initialize Bedrock client with AWS credentials
        
        Uses IAM role if running on EC2 with attached role (recommended)
        Uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from settings for local testing
        """
        try:
            # Configure boto3 client
            session_kwargs = {
                'region_name': settings.AWS_REGION
            }
            
            # Add credentials if provided (for local testing)
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                logger.info("Using AWS credentials from environment variables")
                session_kwargs['aws_access_key_id'] = settings.AWS_ACCESS_KEY_ID
                session_kwargs['aws_secret_access_key'] = settings.AWS_SECRET_ACCESS_KEY
            else:
                logger.info("Using IAM role credentials (EC2)")
            
            # Create boto3 session and client
            session = boto3.Session(**session_kwargs)
            
            self.client = session.client(
                service_name='bedrock-runtime',
                config=boto3.session.Config(
                    read_timeout=180,
                    connect_timeout=10,
                    retries={'max_attempts': 2, 'mode': 'adaptive'}
                )
            )
            
            logger.info(f"Bedrock client initialized for region: {settings.AWS_REGION}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {str(e)}")
            raise AIModelError(
                message="Failed to initialize AWS Bedrock client",
                details=str(e)
            )
    
    @staticmethod
    def _sanitize_json_string(json_str: str) -> str:
        """
        Sanitize JSON string by removing/escaping invalid control characters
        
        Args:
            json_str: Raw JSON string that may contain invalid characters
            
        Returns:
            Cleaned JSON string safe for parsing
        """
        sanitized = ""
        for char in json_str:
            code = ord(char)
            if code >= 32:
                sanitized += char
            elif code in [9, 10, 13]:
                sanitized += char
        
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', sanitized)
        return sanitized
    
    def _extract_json_from_markdown(self, text: str) -> Optional[str]:
        """
        Extract JSON from markdown code blocks or plain text
        
        Args:
            text: Response text that may contain markdown
            
        Returns:
            Extracted JSON string or None if not found
        """
        json_block_patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
        ]
        
        for pattern in json_block_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                logger.info("Found JSON within markdown code block")
                json_str = match.group(1).strip()
                return self._fix_truncated_json(json_str)
        
        incomplete_pattern = r'```(?:json)?\s*(\{.*)'
        match = re.search(incomplete_pattern, text, re.DOTALL)
        if match:
            logger.warning("Found incomplete markdown block")
            json_str = match.group(1).strip()
            json_str = re.sub(r'```\s*$', '', json_str)
            return self._fix_truncated_json(json_str)
        
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        
        if json_start != -1 and json_end > json_start:
            logger.info("Found JSON without markdown code block")
            json_str = text[json_start:json_end].strip()
            return self._fix_truncated_json(json_str)
        
        logger.error("Could not find JSON in response")
        return None
    
    def _fix_truncated_json(self, json_str: str) -> str:
        """
        Attempt to fix truncated/incomplete JSON
        
        Args:
            json_str: Potentially truncated JSON string
            
        Returns:
            Fixed JSON string
        """
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')
        
        if open_braces == close_braces and open_brackets == close_brackets:
            return json_str
        
        logger.warning(f"JSON appears truncated: {{ {open_braces}/{close_braces}, [ {open_brackets}/{close_brackets}")
        
        json_str = re.sub(r',?\s*"[^"]*$', '', json_str)
        
        while open_brackets > close_brackets:
            json_str += ']'
            close_brackets += 1
        
        while open_braces > close_braces:
            json_str += '}'
            close_braces += 1
        
        return json_str
    
    def _format_messages_for_bedrock(self, model_id: str, system_prompt: str, user_prompt: str) -> Dict:
        """
        Format messages according to model-specific requirements
        
        Args:
            model_id: Bedrock model identifier or inference profile ID
            system_prompt: System prompt text
            user_prompt: User prompt text
            
        Returns:
            Formatted request body for the specific model
        """
        # Handle inference profile IDs (us.provider.model) by extracting provider
        if model_id.startswith("us."):
            # Extract provider from inference profile ID: us.anthropic.claude... -> anthropic
            provider = model_id.split(".")[1]
        elif "." in model_id:
            # Direct model ID: anthropic.claude... -> anthropic
            provider = model_id.split(".")[0]
        else:
            provider = model_id
        
        if provider == "anthropic":
            # Claude format
            return {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 16000,
                "temperature": 0.1,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ]
            }
        
        elif provider == "meta":
            # Llama format - max_gen_len must be <= 8192
            return {
                "prompt": f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
                "max_gen_len": 8192,
                "temperature": 0.1,
                "top_p": 0.9
            }
        
        elif provider == "mistral":
            # Mistral format for AWS Bedrock
            # Mistral uses a simple prompt with instruction format
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            return {
                "prompt": combined_prompt,
                "max_tokens": 8192,  # Mistral max is 8192
                "temperature": 0.1,
                "top_p": 0.9
            }
        
        else:
            raise AIModelError(
                message=f"Unsupported model: {model_id}",
                details="Model format not recognized"
            )
    
    def _extract_text_from_response(self, model_id: str, response_body: Dict) -> str:
        """
        Extract text from model-specific response format
        
        Args:
            model_id: Bedrock model identifier or inference profile ID
            response_body: Parsed JSON response from Bedrock
            
        Returns:
            Generated text content
        """
        # Handle inference profile IDs (us.provider.model) by extracting provider
        if model_id.startswith("us."):
            provider = model_id.split(".")[1]
        elif "." in model_id:
            provider = model_id.split(".")[0]
        else:
            provider = model_id
        
        try:
            if provider == "anthropic":
                # Claude response format
                return response_body['content'][0]['text']
            
            elif provider == "meta":
                # Llama response format
                return response_body['generation']
            
            elif provider == "mistral":
                # Mistral response format
                return response_body['outputs'][0]['text']
            
            else:
                raise AIModelError(
                    message=f"Unsupported model response format: {model_id}",
                    details="Cannot extract text from response"
                )
                
        except KeyError as e:
            logger.error(f"Failed to extract text from response: {str(e)}")
            logger.error(f"Response body: {json.dumps(response_body, indent=2)}")
            raise AIModelError(
                message="Failed to parse model response",
                details=f"Missing expected key: {str(e)}"
            )
    
    def _get_token_usage(self, model_id: str, response_body: Dict) -> Dict[str, int]:
        """
        Extract token usage from model response
        
        Args:
            model_id: Bedrock model identifier or inference profile ID
            response_body: Parsed JSON response from Bedrock
            
        Returns:
            Dictionary with prompt, completion, and total tokens
        """
        # Handle inference profile IDs (us.provider.model) by extracting provider
        if model_id.startswith("us."):
            provider = model_id.split(".")[1]
        elif "." in model_id:
            provider = model_id.split(".")[0]
        else:
            provider = model_id
        
        try:
            if provider == "anthropic":
                usage = response_body.get('usage', {})
                prompt_tokens = usage.get('input_tokens', 0)
                completion_tokens = usage.get('output_tokens', 0)
            
            elif provider == "meta":
                prompt_tokens = response_body.get('prompt_token_count', 0)
                completion_tokens = response_body.get('generation_token_count', 0)
            
            elif provider == "mistral":
                prompt_tokens = response_body.get('prompt_token_count', 0)
                completion_tokens = response_body.get('generation_token_count', 0)
            
            else:
                prompt_tokens = 0
                completion_tokens = 0
            
            return {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": prompt_tokens + completion_tokens
            }
            
        except Exception as e:
            logger.warning(f"Failed to extract token usage: {str(e)}")
            return {"prompt": 0, "completion": 0, "total": 0}
    
    def _call_bedrock_with_retry(self, model_id: str, body: Dict) -> tuple[str, Dict[str, int]]:
        """
        Call Bedrock API with retry logic
        
        Args:
            model_id: Bedrock model identifier
            body: Request body formatted for the specific model
            
        Returns:
            Tuple of (response_text, token_usage)
            
        Raises:
            AITimeoutError: If request times out
            AIModelError: If API returns an error
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Call Bedrock API
                response = self.client.invoke_model(
                    modelId=model_id,
                    body=json.dumps(body)
                )
                
                # Parse response
                response_body = json.loads(response['body'].read())
                
                # Extract text and tokens
                text = self._extract_text_from_response(model_id, response_body)
                tokens = self._get_token_usage(model_id, response_body)
                
                return text, tokens
                
            except (ReadTimeoutError, ConnectTimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Bedrock timeout on attempt {attempt + 1}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise AITimeoutError(timeout_seconds=120)
                    
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                
                if error_code == 'ThrottlingException':
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"Bedrock throttled, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise AIModelError(
                            message="AWS Bedrock rate limit exceeded",
                            details="Too many requests. Please try again later."
                        )
                elif error_code == 'ModelTimeoutException':
                    raise AITimeoutError(timeout_seconds=120)
                elif error_code == 'AccessDeniedException':
                    raise AIModelError(
                        message="Access denied to AWS Bedrock",
                        details="Check IAM permissions or enable model access in AWS Console"
                    )
                else:
                    # Log the full error details for debugging
                    logger.error(f"Bedrock ValidationException details: {error_message}")
                    logger.error(f"Request body: {json.dumps(body, indent=2)}")
                    raise AIModelError(
                        message=f"AWS Bedrock error: {error_code}",
                        details=error_message
                    )
                    
            except Exception as e:
                logger.error(f"Unexpected Bedrock error: {str(e)}")
                raise AIModelError(
                    message="Unexpected AWS Bedrock error",
                    details=str(e)
                )
        
        if last_error:
            raise AIModelError(
                message="AWS Bedrock failed after retries",
                details=str(last_error)
            )
    
    # AWS Bedrock Pricing per 1M tokens (as of December 2025)
    MODEL_PRICING = {
        # Anthropic Claude
        "anthropic.claude-3-5-sonnet-20241022-v2:0": {"input": 3.0, "output": 15.0},
        "anthropic.claude-3-5-sonnet-20240620-v1:0": {"input": 3.0, "output": 15.0},
        "anthropic.claude-3-opus-20240229-v1:0": {"input": 15.0, "output": 75.0},
        "anthropic.claude-3-haiku-20240307-v1:0": {"input": 0.25, "output": 1.25},
        "us.anthropic.claude-3-5-haiku-20241022-v1:0": {"input": 0.80, "output": 4.0},
        
        # Meta Llama
        "meta.llama3-1-405b-instruct-v1:0": {"input": 0.00532, "output": 0.016},
        "meta.llama3-1-70b-instruct-v1:0": {"input": 0.00099, "output": 0.00099},
        "meta.llama3-1-8b-instruct-v1:0": {"input": 0.00022, "output": 0.00022},
        
        # Mistral AI
        "mistral.mistral-large-2407-v1:0": {"input": 3.0, "output": 9.0},
        "mistral.mistral-small-2402-v1:0": {"input": 0.2, "output": 0.6},
    }
    
    def analyze_lease_with_search(
        self,
        model_name: str,
        lease_info: LeaseInfo,
        search_results: Optional[List[Dict[str, str]]] = None,
        use_native_search: bool = False
    ) -> tuple[List[Violation], AnalysisMetrics, Optional[Dict[str, str]]]:
        """
        Analyze lease for violations using specified Bedrock model
        
        Note: AWS Bedrock models do NOT have native web search.
        Always use DuckDuckGo search results when available.
        
        Args:
            model_name: Bedrock model identifier
            lease_info: Extracted lease information
            search_results: Search results from DuckDuckGo (recommended)
            use_native_search: Ignored for Bedrock (no native search)
            
        Returns:
            Tuple of (violations list, metrics, location dict extracted by model)
        """
        start_time = time.time()
        
        try:
            # Build prompt
            prompt = build_lease_analysis_prompt(lease_info, search_results, use_native_search=False)
            
            # Format request for Bedrock
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a legal expert specializing in landlord-tenant law. Analyze lease agreements for potential violations of local, county, and state laws. Always cite specific laws and provide .gov sources when possible.",
                user_prompt=prompt
            )
            
            # Make API call
            response_text, tokens_used = self._call_bedrock_with_retry(model_name, body)
            
            # Parse response
            violations, extracted_lease_info = self._parse_violations_from_response(response_text)
            
            # Update lease_info with extracted fields
            if extracted_lease_info:
                if extracted_lease_info.get("city"):
                    lease_info.city = extracted_lease_info["city"]
                if extracted_lease_info.get("state"):
                    lease_info.state = extracted_lease_info["state"]
                if extracted_lease_info.get("county"):
                    lease_info.county = extracted_lease_info["county"]
                if extracted_lease_info.get("address"):
                    lease_info.address = extracted_lease_info["address"]
                if extracted_lease_info.get("landlord"):
                    lease_info.landlord = extracted_lease_info["landlord"]
                if extracted_lease_info.get("tenant"):
                    lease_info.tenant = extracted_lease_info["tenant"]
                if extracted_lease_info.get("rent_amount"):
                    lease_info.rent_amount = extracted_lease_info["rent_amount"]
                if extracted_lease_info.get("security_deposit"):
                    lease_info.security_deposit = extracted_lease_info["security_deposit"]
                if extracted_lease_info.get("lease_duration"):
                    lease_info.lease_duration = extracted_lease_info["lease_duration"]
            
            # Calculate metrics
            elapsed_time = time.time() - start_time
            cost = self._calculate_cost(model_name, tokens_used)
            
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.DUCKDUCKGO_SEARCH,  # Bedrock always uses DuckDuckGo
                total_time_seconds=elapsed_time,
                cost_usd=cost,
                gov_citations_count=sum(1 for v in violations for c in v.citations if c.is_gov_site),
                total_citations_count=sum(len(v.citations) for v in violations),
                violations_found=len(violations),
                avg_confidence_score=sum(v.confidence_score for v in violations) / len(violations) if violations else 0,
                has_law_references=any(
                    c.law_reference for v in violations for c in v.citations
                ),
                tokens_used=tokens_used
            )
            
            return violations, metrics, extracted_lease_info
            
        except Exception as e:
            logger.error(f"Error analyzing with {model_name}: {str(e)}")
            
            elapsed_time = time.time() - start_time
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.DUCKDUCKGO_SEARCH,
                total_time_seconds=elapsed_time,
                cost_usd=0.0,
                gov_citations_count=0,
                total_citations_count=0,
                violations_found=0,
                avg_confidence_score=0.0,
                has_law_references=False,
                tokens_used={"prompt": 0, "completion": 0, "total": 0}
            )
            
            return [], metrics, None
    
    def _calculate_cost(self, model_name: str, tokens_used: Dict[str, int]) -> float:
        """Calculate cost for the API call based on token usage"""
        if model_name not in self.MODEL_PRICING:
            logger.warning(f"No pricing info for model: {model_name}")
            return 0.0
        
        pricing = self.MODEL_PRICING[model_name]
        
        input_cost = (tokens_used.get("prompt", 0) / 1_000_000) * pricing["input"]
        output_cost = (tokens_used.get("completion", 0) / 1_000_000) * pricing["output"]
        
        return input_cost + output_cost
    
    def _parse_violations_from_response(self, response_text: str) -> tuple[List[Violation], Optional[Dict[str, str]]]:
        """Parse violations and lease info from model response"""
        violations = []
        lease_info_data = None
        
        try:
            logger.info("="*80)
            logger.info("PARSING VIOLATIONS RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            # Extract JSON from response (may be wrapped in markdown)
            json_str = response_text
            if "```json" in response_text:
                logger.info("Found ```json marker, extracting...")
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                logger.info("Found ``` marker, extracting...")
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                logger.info("No code blocks found, using full response")
            
            # Sanitize JSON string to remove invalid control characters
            json_str = self._sanitize_json_string(json_str.strip())
            
            # Log sanitized JSON for debugging
            logger.info("SANITIZED JSON STRING:")
            logger.info(json_str[:1000] if len(json_str) > 1000 else json_str)
            if len(json_str) > 1000:
                logger.info(f"... (truncated, total length: {len(json_str)} chars)")
            logger.info("="*80)
            
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Found {len(data.get('violations', []))} violations")
            
            # Extract lease_info if present (includes location and other fields)
            if "lease_info" in data:
                lease_info_data = data["lease_info"]
            # Fallback to old "location" key for backward compatibility
            elif "location" in data:
                lease_info_data = data["location"]
            
            for v_data in data.get("violations", []):
                try:
                    citations = [
                        Citation(**c) for c in v_data.get("citations", [])
                    ]
                    
                    violation = Violation(
                        violation_type=v_data.get("violation_type", "Unknown"),
                        description=v_data.get("description", ""),
                        severity=v_data.get("severity", "medium"),
                        confidence_score=v_data.get("confidence_score", 0.5),
                        lease_clause=v_data.get("lease_clause", ""),
                        citations=citations
                    )
                    violations.append(violation)
                except Exception as e:
                    logger.warning(f"Failed to parse individual violation: {str(e)}")
                    # Continue processing other violations
                    continue
        
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
        except Exception as e:
            logger.error("="*80)
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
        
        return violations, lease_info_data
    
    def analyze_lease_categorized(
        self,
        lease_info: LeaseInfo
    ) -> tuple[Dict[str, List[CategorizedViolation]], AnalysisMetrics, Optional[Dict[str, str]]]:
        """
        Analyze lease for violations using Claude 3.5 Haiku and categorize them.
        
        Args:
            lease_info: Extracted lease information
            
        Returns:
            Tuple of (violations by category dict, metrics, location dict extracted by model)
        """
        # Try Claude 3.5 Haiku first, fallback to Llama 70B if not accessible
        models_to_try = [
            "us.anthropic.claude-3-5-haiku-20241022-v1:0",  # Best for consistency
            "us.meta.llama3-1-70b-instruct-v1:0"  # Fallback if Claude not enabled
        ]
        
        start_time = time.time()
        max_retries = 3
        last_error = None
        model_name = None
        
        # Try each model until one works
        for model_to_test in models_to_try:
            model_name = model_to_test
            logger.info(f"Attempting categorized analysis with {model_name}")
            
            for attempt in range(max_retries):
                try:
                    # Build categorized analysis prompt
                    logger.info(f"Building prompt for {model_name} (attempt {attempt + 1}/{max_retries})")
                    prompt = build_categorized_analysis_prompt(lease_info)
                    logger.info(f"Prompt size: {len(prompt)} characters")
                    
                    # Format request for Bedrock with strict JSON instructions
                    system_prompt = CATEGORIZED_ANALYSIS_SYSTEM_PROMPT
                    
                    body = self._format_messages_for_bedrock(
                        model_id=model_name,
                        system_prompt=system_prompt,
                        user_prompt=prompt
                    )
                    
                    # Make API call
                    logger.info(f"Calling AWS Bedrock with {model_name}...")
                    response_text, tokens_used = self._call_bedrock_with_retry(model_name, body)
                    logger.info(f"Received response: {len(response_text)} characters, tokens used: {tokens_used}")
                    
                    # Parse violations and lease info with improved JSON extraction
                    logger.info("Parsing AI response for violations and location data...")
                    categorized_violations, lease_info_data = self._parse_categorized_violations(response_text)
                    
                    # Validate response has all required fields
                    if self._validate_categorized_response(categorized_violations, lease_info_data):
                        logger.info(f"Successfully completed analysis with {model_name}")
                        break  # Success - exit retry loop
                    else:
                        logger.warning(f"Attempt {attempt + 1}: Invalid response structure, retrying...")
                        last_error = Exception("Invalid response structure")
                        if attempt < max_retries - 1:
                            continue
                        
                except json.JSONDecodeError as e:
                    last_error = e
                    logger.warning(f"Attempt {attempt + 1}: JSON parse error: {str(e)}")
                    if attempt < max_retries - 1:
                        continue
                    # If all retries fail, try next model
                except AIModelError as e:
                    # Check if it's an access denied error
                    if "Access denied" in str(e) or "AccessDeniedException" in str(e):
                        logger.warning(f"Access denied to {model_name}, trying next model...")
                        last_error = e
                        break  # Break inner loop to try next model
                    else:
                        last_error = e
                        logger.error(f"Attempt {attempt + 1}: Error: {str(e)}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        break
                except Exception as e:
                    last_error = e
                    logger.error(f"Attempt {attempt + 1}: Error in categorized analysis: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(1)  # Brief delay before retry
                        continue
                    break
            
            # If successful, calculate metrics and exit model loop
            if self._validate_categorized_response(categorized_violations, lease_info_data):
                # Calculate metrics
                elapsed_time = time.time() - start_time
                
                # Count total violations
                all_violations = []
                for violations_list in categorized_violations.values():
                    all_violations.extend(violations_list)
                
                metrics = AnalysisMetrics(
                    model_name=model_name,
                    search_strategy=SearchStrategy.DUCKDUCKGO_SEARCH,  # Bedrock always uses DuckDuckGo
                    total_time_seconds=elapsed_time,
                    cost_usd=self._calculate_cost(model_name, tokens_used),
                    gov_citations_count=sum(
                        len([c for c in v.citations if c.is_gov_site]) 
                        for v in all_violations
                ),
                total_citations_count=sum(len(v.citations) for v in all_violations),
                violations_found=len(all_violations),
                avg_confidence_score=sum(v.confidence_score for v in all_violations) / len(all_violations) if all_violations else 0,
                has_law_references=any(
                    c.law_reference for v in all_violations for c in v.citations
                ),
                tokens_used=tokens_used
                )
                
                # Return successful result
                return categorized_violations, metrics, lease_info_data
        
        # If we get here, all models failed
        if last_error:
            logger.error(f"All retries failed. Last error: {str(last_error)}")
            
            # Return empty result with error metrics
            elapsed_time = time.time() - start_time
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.DUCKDUCKGO_SEARCH,
                total_time_seconds=elapsed_time,
                cost_usd=0.0,
                gov_citations_count=0,
                total_citations_count=0,
                violations_found=0,
                avg_confidence_score=0.0,
                has_law_references=False,
                tokens_used={"prompt": 0, "completion": 0, "total": 0}
            )
            
            return {}, metrics, None
    
    def _validate_categorized_response(
        self,
        violations_by_category: Dict[str, List[CategorizedViolation]],
        lease_info_data: Optional[Dict[str, str]]
    ) -> bool:
        """Validate that categorized response has all required fields and quality"""
        required_categories = ["rent_increase", "tenant_owner_rights", "fair_housing_laws", "licensing", "others"]
        
        # Check all categories present
        if not all(cat in violations_by_category for cat in required_categories):
            logger.warning("Missing required categories")
            return False
        
        # Validate each violation has required fields and quality
        for category, violations in violations_by_category.items():
            for v in violations:
                # Check lease_clause is not empty
                if not v.lease_clause or v.lease_clause.strip() == "":
                    logger.warning(f"Empty lease_clause in {category}")
                    return False
                
                # Check has at least one citation
                if not v.citations or len(v.citations) == 0:
                    logger.warning(f"No citations in {category}")
                    return False
                
                # Check confidence score is reasonable
                if v.confidence_score < 0.5 or v.confidence_score > 1.0:
                    logger.warning(f"Invalid confidence score: {v.confidence_score}")
                    return False
        
        return True
    
    def _parse_categorized_violations(
        self,
        response_text: str
    ) -> tuple[Dict[str, List[CategorizedViolation]], Optional[Dict[str, str]]]:
        """Parse categorized violations from model response"""
        
        violations_by_category: Dict[str, List[CategorizedViolation]] = {
            "rent_increase": [],
            "tenant_owner_rights": [],
            "fair_housing_laws": [],
            "licensing": [],
            "others": []
        }
        lease_info_data = None
        
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = self._extract_json_from_markdown(response_text)
            
            if not json_str:
                logger.error("No JSON found in response")
                logger.error(f"Response preview: {response_text[:500]}")
                return violations_by_category, lease_info_data
            
            # Sanitize JSON string to remove invalid control characters
            json_str = self._sanitize_json_string(json_str)
            
            # Log sanitized JSON for debugging (show more for troubleshooting)
            logger.info("="*80)
            logger.info("SANITIZED JSON STRING:")
            logger.info(json_str[:1000] if len(json_str) > 1000 else json_str)
            if len(json_str) > 1000:
                logger.info(f"... (truncated, total length: {len(json_str)} chars)")
            logger.info("="*80)
            
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Found {len(data.get('violations', []))} violations")
            
            # Extract lease info
            lease_info_data = data.get("lease_info", {})
            if lease_info_data:
                logger.info("\n" + "="*80)
                logger.info("AI EXTRACTED LOCATION & LEASE INFO:")
                logger.info(f"  Location: {lease_info_data.get('city')}, {lease_info_data.get('state')} ({lease_info_data.get('county')} County)")
                logger.info(f"  Address: {lease_info_data.get('address')}")
                logger.info(f"  Landlord: {lease_info_data.get('landlord')}")
                logger.info(f"  Tenant: {lease_info_data.get('tenant')}")
                logger.info(f"  Rent: {lease_info_data.get('rent_amount')}")
                logger.info(f"  Deposit: {lease_info_data.get('security_deposit')}")
                logger.info(f"  Duration: {lease_info_data.get('lease_duration')}")
                logger.info("AI used this location to search for .gov laws")
                logger.info("="*80 + "\n")
            
            # Parse violations
            for v_data in data.get("violations", []):
                try:
                    # Parse citations
                    citations = []
                    for c_data in v_data.get("citations", []):
                        try:
                            citation = Citation(
                                source_url=c_data.get("source_url", ""),
                                title=c_data.get("title", ""),
                                relevant_text=c_data.get("relevant_text", ""),
                                law_reference=c_data.get("law_reference"),
                                is_gov_site=c_data.get("is_gov_site", False)
                            )
                            citations.append(citation)
                        except Exception as e:
                            logger.warning(f"Failed to parse citation: {str(e)}")
                            # Continue processing other citations
                            continue
                    
                    # Get category
                    category_str = v_data.get("category", "others").lower()
                    try:
                        category = ViolationCategory(category_str)
                    except ValueError:
                        logger.warning(f"Invalid category '{category_str}', defaulting to 'others'")
                        category = ViolationCategory.OTHERS
                    
                    # Create categorized violation (handle null values gracefully)
                    lease_clause = v_data.get("lease_clause")
                    if lease_clause is None or lease_clause == "null":
                        lease_clause = "No specific clause cited"
                    
                    violation = CategorizedViolation(
                        violation_type=v_data.get("violation_type", "Unknown"),
                        category=category,
                        description=v_data.get("description", ""),
                        severity=v_data.get("severity", "medium"),
                        confidence_score=v_data.get("confidence_score", 0.5),
                        lease_clause=lease_clause,
                        citations=citations,
                        recommended_action=v_data.get("recommended_action") or "Review with legal counsel and amend lease accordingly"
                    )
                    
                    # Add to appropriate category
                    violations_by_category[category.value].append(violation)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse individual violation: {str(e)}")
                    # Continue processing other violations
                    continue
        
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
        except Exception as e:
            logger.error("="*80)
            logger.error(f"UNEXPECTED ERROR in categorized parsing: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
        
        return violations_by_category, lease_info_data
    
    @staticmethod
    def get_available_models() -> List[Dict[str, any]]:
        """Get list of available Bedrock models with metadata"""
        models = []
        
        for model_id in settings.ALL_MODELS:
            pricing = BedrockClient.MODEL_PRICING.get(
                model_id,
                {"input": 0, "output": 0}
            )
            
            # Extract provider from model ID (e.g., "anthropic" from "anthropic.claude...")
            provider = model_id.split(".")[0]
            
            models.append({
                "model_id": model_id,
                "name": model_id.split(".")[-1],  # Get model name after last dot
                "provider": provider,
                "has_native_search": False,  # Bedrock has no native search
                "estimated_cost_per_1k_tokens": pricing,
                "context_length": 200000 if "claude-3" in model_id else 128000  # Claude has 200k context
            })
        
        return models
    
    def evaluate_maintenance_request(
        self,
        maintenance_request: str,
        lease_info: LeaseInfo,
        landlord_notes: Optional[str] = None
    ) -> MaintenanceResponse:
        """
        Evaluate maintenance request against lease - approve or reject based on lease terms
        
        Args:
            maintenance_request: The maintenance issue reported by tenant
            lease_info: Extracted lease information
            landlord_notes: Optional notes/context from landlord
            
        Returns:
            MaintenanceResponse with decision (approved/rejected) and lease-based justification
        """
        model_name = settings.FREE_MODEL
        
        try:
            # Build maintenance evaluation prompt
            prompt = build_maintenance_evaluation_prompt(maintenance_request, lease_info, landlord_notes)
            
            # Format request for Bedrock
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a landlord reviewing a maintenance request. Evaluate it against the lease agreement and decide whether to approve or reject it based ONLY on what the lease says. Be fair and follow the lease terms exactly.",
                user_prompt=prompt
            )
            
            # Make API call
            response_text, _ = self._call_bedrock_with_retry(model_name, body)
            
            # LOG THE FULL RESPONSE
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR MAINTENANCE EVALUATION:")
            logger.info(response_text)
            logger.info("="*80)
            
            # Parse evaluation response
            evaluation_data = self._parse_maintenance_response(response_text, maintenance_request)
            
            return evaluation_data
            
        except Exception as e:
            logger.error(f"Error evaluating maintenance request: {str(e)}")
            
            # Return default approved response on error
            return MaintenanceResponse(
                maintenance_request=maintenance_request,
                decision="approved",
                response_message="We will review your maintenance request and respond shortly.",
                decision_reasons=["Unable to evaluate against lease - defaulting to approval"],
                lease_clauses_cited=[]
            )
    
    def _parse_maintenance_response(
        self,
        response_text: str,
        original_request: str
    ) -> MaintenanceResponse:
        """Parse maintenance evaluation response from model"""
        
        try:
            logger.info("="*80)
            logger.info("PARSING MAINTENANCE RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            # Try multiple extraction methods
            json_str = None
            
            # Method 1: Look for ```json code blocks
            if "```json" in response_text:
                logger.info("Found ```json marker, extracting...")
                parts = response_text.split("```json")
                if len(parts) > 1:
                    json_str = parts[1].split("```")[0].strip()
                    logger.info("Extracted from ```json block")
            
            # Method 2: Look for plain ``` code blocks
            elif "```" in response_text and json_str is None:
                logger.info("Found ``` marker, extracting...")
                parts = response_text.split("```")
                if len(parts) > 1:
                    json_str = parts[1].strip()
                    logger.info("Extracted from ``` block")
            
            # Method 3: Find { to } brackets
            if json_str is None:
                logger.info("No code blocks found, looking for JSON brackets...")
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    logger.info(f"Found JSON from position {json_start} to {json_end}")
                else:
                    logger.error("No JSON brackets found in response")
                    logger.error(f"Full response: {response_text}")
                    return MaintenanceResponse(
                        maintenance_request=original_request,
                        decision="approved",
                        response_message="We will review your maintenance request and respond shortly.",
                        decision_reasons=["Unable to parse lease evaluation"],
                        lease_clauses_cited=[]
                    )
            
            # Sanitize JSON string to remove invalid control characters
            json_str = self._sanitize_json_string(json_str)
            
            # Log what we're about to parse
            logger.info("SANITIZED JSON STRING TO PARSE:")
            logger.info(json_str)
            logger.info("="*80)
            
            # Parse the JSON
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Keys found: {list(data.keys())}")
            logger.info(f"Decision: {data.get('decision', 'unknown')}")
            
            return MaintenanceResponse(
                maintenance_request=original_request,
                decision=data.get("decision", "approved"),
                response_message=data.get("response_message", "We will review your request."),
                decision_reasons=data.get("decision_reasons", []),
                lease_clauses_cited=data.get("lease_clauses_cited", []),
                landlord_responsibility_clause=data.get("landlord_responsibility_clause"),
                tenant_responsibility_clause=data.get("tenant_responsibility_clause"),
                estimated_timeline=data.get("estimated_timeline"),
                alternative_action=data.get("alternative_action")
            )
        
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            logger.error(f"JSON string that failed:")
            logger.error(json_str if json_str else "N/A")
            logger.error("="*80)
            return MaintenanceResponse(
                maintenance_request=original_request,
                decision="approved",
                response_message="We will review your maintenance request and respond shortly.",
                decision_reasons=["Error parsing lease evaluation - defaulting to approval"],
                lease_clauses_cited=[]
            )
        except Exception as e:
            logger.error("="*80)
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
            return MaintenanceResponse(
                maintenance_request=original_request,
                decision="approved",
                response_message="We will review your maintenance request and respond shortly.",
                decision_reasons=[f"Error processing request: {type(e).__name__}"],
                lease_clauses_cited=[]
            )

    def generate_vendor_work_order(
        self,
        maintenance_request: str,
        lease_info: LeaseInfo,
        landlord_notes: Optional[str] = None
    ) -> VendorWorkOrder:
        """
        Generate a professional work order for vendor to fix maintenance issue
        
        Args:
            maintenance_request: The maintenance issue reported by tenant
            lease_info: Extracted lease information
            landlord_notes: Optional notes/context from landlord
            
        Returns:
            VendorWorkOrder with detailed instructions for vendor
        """
        model_name = settings.FREE_MODEL
        
        try:
            # Build vendor work order prompt
            prompt = build_vendor_work_order_prompt(maintenance_request, lease_info, landlord_notes)
            
            # Format request for Bedrock
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a property management assistant creating professional work orders for vendors. Generate clear, detailed work orders that help vendors understand exactly what needs to be fixed.",
                user_prompt=prompt
            )
            
            # Make API call
            response_text, _ = self._call_bedrock_with_retry(model_name, body)
            
            # LOG THE FULL RESPONSE
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR VENDOR WORK ORDER:")
            logger.info(response_text)
            logger.info("="*80)
            
            # Parse work order response
            work_order_data = self._parse_vendor_response(response_text, maintenance_request)
            
            return work_order_data
            
        except Exception as e:
            logger.error(f"Error generating vendor work order: {str(e)}")
            
            # Return basic work order on error
            return VendorWorkOrder(
                maintenance_request=maintenance_request,
                work_order_title="Maintenance Request",
                comprehensive_description=f"Please address the following maintenance issue: {maintenance_request}. Property and tenant details are available in the lease document.",
                urgency_level="routine"
            )
    

    
    def _parse_vendor_response(
        self,
        response_text: str,
        original_request: str
    ) -> VendorWorkOrder:
        """Parse vendor work order response from model"""
        
        try:
            logger.info("="*80)
            logger.info("PARSING VENDOR WORK ORDER RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            # Try multiple extraction methods
            json_str = None
            
            # Method 1: Look for ```json code blocks
            if "```json" in response_text:
                logger.info("Found ```json marker, extracting...")
                parts = response_text.split("```json")
                if len(parts) > 1:
                    json_str = parts[1].split("```")[0].strip()
                    logger.info("Extracted from ```json block")
            
            # Method 2: Look for plain ``` code blocks
            elif "```" in response_text and json_str is None:
                logger.info("Found ``` marker, extracting...")
                parts = response_text.split("```")
                if len(parts) > 1:
                    json_str = parts[1].strip()
                    logger.info("Extracted from ``` block")
            
            # Method 3: Find { to } brackets
            if json_str is None:
                logger.info("No code blocks found, looking for JSON brackets...")
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    logger.info(f"Found JSON from position {json_start} to {json_end}")
                else:
                    logger.error("No JSON brackets found in response")
                    logger.error(f"Full response: {response_text}")
                    return VendorWorkOrder(
                        maintenance_request=original_request,
                        work_order_title="Maintenance Request",
                        comprehensive_description=f"Please address: {original_request}. Property details in lease.",
                        urgency_level="routine"
                    )
            
            # Sanitize JSON string to remove invalid control characters
            json_str = self._sanitize_json_string(json_str)
            
            # Log what we're about to parse
            logger.info("SANITIZED JSON STRING TO PARSE:")
            logger.info(json_str)
            logger.info("="*80)
            
            # Parse the JSON
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Keys found: {list(data.keys())}")
            logger.info(f"Work order title: {data.get('work_order_title', 'unknown')}")
            
            return VendorWorkOrder(
                maintenance_request=original_request,
                work_order_title=data.get("work_order_title", "Maintenance Work Order"),
                comprehensive_description=data.get("comprehensive_description", f"Please address: {original_request}"),
                urgency_level=data.get("urgency_level", "routine")
            )
        
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            logger.error(f"JSON string that failed:")
            logger.error(json_str if json_str else "N/A")
            logger.error("="*80)
            return VendorWorkOrder(
                maintenance_request=original_request,
                work_order_title="Maintenance Request",
                comprehensive_description=f"Please address: {original_request}. Property details in lease.",
                urgency_level="routine"
            )
        except Exception as e:
            logger.error("="*80)
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
            return VendorWorkOrder(
                maintenance_request=original_request,
                work_order_title="Maintenance Request",
                comprehensive_description=f"Please address: {original_request}. Property details in lease.",
                urgency_level="routine"
            )

    
    def process_maintenance_workflow(
        self,
        maintenance_request: str,
        lease_info: LeaseInfo,
        landlord_notes: Optional[str] = None
    ) -> MaintenanceWorkflow:
        """Complete maintenance workflow: Evaluate + Generate tenant message + Create vendor work order"""
        model_name = settings.FREE_MODEL
        
        try:
            prompt = build_maintenance_workflow_prompt(maintenance_request, lease_info, landlord_notes)
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a property management assistant. Evaluate maintenance requests against lease agreements, generate professional messages for tenants, and create detailed work orders for vendors. Be fair, professional, and thorough.",
                user_prompt=prompt
            )
            
            response_text, _ = self._call_bedrock_with_retry(model_name, body)
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR MAINTENANCE WORKFLOW:")
            logger.info(response_text)
            logger.info("="*80)
            
            workflow_data = self._parse_workflow_response(response_text, maintenance_request)
            return workflow_data
            
        except Exception as e:
            logger.error(f"Error processing maintenance workflow: {str(e)}")
            return MaintenanceWorkflow(
                maintenance_request=maintenance_request,
                tenant_message="We have received your maintenance request and will respond shortly.",
                tenant_message_tone="neutral",
                decision="approved",
                decision_reasons=["Unable to evaluate against lease - defaulting to approval"],
                lease_clauses_cited=[],
                vendor_work_order=None,
                estimated_timeline=None,
                alternative_action=None
            )
    

    
    def _parse_workflow_response(self, response_text: str, original_request: str) -> MaintenanceWorkflow:
        """Parse maintenance workflow response from model"""
        try:
            logger.info("="*80)
            logger.info("PARSING MAINTENANCE WORKFLOW RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            json_str = None
            if "```json" in response_text:
                logger.info("Found ```json marker, extracting...")
                parts = response_text.split("```json")
                if len(parts) > 1:
                    json_str = parts[1].split("```")[0].strip()
            elif "```" in response_text and json_str is None:
                logger.info("Found ``` marker, extracting...")
                parts = response_text.split("```")
                if len(parts) > 1:
                    json_str = parts[1].strip()
            
            if json_str is None:
                logger.info("No code blocks found, looking for JSON brackets...")
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                else:
                    logger.error("No JSON brackets found in response")
                    return MaintenanceWorkflow(
                        maintenance_request=original_request,
                        tenant_message="We have received your maintenance request and will respond shortly.",
                        tenant_message_tone="neutral",
                        decision="approved",
                        decision_reasons=["Unable to parse evaluation"],
                        lease_clauses_cited=[],
                        vendor_work_order=None
                    )
            
            json_str = self._sanitize_json_string(json_str)
            logger.info("SANITIZED JSON STRING TO PARSE:")
            logger.info(json_str)
            logger.info("="*80)
            
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Keys found: {list(data.keys())}")
            logger.info(f"Decision: {data.get('decision', 'unknown')}")
            
            vendor_work_order = None
            if data.get("vendor_work_order") is not None:
                wo_data = data["vendor_work_order"]
                vendor_work_order = VendorWorkOrder(
                    maintenance_request=original_request,
                    work_order_title=wo_data.get("work_order_title", "Maintenance Work Order"),
                    comprehensive_description=wo_data.get("comprehensive_description", f"Please address: {original_request}"),
                    urgency_level=wo_data.get("urgency_level", "routine")
                )
            
            return MaintenanceWorkflow(
                maintenance_request=original_request,
                tenant_message=data.get("tenant_message", "We will review your request and respond shortly."),
                tenant_message_tone=data.get("tenant_message_tone", "neutral"),
                decision=data.get("decision", "approved"),
                decision_reasons=data.get("decision_reasons", []),
                lease_clauses_cited=data.get("lease_clauses_cited", []),
                vendor_work_order=vendor_work_order,
                estimated_timeline=data.get("estimated_timeline"),
                alternative_action=data.get("alternative_action")
            )
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"JSON string that failed: {json_str if 'json_str' in locals() else 'N/A'}")
            logger.error("="*80)
            return MaintenanceWorkflow(
                maintenance_request=original_request,
                tenant_message="We will review your maintenance request and respond shortly.",
                tenant_message_tone="neutral",
                decision="approved",
                decision_reasons=["Error parsing evaluation - defaulting to approval"],
                lease_clauses_cited=[],
                vendor_work_order=None
            )
        except Exception as e:
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            return MaintenanceWorkflow(
                maintenance_request=original_request,
                tenant_message="We will review your maintenance request and respond shortly.",
                tenant_message_tone="neutral",
                decision="approved",
                decision_reasons=[f"Error processing request: {type(e).__name__}"],
                lease_clauses_cited=[],
                vendor_work_order=None
            )
    
    def rewrite_tenant_message(self, tenant_message: str) -> TenantMessageRewrite:
        """Rewrite tenant's maintenance message to be more professional and clear"""
        model_name = settings.FREE_MODEL
        
        try:
            prompt = build_tenant_message_rewrite_prompt(tenant_message)
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a helpful assistant that helps tenants communicate maintenance issues clearly and professionally to their landlords. Rewrite messages to be polite, detailed, and effective.",
                user_prompt=prompt
            )
            
            response_text, _ = self._call_bedrock_with_retry(model_name, body)
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR TENANT MESSAGE REWRITE:")
            logger.info(response_text)
            logger.info("="*80)
            
            rewrite_data = self._parse_tenant_rewrite_response(response_text, tenant_message)
            return rewrite_data
            
        except Exception as e:
            logger.error(f"Error rewriting tenant message: {str(e)}")
            return TenantMessageRewrite(
                original_message=tenant_message,
                rewritten_message=tenant_message,
                improvements_made=["Unable to rewrite - using original message"],
                tone="original",
                estimated_urgency="routine"
            )
    

    
    def _parse_tenant_rewrite_response(self, response_text: str, original_message: str) -> TenantMessageRewrite:
        """Parse tenant message rewrite response from model"""
        try:
            logger.info("="*80)
            logger.info("PARSING TENANT MESSAGE REWRITE RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            json_str = None
            if "```json" in response_text:
                parts = response_text.split("```json")
                if len(parts) > 1:
                    json_str = parts[1].split("```")[0].strip()
            elif "```" in response_text and json_str is None:
                parts = response_text.split("```")
                if len(parts) > 1:
                    json_str = parts[1].strip()
            
            if json_str is None:
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                else:
                    return TenantMessageRewrite(
                        original_message=original_message,
                        rewritten_message=original_message,
                        improvements_made=["Unable to parse AI response"],
                        tone="original",
                        estimated_urgency="routine"
                    )
            
            json_str = self._sanitize_json_string(json_str)
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=data.get("rewritten_message", original_message),
                improvements_made=data.get("improvements_made", []),
                tone=data.get("tone", "professional"),
                estimated_urgency=data.get("estimated_urgency", "routine")
            )
        except json.JSONDecodeError as e:
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=original_message,
                improvements_made=["JSON parsing error - using original"],
                tone="original",
                estimated_urgency="routine"
            )
        except Exception as e:
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=original_message,
                improvements_made=[f"Error: {type(e).__name__}"],
                tone="original",
                estimated_urgency="routine"
            )
    
    def evaluate_move_out_request(self, move_out_request: str, lease_info: LeaseInfo, owner_notes: Optional[str] = None) -> MoveOutResponse:
        """Evaluate tenant move-out request against lease terms"""
        model_name = settings.FREE_MODEL
        
        try:
            prompt = build_move_out_evaluation_prompt(move_out_request, lease_info, owner_notes)
            body = self._format_messages_for_bedrock(
                model_id=model_name,
                system_prompt="You are a property owner evaluating a tenant's move-out request. Check if they provided proper notice according to the lease, calculate any financial obligations, and provide clear next steps.",
                user_prompt=prompt
            )
            
            response_text, _ = self._call_bedrock_with_retry(model_name, body)
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR MOVE-OUT EVALUATION:")
            logger.info(response_text)
            logger.info("="*80)
            
            evaluation_data = self._parse_move_out_response(response_text, move_out_request)
            return evaluation_data
            
        except Exception as e:
            logger.error(f"Error evaluating move-out request: {str(e)}")
            return MoveOutResponse(
                move_out_request=move_out_request,
                decision="requires_attention",
                response_message="We received your move-out request and will review it shortly.",
                notice_period_valid=False,
                notice_period_required="Unknown - Error evaluating lease",
                notice_period_given="Unable to determine",
                move_out_date="Unknown",
                financial_summary={"rent_owed": "Unable to calculate", "security_deposit": "Will be reviewed", "other_fees": "To be determined"},
                lease_clauses_cited=[],
                next_steps=["We will evaluate your notice period and respond within 2 business days"]
            )
    

    
    def _parse_move_out_response(self, response_text: str, original_request: str) -> MoveOutResponse:
        """Parse move-out evaluation response from model"""
        try:
            logger.info("="*80)
            logger.info("PARSING MOVE-OUT RESPONSE")
            logger.info(f"Response length: {len(response_text)} characters")
            logger.info("="*80)
            
            json_str = None
            if "```json" in response_text:
                parts = response_text.split("```json")
                if len(parts) > 1:
                    json_str = parts[1].split("```")[0].strip()
            elif "```" in response_text and json_str is None:
                parts = response_text.split("```")
                if len(parts) > 1:
                    json_str = parts[1].strip()
            
            if json_str is None:
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                if json_start != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end]
                else:
                    return MoveOutResponse(
                        move_out_request=original_request,
                        decision="requires_attention",
                        response_message="We received your move-out request and will review it shortly.",
                        notice_period_valid=False,
                        notice_period_required="Unable to determine",
                        notice_period_given="Unable to determine",
                        move_out_date="Unknown",
                        financial_summary={"rent_owed": "Unable to calculate", "security_deposit": "Will be reviewed", "other_fees": "None specified"},
                        lease_clauses_cited=[],
                        next_steps=["We will evaluate your request and respond within 2 business days"]
                    )
            
            json_str = self._sanitize_json_string(json_str)
            data = json.loads(json_str)
            logger.info("JSON PARSED SUCCESSFULLY!")
            logger.info(f"Notice valid: {data.get('notice_period_valid', 'unknown')}")
            
            financial_summary = {
                "rent_owed": data.get("rent_owed", "To be calculated"),
                "security_deposit": data.get("security_deposit_status", "Will be reviewed"),
                "other_fees": data.get("other_fees", "None specified"),
                "last_day": data.get("last_day_allowed", "Unknown")
            }
            
            decision = "approved" if data.get("notice_period_valid", False) else "requires_attention"
            
            return MoveOutResponse(
                move_out_request=original_request,
                decision=decision,
                response_message=data.get("response_message", "We will review your move-out request."),
                notice_period_valid=data.get("notice_period_valid", False),
                notice_period_required=data.get("notice_period_required"),
                notice_period_given=data.get("notice_period_provided"),
                move_out_date=data.get("last_day_allowed"),
                financial_summary=financial_summary,
                lease_clauses_cited=data.get("lease_clauses_cited", []),
                penalties_or_fees=None,
                next_steps=data.get("next_steps", ["We will respond within 2 business days"]),
                estimated_refund_timeline=None
            )
        except json.JSONDecodeError as e:
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            return MoveOutResponse(
                move_out_request=original_request,
                decision="requires_attention",
                response_message="We received your move-out request and will review it shortly.",
                notice_period_valid=False,
                notice_period_required="Unknown - Error parsing",
                notice_period_given="Unknown",
                move_out_date="Unknown",
                financial_summary={"rent_owed": "Unable to calculate", "security_deposit": "Will be reviewed", "other_fees": "None specified"},
                lease_clauses_cited=[],
                next_steps=["Error parsing lease - will respond manually within 2 business days"]
            )
        except Exception as e:
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            return MoveOutResponse(
                move_out_request=original_request,
                decision="requires_attention",
                response_message="We received your move-out request and will review it shortly.",
                notice_period_valid=False,
                notice_period_required="Unknown - Error occurred",
                notice_period_given="Unknown",
                move_out_date="Unknown",
                financial_summary={"rent_owed": "Unable to calculate", "security_deposit": "Will be reviewed", "other_fees": "None specified"},
                lease_clauses_cited=[],
                next_steps=[f"Error processing request - will respond manually within 2 business days"]
            )
    
    def maintenance_chat(self, conversation_history: List[ChatMessage]) -> MaintenanceChatResponse:
        """Handle maintenance assistant chatbot conversation with context awareness"""
        start_time = time.time()
        
        try:
            if not conversation_history or conversation_history[-1].role != "user":
                raise ValueError("Last message in conversation history must be from user")
            
            user_message = conversation_history[-1].content.lower()
            emergency_keywords = [
                "smell gas", "gas leak", "rotten egg smell", "gas smell",
                "smell smoke", "see smoke", "sparks", "burning smell", "smoke detector",
                "fire alarm", "co detector", "carbon monoxide",
                "flooding", "water pouring", "ceiling bulging", "ceiling sagging",
                "exposed wire", "outlet hot", "outlet burning", "outlet spark",
                "no heat", "no ac", "locked out", "can't close door", "door won't lock",
                "front door", "exterior door", "window broken", "window won't close"
            ]
            
            has_emergency = any(keyword in user_message for keyword in emergency_keywords)
            
            if has_emergency:
                logger.warning(f"Emergency keyword detected in maintenance chat: {user_message[:100]}")
                return MaintenanceChatResponse(
                    response="This could be an emergency. If you smell gas, see or smell smoke, see sparks, or feel unsafe, please call 911 or your local emergency number immediately. After that, please contact your property's emergency maintenance line. I can help you submit an urgent maintenance request.",
                    suggestTicket=True
                )
            
            system_prompt = MAINTENANCE_CHAT_SYSTEM_PROMPT
            
            messages = [{"role": msg.role, "content": msg.content} for msg in conversation_history]
            
            # Format for Llama - Use Llama 3.1 70B (fast, reliable)
            user_prompt = "\n\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in messages])
            
            # Use Llama 3.1 70B Instruct
            llama_model = "us.meta.llama3-1-70b-instruct-v1:0"
            
            # Create system prompt - simpler and clearer
            simple_system = """You are a maintenance assistant. Help tenants troubleshoot issues.

RESPONSE FORMAT (IMPORTANT):
Return JSON: {"response": "your message", "suggestTicket": false}

RULES:
- "response" is plain text (your message)
- "suggestTicket" is true when professional help needed
- Keep responses short (2-3 sentences)
- Ask questions to understand the issue
- Suggest only safe solutions
- Set suggestTicket=true after 3-4 exchanges without resolution"""
            
            body = {
                "prompt": f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{simple_system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{user_prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
                "max_gen_len": 512,
                "temperature": 0.3,
                "top_p": 0.9
            }
            
            response_text, _ = self._call_bedrock_with_retry(llama_model, body)
            elapsed_time = time.time() - start_time
            
            logger.info(f"Maintenance chat response received in {elapsed_time:.2f}s")
            logger.debug(f"Raw AI response (first 300 chars): {response_text[:300]}")
            
            try:
                # Extract JSON from markdown if present
                json_str = self._extract_json_from_markdown(response_text)
                if not json_str:
                    json_str = response_text.strip()
                
                # First attempt: parse directly
                try:
                    parsed = json.loads(json_str)
                    logger.debug("✓ Direct JSON parse successful")
                except json.JSONDecodeError as e1:
                    # Second attempt: sanitize and retry
                    logger.debug(f"Direct parse failed ({e1}), trying sanitized version...")
                    json_str_sanitized = self._sanitize_json_string(json_str)
                    try:
                        parsed = json.loads(json_str_sanitized)
                        logger.debug("✓ Sanitized JSON parse successful")
                    except json.JSONDecodeError as e2:
                        # Third attempt: Try to fix common issues manually
                        logger.debug(f"Sanitized parse also failed ({e2}), manual fix attempt...")
                        # Replace actual newlines and tabs in string values with escape sequences
                        json_str_fixed = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                        parsed = json.loads(json_str_fixed)
                        logger.debug("✓ Manual fix successful")
                
                # Get values from parsed JSON
                response_value = parsed.get("response", "")
                suggest_ticket = parsed.get("suggestTicket", False)
                
                # Fix double-encoding: check if response is a JSON string instead of plain text
                if isinstance(response_value, str) and response_value.strip().startswith("{"):
                    logger.warning("⚠️ Detected double-encoded JSON in response field")
                    try:
                        # Parse inner JSON
                        inner = json.loads(response_value)
                        if isinstance(inner, dict) and "response" in inner:
                            # Extract the actual values from inner JSON
                            response_value = inner.get("response", response_value)
                            suggest_ticket = inner.get("suggestTicket", suggest_ticket)
                            logger.info("✅ Successfully fixed double-encoded JSON")
                    except json.JSONDecodeError:
                        # If can't parse, treat the whole thing as plain text (keep as-is)
                        logger.debug("Could not parse inner JSON, keeping original value")
                
                return MaintenanceChatResponse(
                    response=response_value,
                    suggestTicket=suggest_ticket
                )
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ All JSON parse attempts failed: {e}")
                logger.debug(f"Failed to parse: {response_text[:500]}")
                # Fallback: use raw response
                suggest_ticket = any(phrase in response_text.lower() for phrase in [
                    "create a maintenance ticket", "create a ticket", "professional attention",
                    "needs a professional", "call maintenance"
                ])
                
                return MaintenanceChatResponse(
                    response=response_text,
                    suggestTicket=suggest_ticket
                )
        
        except Exception as e:
            logger.error(f"Error in maintenance chat: {str(e)}")
            raise AIModelError(message="Failed to process chat message", details=str(e))
    
    def generate_text(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3
    ) -> str:
        """
        Generate text using specified Bedrock model
        
        Args:
            model_id: Bedrock model identifier
            system_prompt: System instructions for the model
            user_prompt: User message/prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0.0-1.0)
            
        Returns:
            Generated text response
            
        Raises:
            AIModelError: If generation fails
        """
        try:
            body = self._format_messages_for_bedrock(
                model_id=model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            
            # Add max_tokens and temperature to body
            if "anthropic" in model_id.lower():
                body["max_tokens"] = max_tokens
                body["temperature"] = temperature
            elif "meta.llama" in model_id.lower():
                body["max_gen_len"] = max_tokens
                body["temperature"] = temperature
            
            response_text, _ = self._call_bedrock_with_retry(model_id, body)
            return response_text
            
        except Exception as e:
            logger.error(f"Error generating text: {str(e)}")
            raise AIModelError(message="Failed to generate text", details=str(e))
    
    def extract_maintenance_request_from_chat(
        self,
        conversation_history: List[ChatMessage]
    ) -> MaintenanceRequestExtraction:
        """
        Extract title and description from tenant chat for maintenance request.
        Uses Haiku for fast, cost-effective extraction.
        
        Args:
            conversation_history: Complete chat conversation
            
        Returns:
            MaintenanceRequestExtraction with title and description
        """
        try:
            start_time = time.time()
            logger.info("Extracting maintenance request from chat conversation")
            
            # Use Haiku (fast and cheap)
            model = settings.FREE_MODEL
            
            # Build conversation context
            messages = [{"role": msg.role, "content": msg.content} for msg in conversation_history]
            
            # Use prompt builder from chat_prompts module
            # Note: build_maintenance_extraction_prompt returns a full extraction prompt
            # We'll use a simpler inline version for title/description extraction
            conversation_text = "\n\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in messages])
            
            system_prompt = """Extract a maintenance request from the tenant's conversation.

INSTRUCTIONS:
- Extract whatever information is available, even if limited
- If details are vague or missing, note that in the description
- If tenant was non-communicative, summarize what the assistant suggested
- Always provide a title and description based on available information

OUTPUT REQUIREMENTS:
1. Title: Brief summary of the issue (max 80 characters)
2. Description: Include all available details. If information is limited, state what is known and what is unclear.

RESPONSE FORMAT (JSON only):
{
  "title": "brief issue summary",
  "description": "complete description with all available details"
}

EXAMPLES:
- Vague conversation: {"title": "Door lock issue", "description": "Tenant reported a broken door lock but did not provide specific details about the problem. May require on-site inspection to diagnose."}
- Clear conversation: {"title": "Master bathroom shower low water pressure", "description": "Shower has low water pressure. The shower head is fixed to the pipe and cannot be removed."}"""

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 300,  # Low token limit - extraction is brief
                "temperature": 0.0,  # Deterministic
                "system": system_prompt,
                "messages": [{"role": "user", "content": f"Extract maintenance request from this conversation:\n\n{conversation_text}"}]
            }
            
            response_text, _ = self._call_bedrock_with_retry(model, body)
            elapsed_time = time.time() - start_time
            
            logger.info(f"Extraction completed in {elapsed_time:.2f}s")
            
            # Parse JSON response
            json_str = self._extract_json_from_markdown(response_text)
            if not json_str:
                json_str = response_text
            
            json_str = self._sanitize_json_string(json_str)
            parsed = json.loads(json_str)
            
            # Truncate title to 80 chars if needed
            title = parsed.get("title", "Maintenance request")[:80]
            description = parsed.get("description", "Issue reported through chat")
            
            return MaintenanceRequestExtraction(
                title=title,
                description=description
            )
            
        except Exception as e:
            logger.error(f"Error extracting maintenance request: {str(e)}")
            raise AIModelError(message="Failed to extract maintenance request", details=str(e))
