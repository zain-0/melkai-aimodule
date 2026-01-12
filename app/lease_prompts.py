"""
LLM prompt templates for lease extraction
"""

SCHEMA_DEFINITION = """
**OUTPUT SCHEMA (STRICT - MUST MATCH EXACTLY)**

Return ONLY valid JSON matching this exact structure:

{
  "utility_responsibilities": [
    {
      "utility_name": "string",
      "responsible": "Tenant | Owner",
      "frequency": "Weekly | Bi-Weekly | Monthly | Quarterly | Bi-Annually | Annually | As Needed | One-time | On Demand | Per Occurrence",
      "charges": {
        "type": "Amount | Percentage",
        "amount_value": number | null,
        "percentage": number | null,
        "base_amount": number | null
      }
    }
  ],
  "common_area_maintenance": [
    {
      "area_name": "string",
      "responsible": "Tenant | Owner",
      "frequency": "Weekly | Bi-Weekly | Monthly | Quarterly | Bi-Annually | Annually | As Needed | One-time | On Demand | Per Occurrence",
      "charges": {
        "type": "Amount | Percentage",
        "amount_value": number | null,
        "percentage": number | null,
        "base_amount": number | null
      }
    }
  ],
  "additional_fees": [
    {
      "fee_name": "string",
      "responsible": "Tenant | Owner",
      "frequency": "Weekly | Bi-Weekly | Monthly | Quarterly | Bi-Annually | Annually | As Needed | One-time | On Demand | Per Occurrence",
      "charges": {
        "type": "Amount | Percentage",
        "amount_value": number | null,
        "percentage": number | null,
        "base_amount": number | null
      }
    }
  ],
  "tenant_improvements": [
    {
      "improvement_item": "string",
      "responsible": "Tenant | Owner",
      "amount": number | null,
      "balance": number | null,
      "recovery_method": "Monthly Amortization | One-time Charge | Rent uplift" | null
    }
  ],
  "term": {
    "lease_start_date": "YYYY-MM-DD",
    "lease_end_date": "YYYY-MM-DD",
    "lease_length": "string",
    "move_in_date": "YYYY-MM-DD",
    "renewal_options": "yes | no",
    "renewal_rent_increase": "string | number"
  },
  "rent_and_deposits": {
    "monthly_base_rent": number,
    "rent_due_date": "1st | 15th | 30th",
    "grace_period": number,
    "late_fee": {
      "type": "Amount | Percentage",
      "amount_value": number | null,
      "percentage": number | null,
      "base_amount": number | null
    },
    "security_deposit": number
  },
  "other_deposits": [
    {
      "label": "string",
      "amount": number
    }
  ],
  "rent_increase_schedule": [
    {
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "base_rent": number,
      "frequency": "Weekly | Bi-Weekly | Monthly | Quarterly | Bi-Annually | Annually | As Needed | One-time | On Demand | Per Occurrence",
      "increase": {
        "type": "Amount | Percentage",
        "value": number | null,
        "percentage": number | null,
        "base_amount": number | null
      },
      "per_sqft_rate": number | null
    }
  ],
  "abatements_discounts": [
    {
      "event_type": "Abatements | Discounts | Waive Rent | Rent Credit | Rent Abatement | Free Rent",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "discount_amount": number,
      "reason": "string"
    }
  ],
  "special_clauses": [
    {
      "description": "string"
    }
  ],
  "nsf_fees": {
    "amount": number
  }
}

**CRITICAL RULES:**
1. Output ONLY valid JSON - no markdown, no explanations, no commentary
2. DO NOT add any text before or after the JSON object
3. DO NOT wrap JSON in code blocks or markdown
4. DO NOT include explanatory notes or reasoning
5. Use null for missing values, empty arrays [] for no items
6. Distinguish between "Amount" and "Percentage" charge types
7. For Amount: set amount_value, set percentage=null
8. For Percentage: set percentage, optionally set base_amount
9. Extract ALL occurrences (arrays can have multiple items)
10. Pay careful attention to tables - extract every row
11. Dates must be YYYY-MM-DD format
12. Numbers must be numeric, not strings (except renewal_rent_increase)
13. Responsible must be exactly "Tenant" or "Owner"

⚠️ CRITICAL: Your response must start with { and end with }. Nothing else.
"""


