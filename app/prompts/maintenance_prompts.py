"""Prompt templates for maintenance workflow operations"""

from typing import Optional
from app.models import LeaseInfo


def build_maintenance_evaluation_prompt(
    maintenance_request: str,
    lease_info: LeaseInfo,
    landlord_notes: Optional[str] = None
) -> str:
    """
    Build prompt for evaluating maintenance requests.
    
    Args:
        maintenance_request: Tenant's maintenance request text
        lease_info: Lease document information
        landlord_notes: Optional notes from landlord
        
    Returns:
        Formatted prompt string
    """
    prompt = f"""You are a landlord reviewing a maintenance request. Evaluate it against the lease agreement and decide whether to APPROVE or REJECT based ONLY on the lease terms.

MAINTENANCE REQUEST FROM TENANT:
{maintenance_request}
"""
    
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


def build_vendor_work_order_prompt(
    maintenance_request: str,
    lease_info: LeaseInfo,
    landlord_notes: Optional[str] = None
) -> str:
    """
    Build prompt for generating vendor work orders.
    
    Args:
        maintenance_request: Tenant's maintenance request text
        lease_info: Lease document information
        landlord_notes: Optional notes from landlord
        
    Returns:
        Formatted prompt string
    """
    prompt = f"""You are creating a professional work order for a vendor/contractor to fix a maintenance issue.

MAINTENANCE REQUEST FROM TENANT:
{maintenance_request}
"""
    
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


def build_maintenance_workflow_prompt(
    maintenance_request: str,
    lease_info: LeaseInfo,
    landlord_notes: Optional[str] = None
) -> str:
    """
    Build prompt for complete maintenance workflow processing.
    
    Args:
        maintenance_request: Tenant's maintenance request text
        lease_info: Lease document information
        landlord_notes: Optional notes from landlord
        
    Returns:
        Formatted prompt string
    """
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
