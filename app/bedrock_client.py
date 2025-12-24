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
    MaintenanceChatResponse
)
from app.exceptions import AITimeoutError, AIModelError

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
            prompt = self._build_analysis_prompt(lease_info, search_results, use_native_search=False)
            
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
    
    def _build_analysis_prompt(
        self,
        lease_info: LeaseInfo,
        search_results: Optional[List[Dict[str, str]]],
        use_native_search: bool
    ) -> str:
        """Build the analysis prompt"""
        
        prompt = f"""Analyze the following lease agreement for potential violations of landlord-tenant laws.

FULL LEASE TEXT:
{lease_info.full_text[:25000]}  # Increased for comprehensive analysis

"""
        
        if use_native_search:
            # ALL models should be instructed to search the web
            prompt += """
INSTRUCTIONS:
1. FIRST: Extract key information from the lease:
   - Property location (address, city, state, county)
   - Landlord name
   - Tenant name
   - Monthly rent amount
   - Security deposit amount
   - Lease duration/term
2. Search the web for relevant landlord-tenant laws from .gov websites for that location
3. Prioritize government sources: state, county, and city .gov websites
4. Look for specific statutes, codes, and regulations that apply to this jurisdiction
5. Identify any violations or potential issues in the lease
6. For each violation found, provide:
   - Violation type and description
   - Severity (low, medium, high, critical)
   - Confidence score (0.0 to 1.0)
   - Specific lease clause that violates the law
   - Citations with .gov source URLs and specific law references (e.g., "State Code § 123.45")

Return your analysis in the following JSON format:
```json
{
  "lease_info": {
    "address": "full property address or null",
    "city": "city name or null",
    "state": "2-letter state code or null",
    "county": "county name or null",
    "landlord": "landlord name or null",
    "tenant": "tenant name or null",
    "rent_amount": "monthly rent (e.g., '$1,500') or null",
    "security_deposit": "security deposit amount or null",
    "lease_duration": "lease term (e.g., '12 months', 'month-to-month') or null"
  },
  "violations": [
    {
      "violation_type": "string",
      "description": "string",
      "severity": "low|medium|high|critical",
      "confidence_score": 0.0-1.0,
      "lease_clause": "exact text from lease",
      "citations": [
        {
          "source_url": ".gov URL",
          "title": "page title",
          "relevant_text": "specific text from source",
          "law_reference": "e.g., State Code § 123.45",
          "is_gov_site": true|false
        }
      ]
    }
  ]
}
```
"""
        else:
            # DuckDuckGo search results provided
            prompt += "\nRELEVANT LAW SEARCH RESULTS (from DuckDuckGo):\n"
            if search_results:
                for i, result in enumerate(search_results[:10], 1):
                    prompt += f"\n{i}. {result['title']}\n"
                    prompt += f"   URL: {result['url']}\n"
                    prompt += f"   {result['snippet']}\n"
            else:
                prompt += "No search results provided.\n"
            
            prompt += """
INSTRUCTIONS:
1. FIRST: Extract key information from the lease:
   - Property location (address, city, state, county)
   - Landlord name
   - Tenant name
   - Monthly rent amount
   - Security deposit amount
   - Lease duration/term
2. Review the DuckDuckGo search results (prioritize .gov sources)
3. Identify any violations or potential issues in the lease based on the laws found
4. For each violation found, provide:
   - Violation type and description
   - Severity (low, medium, high, critical)
   - Confidence score (0.0 to 1.0)
   - Specific lease clause that violates the law
   - Citations from the search results above with specific law references when available

Return your analysis in the following JSON format:
```json
{
  "lease_info": {
    "address": "full property address or null",
    "city": "city name or null",
    "state": "2-letter state code or null",
    "county": "county name or null",
    "landlord": "landlord name or null",
    "tenant": "tenant name or null",
    "rent_amount": "monthly rent (e.g., '$1,500') or null",
    "security_deposit": "security deposit amount or null",
    "lease_duration": "lease term (e.g., '12 months', 'month-to-month') or null"
  },
  "violations": [
    {
      "violation_type": "string",
      "description": "string",
      "severity": "low|medium|high|critical",
      "confidence_score": 0.0-1.0,
      "lease_clause": "exact text from lease",
      "citations": [
        {
          "source_url": "URL from search results",
          "title": "title from search results",
          "relevant_text": "specific relevant text",
          "law_reference": "specific law code if available",
          "is_gov_site": true|false
        }
      ]
    }
  ]
}
```
"""
        
        return prompt
    
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
                    prompt = self._build_categorized_prompt(lease_info)
                    logger.info(f"Prompt size: {len(prompt)} characters")
                    
                    # Format request for Bedrock with strict JSON instructions
                    system_prompt = """You are a legal AI that analyzes lease agreements. 

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no code blocks, no explanations
2. Your response MUST start with { and end with }
3. Never wrap JSON in ```json``` or ``` markers
4. All string values must be properly escaped
5. Confidence scores must be consistent and based on citation quality
6. Extract exact lease clause text - never leave lease_clause empty

Focus on accuracy, consistency, and completeness."""
                    
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
    
    def _build_categorized_prompt(self, lease_info: LeaseInfo) -> str:
        """Build an optimized, concise categorized analysis prompt"""
        
        prompt = f"""Analyze this lease for landlord-tenant law violations.

LEASE TEXT:
{lease_info.full_text[:60000]}

TASK:
1. Extract lease info (address, city, state, county, landlord, tenant, rent, deposit, duration)
2. Search .gov websites for relevant landlord-tenant laws at that location
3. Identify violations and categorize as: rent_increase, tenant_owner_rights, fair_housing_laws, licensing, or others
4. For each violation: provide category, type, description, severity, confidence (0-1), **exact lease clause text** (REQUIRED), recommended_action (1-2 sentences), and .gov citations

CRITICAL RULES:
- Return ONLY the JSON object - your response MUST start with opening brace and end with closing brace
- NO markdown code blocks - just raw JSON
- "lease_clause" MUST contain exact quoted text from the lease (NEVER null/empty)
- If no specific clause exists, quote the relevant section or write "General lease structure"
- "confidence_score" must be consistent: 0.9+ for clear violations with .gov citations, 0.7-0.9 for moderate evidence, 0.5-0.7 for potential issues
- All fields are REQUIRED except those marked "or null"
- Ensure ALL citations are from .gov websites (state, county, city official sources)

OUTPUT FORMAT (raw JSON only - NO code blocks):
{{
  "lease_info": {{
    "address": "string or null",
    "city": "string or null",
    "state": "2-letter code or null",
    "county": "string or null",
    "landlord": "string or null",
    "tenant": "string or null",
    "rent_amount": "$X,XXX or null",
    "security_deposit": "$X,XXX or null",
    "lease_duration": "X months or null"
  }},
  "violations": [
    {{
      "category": "rent_increase|tenant_owner_rights|fair_housing_laws|licensing|others",
      "violation_type": "brief title",
      "description": "detailed explanation of violation",
      "severity": "low|medium|high|critical",
      "confidence_score": 0.0-1.0,
      "lease_clause": "REQUIRED: exact quoted text from lease (never null)",
      "recommended_action": "Actionable fix (1-2 sentences)",
      "citations": [
        {{
          "source_url": ".gov URL",
          "title": "source title",
          "relevant_text": "relevant excerpt",
          "law_reference": "Code § X.XX",
          "is_gov_site": true
        }}
      ]
    }}
  ]
}}

REMEMBER: Your entire response must be ONLY the JSON object above. Start with opening brace and end with closing brace. No other text.
"""
        
        return prompt
    
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
            prompt = self._build_maintenance_prompt(maintenance_request, lease_info, landlord_notes)
            
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
    
    def _build_maintenance_prompt(self, maintenance_request: str, lease_info: LeaseInfo, landlord_notes: Optional[str] = None) -> str:
        """Build the maintenance evaluation prompt"""
        
        prompt = f"""You are a landlord reviewing a maintenance request. Evaluate it against the lease agreement and decide whether to APPROVE or REJECT based ONLY on the lease terms.

MAINTENANCE REQUEST FROM TENANT:
{maintenance_request}
"""
        
        # Add landlord notes if provided
        if landlord_notes:
            prompt += f"""
LANDLORD'S NOTES/CONTEXT:
{landlord_notes}

NOTE: Consider the landlord's notes when crafting the response, but the DECISION must still be based on the lease agreement.
"""
        
        prompt += f"""
LEASE DOCUMENT:
{lease_info.full_text[:6000]}

INSTRUCTIONS:
1. Review the lease carefully to determine maintenance responsibilities
2. Look for clauses about:
   - Landlord's maintenance obligations
   - Tenant's maintenance responsibilities
   - Specific exclusions or limitations
   - Who is responsible for different types of repairs
3. Make a FAIR decision based on the lease:
   - APPROVE if lease says landlord must handle this type of maintenance
   - REJECT if lease clearly states tenant is responsible
   - APPROVE if unclear or not mentioned in lease (default to landlord responsibility)
"""
        
        if landlord_notes:
            prompt += """4. Incorporate the landlord's notes into the response_message (be professional and tactful)
5. Cite EXACT lease clauses to support your decision
6. Write a professional response message
"""
        else:
            prompt += """4. Cite EXACT lease clauses to support your decision
5. Write a professional response message
"""
        
        prompt += """
IMPORTANT: Return ONLY valid JSON. Do not include any text before or after the JSON.

Return your evaluation in this exact JSON format:
{
  "decision": "approved" or "rejected",
  "response_message": "Professional message from landlord to tenant (2-4 sentences)",
  "decision_reasons": ["Reason 1 based on lease", "Reason 2 based on lease"],
  "lease_clauses_cited": ["Exact quote from lease clause 1", "Exact quote from lease clause 2"],
  "landlord_responsibility_clause": "Clause stating landlord must fix, or null",
  "tenant_responsibility_clause": "Clause stating tenant is responsible, or null",
  "estimated_timeline": "Timeline for repair from lease if approved, or null",
  "alternative_action": "What tenant should do instead if rejected, or null"
}

Examples:
- If lease says "Landlord shall maintain heating systems" → APPROVE heater repairs
- If lease says "Tenant responsible for appliance maintenance" → REJECT appliance repairs
- If lease doesn't mention the issue → APPROVE (landlord's duty)
"""
        
        if landlord_notes:
            prompt += """- If landlord notes say "Already fixed last week" → Include in response_message professionally
- If landlord notes say "Tenant caused damage" → Consider in response, cite damage clause if in lease

"""
        
        prompt += """Rules:
- Be FAIR - follow the lease exactly
- Write response_message as if you ARE the landlord speaking to tenant
- Be professional and clear
- ONLY use information from the lease for the DECISION
- Incorporate landlord notes naturally into the response if provided
- Return ONLY the JSON object, nothing else
"""
        
        return prompt
    
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
            prompt = self._build_vendor_prompt(maintenance_request, lease_info, landlord_notes)
            
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
    
    def _build_vendor_prompt(self, maintenance_request: str, lease_info: LeaseInfo, landlord_notes: Optional[str] = None) -> str:
        """Build the vendor work order prompt"""
        
        prompt = f"""You are creating a professional work order for a vendor/contractor to fix a maintenance issue.

MAINTENANCE REQUEST FROM TENANT:
{maintenance_request}
"""
        
        # Add landlord notes if provided
        if landlord_notes:
            prompt += f"""
LANDLORD'S NOTES/CONTEXT:
{landlord_notes}
"""
        
        prompt += f"""
LEASE DOCUMENT (for property details):
{lease_info.full_text[:6000]}

YOUR TASK:
Create a professional, detailed work order that a vendor can use to fix the issue.

INSTRUCTIONS:
1. Determine urgency level:
   - "emergency": Safety issues, no heat/AC in extreme weather, major leaks, no water
   - "urgent": Significant issues needing quick attention (broken appliances, minor leaks)
   - "routine": Non-urgent maintenance

2. Write a COMPREHENSIVE description for the VENDOR with ONLY relevant information:
   ✓ INCLUDE:
   - The specific maintenance issue (detailed problem description)
   - Property address (street address, unit number if applicable)
   - Estimated scope of work (what needs to be assessed/repaired)
   - Access instructions (how/when vendor can access property, who to contact)
   - Tenant contact name (for coordination if needed)
   - Landlord's special notes/instructions if provided
   - Any safety concerns or urgent details
   
   ✗ DO NOT INCLUDE:
   - Rent amount or payment details
   - Lease duration or dates
   - Security deposit information
   - Lease term details (month-to-month, yearly, etc.)
   - Any financial information
   - Legal lease clauses unless directly about access/repair protocol

3. Keep it focused on what vendor needs to complete the job efficiently

IMPORTANT: Return ONLY valid JSON. Do not include any text before or after the JSON.

Return your work order in this exact JSON format:
{{
  "work_order_title": "Brief title (e.g., 'Heater Repair - Unit 123')",
  "comprehensive_description": "VENDOR-FOCUSED description (4-6 sentences): issue details, property address, scope of work, access instructions, tenant contact for coordination, special notes. NO lease terms, rent amounts, or financial details.",
  "urgency_level": "routine|urgent|emergency"
}}

Examples of comprehensive_description:
- "The tenant at 123 Main St, Apt 4B (John Smith) has reported a broken heating system not producing heat. This is an emergency repair as temperatures are below freezing. Vendor should assess the furnace, identify the issue, and complete repairs. Access is available Monday-Friday 9am-5pm via building superintendent. Tenant can be reached for access coordination. Unit was making unusual noises before it stopped working."

Rules:
- Be professional and clear
- Include EVERYTHING vendor needs in the comprehensive_description
- Extract actual property address and tenant info from lease
- Set urgency appropriately
- Return ONLY the JSON object, nothing else
"""
        
        return prompt
    
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
            prompt = self._build_workflow_prompt(maintenance_request, lease_info, landlord_notes)
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
    
    def _build_workflow_prompt(self, maintenance_request: str, lease_info: LeaseInfo, landlord_notes: Optional[str] = None) -> str:
        """Build the complete maintenance workflow prompt"""
        prompt = f"""You are a property management assistant handling a complete maintenance workflow. 

MAINTENANCE REQUEST FROM TENANT:
{maintenance_request}
"""
        if landlord_notes:
            prompt += f"""
LANDLORD'S NOTES/CONTEXT:
{landlord_notes}
"""
        
        prompt += f"""
LEASE DOCUMENT:
{lease_info.full_text[:6000]}

YOUR TASKS:
1. EVALUATE the maintenance request against the lease agreement
   - Determine if landlord or tenant is responsible
   - APPROVE if lease says landlord must handle OR if unclear (default to landlord)
   - REJECT if lease clearly states tenant is responsible
   - Cite exact lease clauses

2. GENERATE a professional message to send to the TENANT
   - If APPROVED: Acknowledge request, explain landlord will handle it, provide timeline
   - If REJECTED: Politely explain tenant's responsibility per lease, suggest next steps
   - Be professional, clear, and empathetic
   - Reference specific lease clauses

3. CREATE a vendor work order (ONLY if APPROVED)
   - If APPROVED: Generate complete work order with property address, issue details, urgency
   - If REJECTED: Set vendor_work_order to null

IMPORTANT RULES:
- Base DECISION only on the lease agreement
- If unclear, default to APPROVE (landlord's standard duty)
- Incorporate landlord notes naturally into messages
- Be fair and professional
- Return ONLY valid JSON, no extra text

RETURN FORMAT (JSON only):
{{
  "decision": "approved" or "rejected",
  "decision_reasons": ["Reason 1 based on lease", "Reason 2"],
  "lease_clauses_cited": ["Exact lease clause 1", "Exact lease clause 2"],
  "tenant_message": "Professional message to send to tenant (3-5 sentences explaining decision, timeline if approved, or next steps if rejected)",
  "tenant_message_tone": "approved|regretful|informative",
  "estimated_timeline": "Timeline for repair if approved (e.g., '24-48 hours'), or null if rejected",
  "alternative_action": "What tenant should do if rejected (e.g., 'Please hire a licensed contractor'), or null if approved",
  "vendor_work_order": {{
    "work_order_title": "Brief title (e.g., 'Emergency Heater Repair - Unit 4B')",
    "comprehensive_description": "Complete description for vendor: issue details, property address from lease, scope of work, access instructions, tenant contact, urgency details. NO financial info.",
    "urgency_level": "routine|urgent|emergency"
  }} OR null if rejected
}}

EXAMPLES:

Example 1 - APPROVED (Heater broken):
{{
  "decision": "approved",
  "decision_reasons": ["Lease Section 8.2 states landlord maintains heating systems", "Heating is essential habitability requirement"],
  "lease_clauses_cited": ["Section 8.2: Landlord shall maintain and repair all heating, plumbing, and electrical systems"],
  "tenant_message": "We have received your maintenance request regarding the heating system. Per Section 8.2 of the lease, we are responsible for maintaining heating systems. This is a high priority repair and we will dispatch a licensed HVAC technician immediately. Expected completion: 24-48 hours. We will keep you updated on progress.",
  "tenant_message_tone": "approved",
  "estimated_timeline": "24-48 hours",
  "alternative_action": null,
  "vendor_work_order": {{
    "work_order_title": "Emergency Heating System Repair - 123 Main St Unit 4B",
    "comprehensive_description": "Heating system failure reported by tenant at 123 Main St, Unit 4B. No heat for 2 days during freezing temperatures. Requires immediate HVAC inspection and repair. Property contact: John Smith, xxx-xxx-xxxx. Access available Mon-Fri 9am-5pm. Tenant can coordinate access.",
    "urgency_level": "emergency"
  }}
}}

Example 2 - REJECTED (Dishwasher):
{{
  "decision": "rejected",
  "decision_reasons": ["Lease Section 12.3 assigns appliance maintenance to tenant", "Dishwasher is not landlord's responsibility per lease"],
  "lease_clauses_cited": ["Section 12.3: Tenant is responsible for maintenance and repair of all appliances including dishwasher, microwave, and washer/dryer"],
  "tenant_message": "We have received your maintenance request regarding the dishwasher. After reviewing Section 12.3 of the lease agreement, appliance maintenance and repairs are the tenant's responsibility. You may hire a licensed appliance technician of your choice to diagnose and repair the issue. Please keep receipts for your records.",
  "tenant_message_tone": "regretful",
  "estimated_timeline": null,
  "alternative_action": "Please hire a licensed appliance technician to repair or replace the dishwasher at your expense",
  "vendor_work_order": null
}}

NOW PROCESS THE MAINTENANCE REQUEST ABOVE AND RETURN ONLY THE JSON:
"""
        return prompt
    
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
            prompt = self._build_tenant_rewrite_prompt(tenant_message)
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
    
    def _build_tenant_rewrite_prompt(self, tenant_message: str) -> str:
        """Build the tenant message rewrite prompt"""
        prompt = f"""You are helping a tenant communicate a maintenance issue to their landlord.

TENANT'S ORIGINAL MESSAGE:
{tenant_message}

YOUR TASK:
Rewrite this message to be professional, clear, and effective while maintaining the tenant's original intent.

INSTRUCTIONS:
1. Keep it polite and professional
2. Make the problem description clear and specific
3. Add relevant details if the original is vague (ask questions like: Where? When did it start? How severe?)
4. Structure it properly (greeting, issue description, impact/urgency, closing)
5. Determine urgency level:
   - "emergency": Safety issues, no heat/AC in extreme weather, major leaks, no water, broken locks
   - "urgent": Significant issues needing quick attention (broken appliances, minor leaks, no hot water)
   - "routine": Non-urgent maintenance (cosmetic issues, minor repairs)
6. Determine tone: professional, urgent, polite, concerned, etc.
7. List the specific improvements you made

IMPORTANT: Return ONLY valid JSON. Do not include any text before or after the JSON.

Return your rewrite in this exact JSON format:
{{
  "rewritten_message": "Professional rewritten message (3-6 sentences). Include: greeting, specific problem description with details, impact on tenant, polite closing.",
  "improvements_made": ["Added specific details", "Improved clarity", "Made tone more professional", etc.],
  "tone": "professional|urgent|polite|concerned",
  "estimated_urgency": "routine|urgent|emergency"
}}

Examples:
- Original: "heater broke"
  Rewritten: "Hello, I wanted to report that the heating system in my unit stopped working as of this morning. The unit is not producing any heat, and with temperatures dropping, this is becoming uncomfortable. I would appreciate it if you could arrange for a repair as soon as possible. Thank you for your attention to this matter."
  Improvements: ["Added greeting and closing", "Specified when issue started", "Explained impact", "Professional tone"]
  Urgency: "urgent"

- Original: "toilet is leaking a bit"
  Rewritten: "Hello, I noticed that the toilet in the main bathroom has developed a small leak at the base. It appears to be leaking slowly when flushed. I've placed towels around it to prevent water damage to the floor. Could you please send someone to take a look at this when you have a chance? Thank you."
  Improvements: ["Added specific location", "Described the problem clearly", "Mentioned preventive action taken", "Polite request"]
  Urgency: "urgent"

Rules:
- Be helpful and constructive
- Don't change the core issue being reported
- Make it sound professional but not overly formal
- Add structure if missing (greeting, issue, closing)
- Return ONLY the JSON object, nothing else
"""
        return prompt
    
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
            prompt = self._build_move_out_prompt(move_out_request, lease_info, owner_notes)
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
    
    def _build_move_out_prompt(self, move_out_request: str, lease_info: LeaseInfo, owner_notes: Optional[str] = None) -> str:
        """Build the move-out evaluation prompt"""
        
        # Get current date
        from datetime import datetime
        today = datetime.now().strftime("%B %d, %Y")  # e.g., "October 16, 2025"
        
        prompt = f"""You are a property owner evaluating a tenant's move-out request. Review the lease agreement and determine:
1. If the tenant provided proper notice according to the lease
2. What financial obligations remain (rent, fees, security deposit)
3. Clear next steps for the tenant

TODAY'S DATE: {today}
IMPORTANT: Use this date to calculate notice periods and determine if the tenant gave sufficient notice.

MOVE-OUT REQUEST FROM TENANT:
{move_out_request}
"""
        
        # Add owner notes if provided
        if owner_notes:
            prompt += f"""
PROPERTY OWNER'S NOTES:
{owner_notes}

NOTE: Consider the owner's notes when crafting the response, but the evaluation must be based on the lease agreement.
"""
        
        prompt += f"""
LEASE DOCUMENT:
{lease_info.full_text[:6000]}

INSTRUCTIONS:
1. Carefully review the lease to find:
   - Required notice period (e.g., "30 days", "60 days", "one month")
   - Notice requirements (written, email, certified mail, etc.)
   - Rent payment obligations during notice period
   - Security deposit return conditions
   - Any move-out fees or penalties
   - Early termination clauses if applicable

2. Determine from the move-out request:
   - When did tenant give notice (or is giving notice now)?
   - What is their intended move-out date?
   - Did they follow proper notice procedures?

3. CRITICAL - Calculate using TODAY'S DATE ({today}):
   IMPORTANT: When calculating dates, ALWAYS consider the FULL DATE including YEAR!
   
   Step-by-step calculation:
   a) If tenant says "I want to move out on [DATE]" → They are giving notice TODAY ({today})
   b) Parse the move-out date - if no year mentioned, assume current year (2025) OR next year if date already passed
   c) Count TOTAL CALENDAR DAYS from TODAY ({today}) to their requested move-out date
   d) Compare TOTAL DAYS to the required notice period from lease
   e) If TOTAL DAYS >= required notice period → notice_period_valid = TRUE ✓
   f) If TOTAL DAYS < required notice period → notice_period_valid = FALSE ✗
   
   DATE PARSING RULES:
   - "December 15" or "December 15th" = December 15, 2025 (current year)
   - "November 1" = November 1, 2025 (current year) 
   - If date is BEFORE today in current year, assume NEXT YEAR (e.g., "January 15" = January 15, 2026)
   - "December 15, 2025" or "12/15/2025" = Use exact year specified
   - Calculate days as: (Target Date - Today's Date) in calendar days
   
   Example: TODAY is {today}, tenant wants to move out December 15, lease requires 30 days
   - Parse: December 15 = December 15, 2025 (same year since December is after October)
   - Calculate: Days from October 16, 2025 to December 15, 2025 = 60 calendar days
   - Compare: 60 days >= 30 days required → VALID = TRUE ✓
   
   Calculate and provide:
   - Required notice period from lease
   - Actual notice period provided by tenant (TOTAL CALENDAR DAYS from today to move-out date)
   - Last allowed day tenant can stay (today + required notice period, OR their requested date if valid)
   - Any remaining rent owed (calculate prorated rent if needed)
   - Security deposit handling
   - Other applicable fees

4. Cite EXACT clauses from the lease that support your evaluation

5. Write a professional response message to the tenant

6. Provide clear next steps for the tenant

IMPORTANT: Return ONLY valid JSON. Do not include any text before or after the JSON.

Return your evaluation in this exact JSON format:
{{
  "notice_period_valid": true or false,
  "notice_period_required": "Required notice period from lease (e.g., '30 days', '60 days')",
  "notice_period_provided": "Actual notice period tenant provided (e.g., 'Giving notice today, {today}' or 'X days notice')",
  "last_day_allowed": "Last day tenant can occupy the property (calculate from today)",
  "rent_owed": "Description of any remaining rent owed (calculate prorated amounts)",
  "security_deposit_status": "What will happen with security deposit",
  "other_fees": "Any other fees or charges that apply",
  "lease_clauses_cited": ["Exact quote from lease clause 1", "Exact quote from lease clause 2"],
  "response_message": "Professional message to tenant (3-5 sentences explaining the evaluation)",
  "next_steps": ["Action item 1 for tenant", "Action item 2 for tenant", "Action item 3 for tenant"]
}}

CALCULATION EXAMPLES - DO MATH CAREFULLY (TODAY is {today}):

Example 1: SUFFICIENT NOTICE ✓
- Request: "I want to move out on December 15th" (said today, {today})
- Lease requires: 30 days notice
- Parse date: December 15th = December 15, 2025 (same year)
- Calculation: From October 16, 2025 to December 15, 2025 = 60 calendar days
- 60 days >= 30 days → notice_period_valid = TRUE ✓
- decision = "approved"
- Response: "Your 60-day notice is accepted. You may move out on December 15, 2025."

Example 2: INSUFFICIENT NOTICE ✗
- Request: "I want to move out on November 1st" (said today, {today})
- Lease requires: 30 days notice
- Parse date: November 1st = November 1, 2025 (same year)
- Calculation: From October 16, 2025 to November 1, 2025 = 16 calendar days
- 16 days < 30 days → notice_period_valid = FALSE ✗
- decision = "requires_attention"
- Response: "Insufficient notice. Lease requires 30 days. You may move out no earlier than November 15, 2025."

Example 3: NEXT YEAR DATE ✓
- Request: "I want to move out on January 31st" (said today, {today})
- Lease requires: 60 days notice
- Parse date: January 31st = January 31, 2026 (next year, since January already passed in 2025)
- Calculation: From October 16, 2025 to January 31, 2026 = 107 calendar days
- 107 days >= 60 days → notice_period_valid = TRUE ✓
- decision = "approved"
- Response: "Your 107-day notice is accepted. You may move out on January 31, 2026."

Example 4: EXPLICIT YEAR SPECIFIED ✗
- Request: "I want to move out on October 25, 2025" (said today, {today})
- Lease requires: 30 days notice
- Parse date: October 25, 2025 (year specified)
- Calculation: From October 16, 2025 to October 25, 2025 = 9 calendar days
- 9 days < 30 days → notice_period_valid = FALSE ✗
- decision = "requires_attention"
- Response: "Insufficient notice. Lease requires 30 days. You may move out no earlier than November 15, 2025."

Example 5: PAST NOTICE GIVEN ✓
- Request: "I gave notice on September 1st, moving out October 15th"
- Lease requires: 30 days notice
- Parse dates: September 1, 2025 to October 15, 2025
- Calculation: September 1 to October 15 = 44 calendar days
- 44 days >= 30 days → notice_period_valid = TRUE ✓
- decision = "approved"

CRITICAL REMINDERS:
- COUNT CALENDAR DAYS including the full year (not just month/day)
- If no year specified, assume current year UNLESS date already passed this year, then use next year
- Calculate exact days between two full dates (Month Day, Year format)
- If days >= required days → notice_period_valid = TRUE, decision = "approved"
- If days < required days → notice_period_valid = FALSE, decision = "requires_attention"
- Write response_message as if you ARE the property owner speaking to tenant
- Be professional, clear, and ACCURATE with date calculations
- If owner notes mention issues (damages, unpaid rent, etc.), incorporate into response
- Return ONLY the JSON object, nothing else
"""
        
        return prompt
    
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
            
            system_prompt = """# Role & Purpose
You are the Maintenance Assistant inside the MELK property management application.
Your job is to:
- Help residents describe their maintenance issue clearly.
- Offer only simple, low-risk tips they can safely try.
- Decide when to stop giving tips and instead escalate to maintenance or emergency services.

# Absolute Safety Rules (Non-Negotiable)
Your highest priority is safety. You must:

**NEVER provide advice that involves:**
- Working with gas, wiring, electrical panels, outlets, or circuit breakers
- Opening or disassembling appliances, heaters/furnaces, water heaters, plumbing, walls, ceilings, or floors
- Using tools (screwdrivers, wrenches, drills, etc.) or ladders/step stools
- Using strong chemical drain cleaners or other hazardous chemicals
- Bypassing, disabling, or ignoring smoke/CO detectors or other safety devices
- Forcing doors or windows, tampering with locks, or bypassing building security

**Never give medical, legal, or insurance advice.** Do not tell people whether they should or should not call police, doctors, or insurers.

**When in doubt about safety, do not suggest any fix.** Instead, recommend contacting maintenance or emergency services.

# Emergencies & Urgent Hazards
If the user describes anything that sounds like:
- Smelling gas or a "rotten egg" smell
- Smelling smoke, seeing smoke, sparks, or burning smells
- Flooding, water pouring from ceilings/walls, or a bulging/sagging ceiling
- Exposed wires, outlets that are hot, burning, or buzzing
- Fire alarms or CO detectors going off (or clearly malfunctioning)
- No heat in very cold weather or no AC in extreme heat (risk to health)
- Being locked out or unable to secure an exterior door or window
- Any situation where someone might be in immediate danger

**Then you must:**
1. Stop giving troubleshooting tips.
2. Respond with clear emergency guidance:
   "This could be an emergency. If you smell gas, see or smell smoke, see sparks, or feel unsafe, please call 911 or your local emergency number immediately. After that, please contact your property's emergency maintenance line. I can also help you mark this as urgent in a maintenance request."
3. Set suggestTicket to true.

# Allowed Types of Suggestions (Low-Risk Only)
You may suggest only simple, user-level actions like:

**Check basic settings:**
- Thermostat mode (Heat/Cool/Off) and temperature
- That an appliance is plugged in and the door is fully closed
- That vents or radiators are not blocked by furniture

**Clean or remove obvious debris from safe, exposed areas:**
- Wiping visible dust from vents or thermostat covers
- Removing hair or soap scum from the top of a drain cover or stopper (no tools, no chemicals)
- Gently wiping scuffs on walls with a damp soft cloth

**Confirm simple substitutions:**
- Try a light bulb that they already know works in that fixture
- Try a different small device in an outlet to check if the outlet might not be working

**Contain a minor issue:**
- Place a towel or bucket under a slow drip and report it

**Document & report:**
- For noise/neighbors or recurring issues, suggest noting times/dates and contacting management through the portal

You must keep suggestions short, simple, and optional. Never pressure the user to attempt anything that feels unsafe or uncomfortable.

# Escalation to Maintenance (Non-Emergency)
For anything beyond basic checks and cleaning, your job is to:
- Help them describe the problem clearly (what, where, how long, any photos).
- Suggest an appropriate priority (routine vs. urgent, not emergency) based on their description.
- Tell them: "This is better handled by our maintenance team. I'll help you submit a request."
- Set suggestTicket to true.

# Tone & Boundaries
- Be calm, polite, and reassuring.
- Keep responses to 2-4 sentences maximum.
- Do not guess about building policies; if unknown, say that management will review it.
- Do not promise specific repair times or outcomes. Say "maintenance team" or "property management will review your request."
- If you are unsure whether a suggestion is safe: Do not provide the suggestion. Instead, recommend contacting maintenance and/or emergency services.

# Response Format
Respond in JSON format:
{
  "response": "your helpful response here",
  "suggestTicket": false
}

Set suggestTicket to true when:
- Any emergency or hazardous situation is detected
- Professional help is clearly needed
- After 3-4 exchanges without resolution
- User has tried simple suggestions but issue persists"""
            
            messages = [{"role": msg.role, "content": msg.content} for msg in conversation_history]
            
            # Format for Bedrock - Use Haiku for fast responses
            user_prompt = "\n\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in messages])
            
            # Use Haiku (fastest model)
            haiku_model = "us.anthropic.claude-3-haiku-20240307-v1:0"
            
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 400,  # Keep responses brief
                "temperature": 0.3,  # Slightly deterministic
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}]
            }
            
            response_text, _ = self._call_bedrock_with_retry(haiku_model, body)
            elapsed_time = time.time() - start_time
            
            logger.info(f"Maintenance chat response received in {elapsed_time:.2f}s")
            
            try:
                json_str = self._extract_json_from_markdown(response_text)
                if not json_str:
                    json_str = response_text
                
                json_str = self._sanitize_json_string(json_str)
                parsed = json.loads(json_str)
                
                return MaintenanceChatResponse(
                    response=parsed.get("response", response_text),
                    suggestTicket=parsed.get("suggestTicket", False)
                )
                
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse failed, using raw response: {e}")
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
        conversation_history: List['ChatMessage']
    ) -> 'MaintenanceRequestExtraction':
        """
        Extract title and description from tenant chat for maintenance request.
        Uses Haiku for fast, cost-effective extraction.
        
        Args:
            conversation_history: Complete chat conversation
            
        Returns:
            MaintenanceRequestExtraction with title and description
        """
        from app.models import MaintenanceRequestExtraction
        
        try:
            start_time = time.time()
            logger.info("Extracting maintenance request from chat conversation")
            
            # Use Haiku (fast and cheap)
            model = "us.anthropic.claude-3-haiku-20240307-v1:0"
            
            # Build conversation context
            messages = [{"role": msg.role, "content": msg.content} for msg in conversation_history]
            conversation_text = "\n\n".join([f"{msg['role'].upper()}: {msg['content']}" for msg in messages])
            
            system_prompt = """Extract a maintenance request from the tenant's conversation.

OUTPUT REQUIREMENTS:
1. Title: Brief summary from tenant's perspective (max 80 characters)
2. Description: Detailed description including all relevant details from conversation

RESPONSE FORMAT (JSON only):
{
  "title": "brief issue summary",
  "description": "complete description with all details"
}

Be concise but include all important details."""

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
