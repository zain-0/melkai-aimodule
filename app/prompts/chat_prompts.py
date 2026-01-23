"""Prompt templates for maintenance chat and extraction operations"""

from typing import Optional, List, Dict, Any
from app.models import LeaseInfo


# System prompt for maintenance chat
MAINTENANCE_CHAT_SYSTEM_PROMPT = """You are a helpful property management AI assistant helping tenants communicate maintenance issues to their landlord or property owner.

Your role:
- Help tenants describe maintenance issues clearly
- Ask follow-up questions to get complete information
- Provide helpful guidance about what details are important
- Be empathetic and professional
- Guide the conversation to gather: what's broken, location, when it started, how urgent

Response format:
- Keep responses conversational and friendly
- Ask one or two questions at a time (don't overwhelm)
- Acknowledge what they've told you
- If you have enough information, tell them they're ready to submit

When you have sufficient information (what, where, when, urgency):
- Summarize what you understand
- Tell them: "You can now click the red button to submit your maintenance request"
- DO NOT say you have created or will create a ticket
- DO NOT say you will send anything to the landlord
- The tenant must click the button to submit

Remember:
- You're here to help, not judge
- Some people may not know how to describe problems - help them
- Be patient with unclear or incomplete information
- Maintain a supportive, helpful tone
- You CANNOT submit tickets - only guide them to click the button"""


def build_maintenance_extraction_prompt(
    conversation_messages: List[Dict[str, Any]],
    lease_info: Optional[LeaseInfo] = None
) -> str:
    """
    Build prompt for extracting structured maintenance information from chat.
    
    Args:
        conversation_messages: List of chat messages with role and content
        lease_info: Optional lease document information
        
    Returns:
        Formatted prompt string
    """
    # Format conversation history
    conversation_text = "\n\n".join([
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in conversation_messages
    ])
    
    prompt = f"""You are analyzing a conversation between a tenant and an AI assistant about a maintenance issue.
Extract all relevant information about the maintenance request.

CONVERSATION:
{conversation_text}
"""
    
    if lease_info:
        prompt += f"""
LEASE INFORMATION (for context):
Property Address: {lease_info.property_address if hasattr(lease_info, 'property_address') else 'Not available'}
Tenant Name: {lease_info.tenant_name if hasattr(lease_info, 'tenant_name') else 'Not available'}
"""
    
    prompt += """
YOUR TASK:
Extract and structure all maintenance-related information from this conversation.

IMPORTANT: Return ONLY valid JSON. Do not include any text before or after the JSON.

Return the extracted information in this exact JSON format:
{
  "issue_description": "Clear, detailed description of the maintenance issue",
  "location": "Specific location in the property (e.g., 'master bathroom', 'kitchen sink', 'bedroom ceiling')",
  "urgency": "emergency|urgent|routine",
  "urgency_reason": "Explanation of why this urgency level",
  "when_started": "When the problem started (e.g., 'this morning', '3 days ago', 'last week')",
  "additional_details": [
    "Any other relevant details mentioned",
    "Impact on tenant",
    "Previous attempts to fix"
  ],
  "tenant_availability": "When tenant is available for repair visit, if mentioned",
  "photos_mentioned": true or false,
  "ready_to_send": true or false,
  "missing_information": [
    "List any important missing details",
    "Questions that still need answers"
  ]
}

URGENCY GUIDELINES:
- "emergency": Safety issues, no heat/AC in extreme weather, major leaks, no water, gas leaks, electrical hazards, broken locks
- "urgent": Significant issues needing quick attention (broken major appliances, moderate leaks, no hot water, pest infestation)
- "routine": Non-urgent maintenance (cosmetic issues, minor repairs, slow drains, light bulbs)

READY TO SEND CRITERIA:
Set "ready_to_send": true ONLY if you have:
- Clear description of the problem
- Specific location
- When it started
- Urgency level can be determined

If any critical information is missing, set "ready_to_send": false and list what's missing.

Examples:

Example 1 - READY:
Tenant: "The toilet in the main bathroom is leaking at the base. It started yesterday and there's water pooling on the floor. I put towels down but it keeps leaking every time someone flushes."
Result:
{
  "issue_description": "Toilet leaking at the base, water pooling on floor after each flush",
  "location": "main bathroom",
  "urgency": "urgent",
  "urgency_reason": "Active water leak causing potential floor damage",
  "when_started": "yesterday",
  "additional_details": ["Tenant placed towels to absorb water", "Leak occurs with each flush"],
  "tenant_availability": "not mentioned",
  "photos_mentioned": false,
  "ready_to_send": true,
  "missing_information": []
}

Example 2 - NOT READY:
Tenant: "Something is broken"
Assistant: "I'm sorry to hear that! Can you tell me what's broken?"
Tenant: "In the bathroom"
Result:
{
  "issue_description": "Unspecified issue in bathroom",
  "location": "bathroom",
  "urgency": "unknown",
  "urgency_reason": "Insufficient information to determine urgency",
  "when_started": "not mentioned",
  "additional_details": [],
  "tenant_availability": "not mentioned",
  "photos_mentioned": false,
  "ready_to_send": false,
  "missing_information": [
    "What specifically is broken?",
    "When did the issue start?",
    "How is this affecting the tenant?"
  ]
}

Rules:
- Be thorough - capture all details mentioned
- Use exact quotes when relevant
- Don't make assumptions about urgency - base it on the actual issue described
- If information is incomplete, clearly note what's missing
- Return ONLY the JSON object, nothing else
"""
    
    return prompt


def build_conversation_summary_prompt(
    conversation_messages: List[Dict[str, Any]]
) -> str:
    """
    Build prompt for summarizing maintenance chat conversations.
    
    Args:
        conversation_messages: List of chat messages with role and content
        
    Returns:
        Formatted prompt string
    """
    conversation_text = "\n\n".join([
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in conversation_messages
    ])
    
    return f"""Summarize this maintenance-related conversation in 2-3 sentences.
Focus on the key issue discussed and any important details gathered.

CONVERSATION:
{conversation_text}

Return a brief, clear summary that captures:
1. What maintenance issue was discussed
2. Key details provided
3. Current status (ready to send to landlord, needs more info, etc.)

Keep it concise and factual."""
