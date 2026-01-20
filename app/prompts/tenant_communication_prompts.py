"""Prompt templates for tenant communication operations"""

from typing import Optional
from app.models import LeaseInfo
from datetime import datetime


def build_tenant_message_rewrite_prompt(tenant_message: str) -> str:
    """
    Build prompt for rewriting tenant messages professionally.
    
    Args:
        tenant_message: Original message from tenant
        
    Returns:
        Formatted prompt string
    """
    return f"""You are helping a tenant communicate a maintenance issue to their landlord.

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


def build_move_out_evaluation_prompt(
    move_out_request: str,
    lease_info: LeaseInfo,
    owner_notes: Optional[str] = None
) -> str:
    """
    Build prompt for evaluating tenant move-out requests.
    
    Args:
        move_out_request: Tenant's move-out request text
        lease_info: Lease document information
        owner_notes: Optional notes from property owner
        
    Returns:
        Formatted prompt string
    """
    today = datetime.now().strftime("%B %d, %Y")
    
    prompt = f"""You are a property owner evaluating a tenant's move-out request. Review the lease agreement and determine:
1. If the tenant provided proper notice according to the lease
2. What financial obligations remain (rent, fees, security deposit)
3. Clear next steps for the tenant

TODAY'S DATE: {today}
IMPORTANT: Use this date to calculate notice periods and determine if the tenant gave sufficient notice.

MOVE-OUT REQUEST FROM TENANT:
{move_out_request}
"""
    
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
