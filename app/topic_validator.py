"""
Topic Validation Module

This module provides functions to validate that user inputs are on-topic for each API endpoint.
If an off-topic query is detected, it returns a rejection message.
"""

from typing import Optional, Tuple
import re
from app.bedrock_client import BedrockClient
from app.config import settings
import logging

logger = logging.getLogger(__name__)

bedrock_client = BedrockClient()

OFF_TOPIC_MESSAGE = "Sorry, I can't help you with that."


def is_lease_analysis_topic(text: str) -> bool:
    """
    Validate if text is related to lease analysis/violation checking.
    
    Args:
        text: User input text
        
    Returns:
        True if on-topic, False otherwise
    """
    # Keywords for lease analysis
    lease_keywords = [
        'lease', 'rental', 'rent', 'tenant', 'landlord', 'property',
        'violation', 'agreement', 'contract', 'housing', 'apartment',
        'eviction', 'deposit', 'security', 'occupancy', 'premises',
        'residential', 'commercial', 'real estate', 'renting'
    ]
    
    text_lower = text.lower()
    
    # Check if any lease keywords are present
    has_lease_keywords = any(keyword in text_lower for keyword in lease_keywords)
    
    # Check for obviously off-topic queries
    off_topic_indicators = [
        'weather', 'recipe', 'sports', 'movie', 'music', 'game',
        'joke', 'story', 'poem', 'song', 'calculate', 'math problem',
        'translate', 'define', 'what is', 'who is', 'when did'
    ]
    
    has_off_topic = any(indicator in text_lower for indicator in off_topic_indicators)
    
    # If it has obvious off-topic indicators and no lease keywords, reject
    if has_off_topic and not has_lease_keywords:
        return False
    
    return True


