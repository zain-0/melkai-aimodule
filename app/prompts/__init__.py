"""
Prompt templates for AWS Bedrock AI operations.

This package contains organized prompt builders for different domains:
- lease_analysis_prompts: Lease violation analysis
- maintenance_prompts: Maintenance request handling
- tenant_communication_prompts: Tenant messaging and move-out evaluations
- chat_prompts: Conversational maintenance assistant
"""

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

__all__ = [
    # Lease analysis
    "build_lease_analysis_prompt",
    "build_categorized_analysis_prompt",
    "CATEGORIZED_ANALYSIS_SYSTEM_PROMPT",
    
    # Maintenance
    "build_maintenance_evaluation_prompt",
    "build_vendor_work_order_prompt",
    "build_maintenance_workflow_prompt",
    
    # Tenant communication
    "build_tenant_message_rewrite_prompt",
    "build_move_out_evaluation_prompt",
    
    # Chat
    "MAINTENANCE_CHAT_SYSTEM_PROMPT",
    "build_maintenance_extraction_prompt",
    "build_conversation_summary_prompt",
]
