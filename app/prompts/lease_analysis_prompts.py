"""Prompt templates for lease analysis operations"""

from typing import Optional, List, Dict
from app.models import LeaseInfo


def build_lease_analysis_prompt(
    lease_info: LeaseInfo,
    search_results: Optional[List[Dict[str, str]]],
    use_native_search: bool
) -> str:
    """
    Build prompt for analyzing lease violations.
    
    Args:
        lease_info: Lease document information
        search_results: Optional search results from DuckDuckGo
        use_native_search: Whether model should search web itself
        
    Returns:
        Formatted prompt string
    """
    prompt = f"""Analyze the following lease agreement for potential violations of landlord-tenant laws.

FULL LEASE TEXT:
{lease_info.full_text[:25000]}

"""
    
    if use_native_search:
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


def build_categorized_analysis_prompt(lease_info: LeaseInfo) -> str:
    """
    Build prompt for categorized lease violation analysis.
    
    Args:
        lease_info: Lease document information
        
    Returns:
        Formatted prompt string
    """
    return f"""Analyze this lease for landlord-tenant law violations.

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


# System prompt for categorized analysis
CATEGORIZED_ANALYSIS_SYSTEM_PROMPT = """You are a legal AI that analyzes lease agreements. 

CRITICAL RULES:
1. Return ONLY valid JSON - no markdown, no code blocks, no explanations
2. Your response MUST start with { and end with }
3. Never wrap JSON in ```json``` or ``` markers
4. All string values must be properly escaped
5. Confidence scores must be consistent and based on citation quality
6. Extract exact lease clause text - never leave lease_clause empty

Focus on accuracy, consistency, and completeness."""
