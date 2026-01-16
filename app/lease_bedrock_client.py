"""
AWS Bedrock async client for lease extraction with retry logic and rate limiting
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockThrottlingError(Exception):
    """Custom exception for Bedrock throttling"""
    pass


class LeaseBedrockClient:
    """Async AWS Bedrock client for lease extraction with rate limiting and retry logic"""
    
    def __init__(self, region: str, max_concurrent: int, 
                 access_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.region = region
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        
        session_kwargs = {'region_name': self.region}
        if access_key and secret_key:
            session_kwargs.update({'aws_access_key_id': access_key, 'aws_secret_access_key': secret_key})
        
        self.session = boto3.Session(**session_kwargs)
        
        # Configure boto3 connection pool to match concurrency
        from botocore.config import Config
        boto_config = Config(
            max_pool_connections=max_concurrent,
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        
        self.client = self.session.client('bedrock-runtime', config=boto_config)
        logger.info(f"Lease Bedrock client initialized (region={self.region}, max_concurrent={self.max_concurrent})")
    
    def _invoke_bedrock_sync(self, model_id: str, prompt: str, temperature: float, max_tokens: int) -> Dict[str, Any]:
        """Synchronous Bedrock invocation (wrapped for async)"""
        try:
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            
            response = self.client.invoke_model(
                modelId=model_id, body=json.dumps(request_body),
                contentType="application/json", accept="application/json"
            )
            
            response_body = json.loads(response['body'].read())
            return {
                'content': response_body['content'][0]['text'],
                'stop_reason': response_body.get('stop_reason'),
                'usage': {
                    'input_tokens': response_body.get('usage', {}).get('input_tokens', 0),
                    'output_tokens': response_body.get('usage', {}).get('output_tokens', 0)
                }
            }
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['ThrottlingException', 'TooManyRequestsException']:
                logger.warning(f"Bedrock throttling detected: {error_code}")
                raise BedrockThrottlingError(f"Throttled: {error_code}")
            logger.error(f"Bedrock ClientError: {error_code} - {e}")
            raise
        except Exception as e:
            logger.error(f"Bedrock invocation error: {e}")
            raise
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
           retry=retry_if_exception_type(BedrockThrottlingError), reraise=True)
    async def invoke_model_async(self, prompt: str, model_id: str,
                                temperature: float, max_tokens: int,
                                timeout: int) -> Dict[str, Any]:
        """Async model invocation with retry logic and rate limiting"""
        async with self.semaphore:
            try:
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, self._invoke_bedrock_sync, model_id, prompt, temperature, max_tokens),
                    timeout=timeout
                )
                logger.debug(f"Bedrock invocation successful (tokens: {response['usage']['input_tokens']}+{response['usage']['output_tokens']})")
                return response
            except asyncio.TimeoutError:
                logger.error(f"Bedrock request timeout after {timeout}s")
                raise
            except BedrockThrottlingError:
                logger.warning("Bedrock throttling - will retry")
                raise
            except Exception as e:
                logger.error(f"Bedrock invocation failed: {e}")
                raise
    
    async def extract_json_from_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and parse JSON from model response
        
        Args:
            response: Bedrock response dictionary
            
        Returns:
            Parsed JSON data
        """
        content = response.get('content', '')
        
        # Log first 200 chars of response for debugging
        logger.info(f"Model response preview: {content[:200]}...")
        
        # Try to extract JSON from markdown code blocks
        if '```json' in content:
            start = content.find('```json') + 7
            end = content.find('```', start)
            if end > start:
                content = content[start:end].strip()
        elif '```' in content:
            start = content.find('```') + 3
            end = content.find('```', start)
            if end > start:
                content = content[start:end].strip()
        
        # Try to extract just the JSON object if there's extra text
        # Find the first { and try to parse from there
        if not content.strip().startswith('{'):
            start_idx = content.find('{')
            if start_idx >= 0:
                content = content[start_idx:]
                logger.debug("Stripped leading text before JSON")
        
        try:
            # Use json.JSONDecoder to get only the first valid JSON object
            # This handles cases where there's text after the JSON
            decoder = json.JSONDecoder()
            parsed_json, idx = decoder.raw_decode(content)
            
            # Check if there's significant text after the JSON
            remaining = content[idx:].strip()
            if remaining and len(remaining) > 10:
                logger.warning(f"Extra text found after JSON ({len(remaining)} chars): {remaining[:100]}...")
            
            # Log key counts for debugging
            logger.info(f"Parsed JSON keys: {list(parsed_json.keys())}")
            return parsed_json
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            logger.debug(f"Raw content: {content[:500]}...")
            raise ValueError(f"Invalid JSON in model response: {e}")
    
    async def close(self):
        """Cleanup resources"""
        # Close boto3 client if needed
        if hasattr(self.client, 'close'):
            self.client.close()
        logger.info("Lease Bedrock client closed")
