import json
import time
import re
from typing import List, Dict, Optional
from openai import OpenAI
import logging
import httpx
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
    TenantMessageRewrite
)
from app.exceptions import AITimeoutError, AIModelError

logger = logging.getLogger(__name__)


# Retry decorator for transient API failures
def retry_on_api_error(func):
    """Decorator to retry on transient API errors"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True
    )(func)


class OpenRouterClient:
    """Client for interacting with OpenRouter API with timeout and retry support"""
    
    def __init__(self):
        # Configure httpx client with timeout
        http_client = httpx.Client(
            timeout=httpx.Timeout(
                timeout=60.0,  # 60 second timeout for AI calls
                connect=10.0,  # 10 seconds to establish connection
                read=60.0,     # 60 seconds to read response
                write=10.0     # 10 seconds to send request
            )
        )
        
        self.client = OpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            http_client=http_client
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
        # Method 1: Remove all control characters except newline, tab, carriage return
        # This is more aggressive but safer for JSON parsing
        sanitized = ""
        for char in json_str:
            code = ord(char)
            
            # Allow:
            # - All printable ASCII (32-126)
            # - Tab (9), Newline (10), Carriage Return (13)
            # - Extended ASCII/Unicode (>127)
            if code >= 32:  # Printable and extended characters
                sanitized += char
            elif code in [9, 10, 13]:  # Tab, LF, CR
                sanitized += char
            # Skip all other control characters (0-8, 11-12, 14-31)
            # Don't replace with space, just skip them entirely
        
        # Method 2: Use regex to escape any remaining problematic characters
        # Escape any literal control characters that might have slipped through
        sanitized = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]', '', sanitized)
        
        return sanitized
    
    def _call_ai_with_retry(self, **kwargs):
        """
        Call OpenAI API with retry logic and error handling
        
        Args:
            **kwargs: Arguments to pass to chat.completions.create()
            
        Returns:
            API response
            
        Raises:
            AITimeoutError: If request times out
            AIModelError: If AI model returns an error
        """
        try:
            # Make the API call with retry decorator logic
            max_retries = 3
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    return response
                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.warning(f"API timeout on attempt {attempt + 1}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise AITimeoutError(timeout_seconds=60)
                except (httpx.ConnectError, httpx.NetworkError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"Network error on attempt {attempt + 1}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        raise AIModelError(
                            message="Failed to connect to AI service",
                            details=str(e)
                        )
                except Exception as e:
                    # Other errors (API errors, rate limits, etc.)
                    error_msg = str(e).lower()
                    if "timeout" in error_msg:
                        raise AITimeoutError(timeout_seconds=60)
                    elif "rate limit" in error_msg:
                        raise AIModelError(
                            message="AI service rate limit exceeded",
                            details="Too many requests. Please try again later."
                        )
                    else:
                        raise AIModelError(
                            message="AI service error",
                            details=str(e)
                        )
            
            # Should never reach here, but just in case
            if last_error:
                raise AIModelError(
                    message="AI service failed after retries",
                    details=str(last_error)
                )
                
        except (AITimeoutError, AIModelError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"Unexpected error calling AI: {str(e)}")
            raise AIModelError(
                message="Unexpected error calling AI service",
                details=str(e)
            )
    
    # Pricing per 1M tokens (approximations based on OpenRouter pricing as of 2025)
    MODEL_PRICING = {
        # Perplexity - with online search (2025 models)
        "perplexity/sonar-pro": {"input": 3.0, "output": 15.0},
        "perplexity/sonar": {"input": 1.0, "output": 1.0},
        "perplexity/sonar-reasoning": {"input": 1.0, "output": 5.0},
        
        # Anthropic Claude (2025 models)
        "anthropic/claude-sonnet-4.5": {"input": 3.0, "output": 15.0},
        "anthropic/claude-3.7-sonnet": {"input": 3.0, "output": 15.0},
        "anthropic/claude-opus-4": {"input": 15.0, "output": 75.0},
        
        # OpenAI (GPT-5 series)
        "openai/gpt-5": {"input": 5.0, "output": 15.0},
        "openai/gpt-5-mini": {"input": 0.15, "output": 0.6},
        "openai/gpt-4o": {"input": 2.5, "output": 10.0},
        
        # Google Gemini (2.5 series)
        "google/gemini-2.5-flash-preview-09-2025": {"input": 0.075, "output": 0.3},
        "google/gemini-2.5-flash-lite": {"input": 0.04, "output": 0.15},
        
        # Meta Llama (Latest)
        "meta-llama/llama-4-scout": {"input": 0.2, "output": 0.2},
        "meta-llama/llama-3.3-8b-instruct:free": {"input": 0.0, "output": 0.0},
        
        # Mistral
        "mistralai/mistral-medium-3.1": {"input": 0.7, "output": 2.1},
        "mistralai/devstral-medium": {"input": 0.5, "output": 1.5},
        
        # DeepSeek
        "deepseek/deepseek-v3.2-exp": {"input": 0.14, "output": 0.28},
        "deepseek/deepseek-chat-v3.1:free": {"input": 0.0, "output": 0.0},
        
        # Qwen
        "qwen/qwen3-max": {"input": 0.8, "output": 0.8},
        "qwen/qwen3-coder-plus": {"input": 0.3, "output": 0.3},
    }
    
    def analyze_lease_with_search(
        self,
        model_name: str,
        lease_info: LeaseInfo,
        search_results: Optional[List[Dict[str, str]]] = None,
        use_native_search: bool = False
    ) -> tuple[List[Violation], AnalysisMetrics, Optional[Dict[str, str]]]:
        """
        Analyze lease for violations using specified model
        
        Args:
            model_name: OpenRouter model identifier
            lease_info: Extracted lease information
            search_results: Search results from DuckDuckGo (if not using native search)
            use_native_search: Whether model has native web search capability
            
        Returns:
            Tuple of (violations list, metrics, location dict extracted by model)
        """
        start_time = time.time()
        
        try:
            # Build prompt
            prompt = self._build_analysis_prompt(lease_info, search_results, use_native_search)
            
            # Make API call
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a legal expert specializing in landlord-tenant law. Analyze lease agreements for potential violations of local, county, and state laws. Always cite specific laws and provide .gov sources when possible."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=4000,
            )
            
            # Parse response - now returns violations AND lease_info data
            violations, extracted_lease_info = self._parse_violations_from_response(
                response.choices[0].message.content
            )
            
            # Update lease_info with all extracted fields if available
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
            
            tokens_used = {
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens
            }
            
            cost = self._calculate_cost(model_name, tokens_used)
            
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.NATIVE_SEARCH if use_native_search else SearchStrategy.DUCKDUCKGO,
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
            
            # Return empty result with error metrics
            elapsed_time = time.time() - start_time
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.NATIVE_SEARCH if use_native_search else SearchStrategy.DUCKDUCKGO,
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
    
    def _build_analysis_prompt(
        self,
        lease_info: LeaseInfo,
        search_results: Optional[List[Dict[str, str]]],
        use_native_search: bool
    ) -> str:
        """Build the analysis prompt"""
        
        prompt = f"""Analyze the following lease agreement for potential violations of landlord-tenant laws.