def validate_maintenance_topic(maintenance_request: str, landlord_notes: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate if maintenance request is actually about property maintenance.
    
    Args:
        maintenance_request: The maintenance request text
        landlord_notes: Optional landlord notes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Maintenance keywords
    maintenance_keywords = [
        'repair', 'fix', 'broken', 'leak', 'maintenance', 'heating', 'cooling',
        'plumbing', 'electrical', 'hvac', 'ac', 'heater', 'water', 'appliance',
        'door', 'window', 'roof', 'wall', 'floor', 'ceiling', 'toilet', 'sink',
        'faucet', 'shower', 'bath', 'kitchen', 'bedroom', 'light', 'outlet',
        'pipe', 'drain', 'smoke detector', 'thermostat', 'furnace', 'radiator',
        'dishwasher', 'refrigerator', 'stove', 'oven', 'garbage disposal',
        'not working', 'broken', 'damaged', 'malfunctioning', 'issue', 'problem'
    ]
    
    request_lower = maintenance_request.lower()
    
    # Check if any maintenance keywords are present
    has_maintenance_keywords = any(keyword in request_lower for keyword in maintenance_keywords)
    
    # Check for obviously off-topic content
    off_topic_patterns = [
        r'\b(weather|recipe|joke|story|poem|movie|music|game|sport)\b',
        r'\b(calculate|math|translate|define)\b',
        r'\b(what is|who is|when did|where is)\b(?!.*(broken|not working|issue|problem))',
    ]
    
    for pattern in off_topic_patterns:
        if re.search(pattern, request_lower) and not has_maintenance_keywords:
            return False, OFF_TOPIC_MESSAGE
    
    # If request is very short and has no maintenance keywords, it's likely off-topic
    if len(maintenance_request.strip().split()) < 3 and not has_maintenance_keywords:
        # Use AI to check if it's a valid maintenance request
        return _ai_validate_maintenance(maintenance_request)
    
    return True, None


def validate_move_out_topic(move_out_request: str, owner_notes: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate if move-out request is actually about moving out/lease termination.
    
    Args:
        move_out_request: The move-out request text
        owner_notes: Optional owner notes
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Move-out keywords
    move_out_keywords = [
        'move out', 'moving out', 'move-out', 'vacate', 'vacating', 'leave',
        'leaving', 'end lease', 'terminate', 'termination', 'notice', 'giving notice',
        '30 day', '60 day', 'deposit refund', 'security deposit', 'final inspection',
        'move out date', 'last day', 'ending tenancy', 'breaking lease'
    ]
    
    request_lower = move_out_request.lower()
    
    # Check if any move-out keywords are present
    has_move_out_keywords = any(keyword in request_lower for keyword in move_out_keywords)
    
    if not has_move_out_keywords:
        # Check if it's about lease termination or ending tenancy
        termination_patterns = [
            r'\b(end|ending|finish|finishing|quit|quitting)\b.*\b(lease|tenancy|rental)\b',
            r'\b(lease|tenancy|rental)\b.*\b(end|ending|finish|finishing)\b'
        ]
        
        has_termination_pattern = any(re.search(pattern, request_lower) for pattern in termination_patterns)
        
        if not has_termination_pattern:
            return False, OFF_TOPIC_MESSAGE
    
    return True, None


def validate_tenant_chat_topic(message: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if tenant chat message is about maintenance/property issues.
    
    Args:
        message: The tenant's message
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # This is more lenient since it's a chat interface
    # We want to allow troubleshooting questions
    
    property_keywords = [
        'broken', 'not working', 'issue', 'problem', 'repair', 'fix',
        'leak', 'water', 'heat', 'cold', 'noise', 'smell', 'door',
        'window', 'lock', 'light', 'electricity', 'power', 'toilet',
        'shower', 'bath', 'sink', 'kitchen', 'bedroom', 'living room',
        'appliance', 'ac', 'heater', 'hvac', 'plumbing', 'electrical',
        'maintenance', 'help', 'urgent', 'emergency', 'apartment', 'unit'
    ]
    
    message_lower = message.lower()
    
    # Check if any property-related keywords are present
    has_property_keywords = any(keyword in message_lower for keyword in property_keywords)
    
    # For greetings or very short messages, allow them (part of conversation flow)
    short_allowed = ['hi', 'hello', 'hey', 'yes', 'no', 'ok', 'okay', 'thanks', 'thank you', 'bye']
    if message_lower.strip() in short_allowed or len(message.strip()) < 3:
        return True, None
    
    # If message is asking about completely unrelated topics
    unrelated_topics = [
        'weather', 'recipe', 'cooking', 'baking', 'movie', 'film', 'music',
        'song', 'game', 'sport', 'football', 'basketball', 'baseball',
        'politics', 'election', 'president', 'stock', 'investment',
        'math problem', 'homework', 'essay', 'write a', 'poem', 'story'
    ]
    
    has_unrelated = any(topic in message_lower for topic in unrelated_topics)
    
    if has_unrelated and not has_property_keywords:
        return False, OFF_TOPIC_MESSAGE
    
    return True, None


def validate_email_rewrite_topic(text: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if email rewrite request is related to property management/leases.
    
    Args:
        text: The text to be rewritten as email
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Email rewrite should be about property management, leases, maintenance, or tenant communications
    relevant_keywords = [
        'lease', 'rent', 'tenant', 'landlord', 'property', 'maintenance',
        'repair', 'notice', 'violation', 'deposit', 'payment', 'eviction',
        'inspection', 'move', 'occupancy', 'agreement', 'contract', 'unit',
        'apartment', 'building', 'premises', 'utilities', 'parking'
    ]
    
    text_lower = text.lower()
    
    # Check if any relevant keywords are present
    has_relevant_keywords = any(keyword in text_lower for keyword in relevant_keywords)
    
    if not has_relevant_keywords:
        # Check if it's about completely unrelated topics
        unrelated_patterns = [
            r'\b(recipe|cooking|weather|sports|movie|music|game)\b',
            r'\b(joke|story|poem|song)\b',
            r'\b(math|science|history|geography)\b(?!.*property)',
        ]
        
        for pattern in unrelated_patterns:
            if re.search(pattern, text_lower):
                return False, OFF_TOPIC_MESSAGE
    
    return True, None


def _ai_validate_maintenance(maintenance_request: str) -> Tuple[bool, Optional[str]]:
    """
    Use AI to validate if a short/ambiguous request is about maintenance.
    
    Args:
        maintenance_request: The maintenance request text
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        system_prompt = """You are a validation assistant. Determine if the user's message is about property maintenance, repairs, or issues with rental property/apartment.

Respond with ONLY "YES" if it's about maintenance/property issues.
Respond with ONLY "NO" if it's about something else (weather, jokes, recipes, math, etc.)."""

        user_prompt = f"Is this about property maintenance or repairs?\n\nMessage: {maintenance_request}"
        
        response = bedrock_client.generate_text(
            model_id=settings.FREE_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=10,
            temperature=0.0
        )
        
        response_clean = response.strip().upper()
        
        if "YES" in response_clean:
            return True, None
        else:
            return False, OFF_TOPIC_MESSAGE
            
    except Exception as e:
        logger.error(f"AI validation failed: {e}")
        # On error, be permissive (allow the request)
        return True, None
