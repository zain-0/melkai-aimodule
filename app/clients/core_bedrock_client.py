"""Core AWS Bedrock client with shared functionality for all specialized clients"""

import json
import time
import re
from typing import Dict, Optional
import logging
import boto3
from botocore.exceptions import ClientError, ReadTimeoutError, ConnectTimeoutError

from app.config import settings
from app.exceptions import AITimeoutError, AIModelError

logger = logging.getLogger(__name__)


class CoreBedrockClient:
    """
    Base client for AWS Bedrock API interactions.
    Provides common functionality used by all specialized clients.
    """
    
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
    
    def __init__(self):
        """
        Initialize Bedrock client with AWS credentials.
        
        Uses IAM role if running on EC2 with attached role (recommended).
        Uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from settings for local testing.
        
        Raises:
            AIModelError: If client initialization fails
        """
        try:
            # Configure boto3 client
            session_kwargs = {'region_name': settings.AWS_REGION}
            
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
        Sanitize JSON string by removing/escaping invalid control characters.
        
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
            elif code in [9, 10, 13]:  # Tab, newline, carriage return
                sanitized += char
        
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', sanitized)
        return sanitized
    
    def _extract_json_from_markdown(self, text: str) -> Optional[str]:
        """
        Extract JSON from markdown code blocks or plain text.
        
        Args:
            text: Response text that may contain markdown
            
        Returns:
            Extracted JSON string or None if not found
        """
        # Try to find JSON in markdown code blocks
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
        
        # Try incomplete markdown blocks
        incomplete_pattern = r'```(?:json)?\s*(\{.*)'
        match = re.search(incomplete_pattern, text, re.DOTALL)
        if match:
            logger.warning("Found incomplete markdown block")
            json_str = match.group(1).strip()
            json_str = re.sub(r'```\s*$', '', json_str)
            return self._fix_truncated_json(json_str)
        
        # Extract JSON without markdown
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
        Attempt to fix truncated/incomplete JSON by closing open brackets.
        
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
        
        # Remove incomplete strings at the end
        json_str = re.sub(r',?\s*"[^"]*$', '', json_str)
        
        # Close open brackets
        while open_brackets > close_brackets:
            json_str += ']'
            close_brackets += 1
        
        # Close open braces
        while open_braces > close_braces:
            json_str += '}'
            close_braces += 1
        
        return json_str
    
    def _format_messages_for_bedrock(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str
    ) -> Dict:
        """
        Format messages according to model-specific requirements.
        
        Args:
            model_id: Bedrock model identifier or inference profile ID
            system_prompt: System prompt text
            user_prompt: User prompt text
            
        Returns:
            Formatted request body for the specific model
            
        Raises:
            AIModelError: If model format is not supported
        """
        # Handle inference profile IDs (us.provider.model) by extracting provider
        if model_id.startswith("us."):
            provider = model_id.split(".")[1]
        elif "." in model_id:
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
                "messages": [{"role": "user", "content": user_prompt}]
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
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            return {
                "prompt": combined_prompt,
                "max_tokens": 8192,
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
        Extract text from model-specific response format.
        
        Args:
            model_id: Bedrock model identifier or inference profile ID
            response_body: Parsed JSON response from Bedrock
            
        Returns:
            Generated text content
            
        Raises:
            AIModelError: If response format is not supported or parsing fails
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
                return response_body['content'][0]['text']
            elif provider == "meta":
                return response_body['generation']
            elif provider == "mistral":
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
        Extract token usage from model response.
        
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
    
    def _call_bedrock_with_retry(
        self,
        model_id: str,
        body: Dict
    ) -> tuple[str, Dict[str, int]]:
        """
        Call Bedrock API with automatic retry logic.
        
        Args:
            model_id: Bedrock model identifier
            body: Request body formatted for the specific model
            
        Returns:
            Tuple of (response_text, token_usage)
            
        Raises:
            AITimeoutError: If request times out after retries
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
                    logger.error(f"Bedrock error details: {error_message}")
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
    
    def calculate_cost(self, model_name: str, tokens_used: Dict[str, int]) -> float:
        """
        Calculate the cost of API usage based on token usage.
        
        Args:
            model_name: Name of the model used
            tokens_used: Dictionary with 'prompt' and 'completion' token counts
            
        Returns:
            Cost in USD
        """
        pricing = self.MODEL_PRICING.get(model_name, {"input": 0, "output": 0})
        
        prompt_cost = (tokens_used.get("prompt", 0) / 1_000_000) * pricing["input"]
        completion_cost = (tokens_used.get("completion", 0) / 1_000_000) * pricing["output"]
        
        return prompt_cost + completion_cost