EXTRACTION_INSTRUCTIONS = """
**EXTRACTION INSTRUCTIONS:**

You are extracting structured data from a commercial lease agreement. This is pages {start_page}-{end_page} of a {total_pages}-page document.

**Context:**
- Window ID: {window_id}
- This is a {window_context} window
- Some data may appear in multiple windows (overlapping pages) - extract everything you see

**Your Task:**
1. Read the provided lease pages carefully and extract ALL relevant data
2. **CRITICAL: Extract ALL numerical amounts - don't leave fields null when amounts are visible**
3. Be thorough - scan for:
   - **Utilities** (electricity, water, gas, internet, trash, etc.) - Extract specific dollar amounts or state "Tenant pays directly"
   - **CAM charges** (cleaning, landscaping, parking, common area costs) - Extract percentage of operating expenses or flat amounts
   - **Additional fees** (admin fees, processing fees, insurance, taxes) - Extract exact amounts or percentages
   - **Tenant improvements** (TI allowances, build-out costs) - Extract total amounts and recovery methods
   - **Dates** (start, end, move-in, renewals) - Use exact dates from lease
   - **Rent amounts** - Extract base monthly rent, NOT per square foot rates unless that's the only value given
   - **Security deposits** - Extract exact amounts
   - **Rent increase schedules** - Extract all annual increases with dates and amounts/percentages
   - **Late fees** - Extract percentage OR flat amount (NOT both) into rent_and_deposits.late_fee
   - **NSF/bounced check fees** - Extract exact amount into nsf_fees.amount
   - **Abatements** (free rent periods, discounts) - Extract dates and amounts
   - **Special clauses** (use restrictions, holdover, options, etc.)

4. **For charges - BE SPECIFIC:**
   - If stated as "$X per month" or just "$X" → type="Amount", amount_value=X, percentage=null
   - If stated as "X%" or "X percent" → type="Percentage", percentage=X (NOT null)
   - If stated as "X% of $Y" → type="Percentage", percentage=X, base_amount=Y
   - If stated as "$X per square foot" → type="Amount", amount_value=X, note it in base_amount context
   - **LATE FEES - CRITICAL:** Late fees are EITHER a flat amount OR a percentage, NEVER both:
     - "Late fee: $100" → type="Amount", amount_value=100, percentage=null
     - "Late fee: 10% of unpaid rent" → type="Percentage", percentage=10, amount_value=null
     - "Greater of $100 or 10%" → Choose ONE: type="Amount", amount_value=100 (the $100 is typically the primary charge)
     - **DO NOT** set both amount_value AND percentage in the same charge object
   - **CRITICAL: If you set type="Percentage", you MUST provide the percentage number. If you can't find a percentage value, DO NOT create the entry at all**
   - **CRITICAL: If you set type="Amount", you MUST provide amount_value. If amount is not specified (e.g., "Tenant pays directly"), use amount_value=null**

5. **For rent calculations - CRITICAL - READ THIS CAREFULLY:**
   - **monthly_base_rent = MONTHLY RENT IN DOLLARS, NOT ANNUAL, NOT PER SQFT RATE**
   - **PREFERRED METHOD - Calculate from square footage:**
     - **STEP 1:** Find premises square footage (e.g., "3,560 square feet", "3560 sq ft", "rentable area")
     - **STEP 2:** Find rent rate per square foot (e.g., "$3.25 per sq ft", "$3.25/sf", "$3.25 psf")
     - **STEP 3:** Calculate: square_footage × rate_per_sqft = monthly_base_rent
       - Example: 3,560 sq ft × $3.25/sq ft = $11,573.00/month

6. **For tables:**
   - Extract EVERY row as a separate array item
   - Include all columns with their values
   - Don't summarize or skip rows
   - **For rent schedules:** Extract each year as a separate rent_increase_schedule entry with start_date, end_date, and base_rent

7. **For dates - CRITICAL DATE TYPES:**
   - Use YYYY-MM-DD format
   - **lease_start_date** = Commencement Date / Effective Date (when lease LEGALLY BEGINS)
   - **move_in_date** = Date tenant takes possession (may be same as or different from start date)
   - **lease_end_date** = Expiration Date / Termination Date

8. **For unclear values:**
   - Look at surrounding context for clues
   - Check exhibits, schedules, and attachments
   - Scan tables, fine print, footnotes
   - **Only use null if the value is truly not mentioned anywhere in the visible pages**

9. Return ONLY the JSON object - no other text

**REMEMBER:**
- This is {window_context} data extraction
- Extract everything visible in these pages
- Overlapping windows will be merged later
- Precision and completeness matter more than avoiding duplication
"""


def build_extraction_prompt(
    window_text: str,
    window_context: dict
) -> str:
    """
    Build complete extraction prompt for a window
    
    Args:
        window_text: Text content of the window
        window_context: Window metadata (start_page, end_page, etc.)
        
    Returns:
        Complete prompt string
    """
    # Determine window context description
    is_first = window_context.get('is_first_window', False)
    is_last = window_context.get('is_last_window', False)
    
    if is_first and is_last:
        context_desc = "complete"
    elif is_first:
        context_desc = "first"
    elif is_last:
        context_desc = "final"
    else:
        context_desc = "middle"
    
    # Format instructions with context
    instructions = EXTRACTION_INSTRUCTIONS.format(
        start_page=window_context['start_page'],
        end_page=window_context['end_page'],
        total_pages=window_context['total_pages'],
        window_id=window_context['window_id'],
        window_context=context_desc
    )
    
    # Build complete prompt
    prompt = f"""
{SCHEMA_DEFINITION}

{instructions}

**LEASE DOCUMENT (Pages {window_context['start_page']}-{window_context['end_page']}):**

{window_text}

**NOW EXTRACT THE DATA AS JSON:**

Reminder: Output ONLY the JSON object. Start with {{ and end with }}. No other text.
""".strip()
    
    return prompt


def build_validation_prompt(
    extracted_data: dict,
    issues: list
) -> str:
    """
    Build prompt for validation/correction of extracted data
    
    Args:
        extracted_data: Previously extracted data
        issues: List of validation issues found
        
    Returns:
        Validation prompt
    """
    issues_text = "\n".join(f"- {issue}" for issue in issues)
    
    prompt = f"""
The following data was extracted from a lease but has validation issues:

**ISSUES FOUND:**
{issues_text}

**EXTRACTED DATA:**
{extracted_data}

Please correct these issues and return ONLY the corrected JSON matching the schema.
Focus on fixing the specific issues mentioned above.

{SCHEMA_DEFINITION}

**CORRECTED JSON:**
""".strip()
    
    return prompt