FULL LEASE TEXT:
{lease_info.full_text[:8000]}  # Truncate to avoid token limits

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
    
    def _calculate_cost(self, model_name: str, tokens_used: Dict[str, int]) -> float:
        """Calculate cost in USD for API call"""
        if model_name not in self.MODEL_PRICING:
            logger.warning(f"No pricing info for {model_name}, using default")
            pricing = {"input": 1.0, "output": 1.0}
        else:
            pricing = self.MODEL_PRICING[model_name]
        
        input_cost = (tokens_used["prompt"] / 1_000_000) * pricing["input"]
        output_cost = (tokens_used["completion"] / 1_000_000) * pricing["output"]
        
        return input_cost + output_cost
    
    @staticmethod
    def get_available_models() -> List[Dict[str, any]]:
        """Get list of available models with metadata"""
        models = []
        
        for model_id in settings.MODELS_WITH_SEARCH + settings.MODELS_WITHOUT_SEARCH:
            pricing = OpenRouterClient.MODEL_PRICING.get(
                model_id,
                {"input": 0, "output": 0}
            )
            
            models.append({
                "model_id": model_id,
                "name": model_id.split("/")[-1],
                "provider": model_id.split("/")[0],
                "has_native_search": model_id in settings.MODELS_WITH_SEARCH,
                "estimated_cost_per_1k_tokens": pricing,
                "context_length": 128000 if "128k" in model_id else 32000
            })
        
        return models

    def analyze_lease_categorized(
        self,
        lease_info: LeaseInfo
    ) -> tuple[Dict[str, List[CategorizedViolation]], AnalysisMetrics, Optional[Dict[str, str]]]:
        """
        Analyze lease for violations using Mistral Medium 3.1 and categorize them.
        
        Args:
            lease_info: Extracted lease information
            
        Returns:
            Tuple of (violations by category dict, metrics, location dict extracted by model)
        """
        model_name = "mistralai/mistral-medium-3.1"
        start_time = time.time()
        
        try:
            # Build categorized analysis prompt
            prompt = self._build_categorized_prompt(lease_info)
            
            # Make API call with retry
            response = self._call_ai_with_retry(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a legal expert specializing in landlord-tenant law. Analyze lease agreements for potential violations and categorize them into: rent_increase, tenant_owner_rights, fair_housing_laws, licensing, or others."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=4000
            )
            
            # Extract response
            response_text = response.choices[0].message.content
            
            # Parse violations and lease info
            categorized_violations, lease_info_data = self._parse_categorized_violations(response_text)
            
            # Calculate metrics
            elapsed_time = time.time() - start_time
            tokens_used = {
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens
            }
            
            # Count total violations
            all_violations = []
            for violations_list in categorized_violations.values():
                all_violations.extend(violations_list)
            
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.NATIVE_SEARCH,
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
            
            return categorized_violations, metrics, lease_info_data
            
        except Exception as e:
            logger.error(f"Error in categorized analysis: {str(e)}")
            
            # Return empty result with error metrics
            elapsed_time = time.time() - start_time
            metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=SearchStrategy.NATIVE_SEARCH,
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
    
    def _build_categorized_prompt(self, lease_info: LeaseInfo) -> str:
        """Build the categorized analysis prompt"""
        
        prompt = f"""Analyze the following lease agreement for potential violations of landlord-tenant laws.

FULL LEASE TEXT:
{lease_info.full_text[:8000]}  # Truncate to avoid token limits

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

4. Identify any violations or potential issues in the lease

5. CATEGORIZE each violation into ONE of these categories:
   - "rent_increase": Violations related to rent increases, caps, notice requirements
   - "tenant_owner_rights": Violations of tenant rights or landlord obligations (repairs, entry, privacy, etc.)
   - "fair_housing_laws": Discrimination, accessibility, protected classes violations
   - "licensing": Property licensing, registration, permit violations
   - "others": Any violation that doesn't fit the above categories

6. For each violation, provide:
   - Category (must be one of the 5 above)
   - Violation type and description
   - Severity (low, medium, high, critical)
   - Confidence score (0.0 to 1.0)
   - Specific lease clause that violates the law
   - Citations with .gov source URLs and specific law references

Return your analysis in the following JSON format:
```json
{{
  "lease_info": {{
    "address": "full property address or null",
    "city": "city name or null",
    "state": "2-letter state code or null",
    "county": "county name or null",
    "landlord": "landlord name or null",
    "tenant": "tenant name or null",
    "rent_amount": "monthly rent (e.g., '$1,500') or null",
    "security_deposit": "security deposit amount or null",
    "lease_duration": "lease term (e.g., '12 months') or null"
  }},
  "violations": [
    {{
      "category": "rent_increase|tenant_owner_rights|fair_housing_laws|licensing|others",
      "violation_type": "string",
      "description": "string",
      "severity": "low|medium|high|critical",
      "confidence_score": 0.0-1.0,
      "lease_clause": "exact text from lease",
      "citations": [
        {{
          "source_url": ".gov URL",
          "title": "page title",
          "relevant_text": "specific text from source",
          "law_reference": "e.g., State Code § 123.45",
          "is_gov_site": true|false
        }}
      ]
    }}
  ]
}}
```

Be thorough in your analysis. Search for all relevant laws and regulations. Provide specific citations and law references.
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
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            
            if json_start == -1 or json_end == 0:
                logger.error("No JSON found in response")
                return violations_by_category, lease_info_data
            
            json_str = response_text[json_start:json_end]
            
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
                    
                    # Create categorized violation
                    violation = CategorizedViolation(
                        violation_type=v_data.get("violation_type", "Unknown"),
                        category=category,
                        description=v_data.get("description", ""),
                        severity=v_data.get("severity", "medium"),
                        confidence_score=v_data.get("confidence_score", 0.5),
                        lease_clause=v_data.get("lease_clause", ""),
                        citations=citations
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
        model_name = "meta-llama/llama-3.3-8b-instruct:free"
        
        try:
            # Build maintenance evaluation prompt
            prompt = self._build_maintenance_prompt(maintenance_request, lease_info, landlord_notes)
            
            # Make API call with retry
            response = self._call_ai_with_retry(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a landlord reviewing a maintenance request. Evaluate it against the lease agreement and decide whether to approve or reject it based ONLY on what the lease says. Be fair and follow the lease terms exactly."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=800  # Limit response size
            )
            
            # Extract response
            response_text = response.choices[0].message.content
            
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
        model_name = "meta-llama/llama-3.3-8b-instruct:free"
        
        try:
            # Build vendor work order prompt
            prompt = self._build_vendor_prompt(maintenance_request, lease_info, landlord_notes)
            
            # Make API call with retry
            response = self._call_ai_with_retry(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a property management assistant creating professional work orders for vendors. Generate clear, detailed work orders that help vendors understand exactly what needs to be fixed."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=800  # Limit response size
            )
            
            # Extract response
            response_text = response.choices[0].message.content
            
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

    def rewrite_tenant_message(
        self,
        tenant_message: str
    ) -> 'TenantMessageRewrite':
        """
        Rewrite tenant's maintenance message to be more professional and clear
        
        Args:
            tenant_message: The original message from tenant describing the issue
            
        Returns:
            TenantMessageRewrite with improved message and metadata
        """
        from app.models import TenantMessageRewrite
        
        model_name = "meta-llama/llama-3.3-8b-instruct:free"
        
        try:
            # Build tenant message rewrite prompt
            prompt = self._build_tenant_rewrite_prompt(tenant_message)
            
            # Make API call with retry
            response = self._call_ai_with_retry(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that helps tenants communicate maintenance issues clearly and professionally to their landlords. Rewrite messages to be polite, detailed, and effective."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.4,
                max_tokens=600  # Shorter for tenant messages
            )
            
            # Extract response
            response_text = response.choices[0].message.content
            
            # LOG THE FULL RESPONSE
            logger.info("="*80)
            logger.info("FULL AI RESPONSE FOR TENANT MESSAGE REWRITE:")
            logger.info(response_text)
            logger.info("="*80)
            
            # Parse rewrite response
            rewrite_data = self._parse_tenant_rewrite_response(response_text, tenant_message)
            
            return rewrite_data
            
        except Exception as e:
            logger.error(f"Error rewriting tenant message: {str(e)}")
            
            # Return original message on error
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
    
    def _parse_tenant_rewrite_response(
        self,
        response_text: str,
        original_message: str
    ) -> 'TenantMessageRewrite':
        """Parse tenant message rewrite response from model"""
        from app.models import TenantMessageRewrite
        
        try:
            logger.info("="*80)
            logger.info("PARSING TENANT MESSAGE REWRITE RESPONSE")
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
                    return TenantMessageRewrite(
                        original_message=original_message,
                        rewritten_message=original_message,
                        improvements_made=["Unable to parse AI response"],
                        tone="original",
                        estimated_urgency="routine"
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
            
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=data.get("rewritten_message", original_message),
                improvements_made=data.get("improvements_made", []),
                tone=data.get("tone", "professional"),
                estimated_urgency=data.get("estimated_urgency", "routine")
            )
        
        except json.JSONDecodeError as e:
            logger.error("="*80)
            logger.error(f"JSON DECODE ERROR: {str(e)}")
            logger.error(f"Error at position: {e.pos if hasattr(e, 'pos') else 'unknown'}")
            logger.error(f"JSON string that failed:")
            logger.error(json_str if json_str else "N/A")
            logger.error("="*80)
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=original_message,
                improvements_made=["JSON parsing error - using original"],
                tone="original",
                estimated_urgency="routine"
            )
        except Exception as e:
            logger.error("="*80)
            logger.error(f"UNEXPECTED ERROR: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Response text (first 500 chars): {response_text[:500]}")
            logger.error("="*80)
            return TenantMessageRewrite(
                original_message=original_message,
                rewritten_message=original_message,
                improvements_made=[f"Error: {type(e).__name__}"],
                tone="original",
                estimated_urgency="routine"
            )





