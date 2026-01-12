"""
Utility functions for lease extraction API
"""
import logging
import hashlib
from typing import Dict, Any


def generate_request_id(filename: str, file_hash: str = None) -> str:
    """
    Generate idempotent request ID for caching/deduplication
    
    Args:
        filename: Original filename
        file_hash: Optional file content hash
        
    Returns:
        Request ID hash
    """
    import time
    content = f"{filename}:{file_hash or time.time()}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def sanitize_error(error: Exception) -> Dict[str, Any]:
    """
    Sanitize exception for API response
    
    Args:
        error: Exception object
        
    Returns:
        Sanitized error dict
    """
    return {
        'error_type': type(error).__name__,
        'error_message': str(error),
        'error_class': error.__class__.__name__
    }


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str = "haiku"
) -> float:
    """
    Estimate AWS Bedrock cost
    
    Args:
        input_tokens: Input token count
        output_tokens: Output token count
        model: Model type (sonnet or haiku)
        
    Returns:
        Estimated cost in USD
    """
    # Pricing as of Jan 2026 (Claude 3.5 Haiku)
    if model == "haiku":
        input_price = 0.80 / 1_000_000   # $0.80 per 1M input tokens
        output_price = 4.00 / 1_000_000  # $4.00 per 1M output tokens
    else:  # sonnet
        input_price = 3.00 / 1_000_000   # $3.00 per 1M input tokens
        output_price = 15.00 / 1_000_000 # $15.00 per 1M output tokens
    
    cost = (input_tokens * input_price) + (output_tokens * output_price)
    return round(cost, 4)


def validate_pdf_file(filename: str, file_size: int, max_size_mb: int = 100) -> tuple:
    """
    Validate PDF file
    
    Args:
        filename: File name
        file_size: File size in bytes
        max_size_mb: Maximum allowed size in MB
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filename or not isinstance(filename, str):
        return False, "Invalid filename"
    
    if not filename.lower().endswith('.pdf'):
        return False, "File must be a PDF"
    
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        return False, f"File size exceeds {max_size_mb}MB limit"
    
    if file_size == 0:
        return False, "File is empty"
    
    return True, ""


def format_currency(amount: float) -> str:
    """Format amount as USD currency"""
    if amount is None:
        return "N/A"
    return f"${amount:,.2f}"


def truncate_string(s: str, max_length: int = 100) -> str:
    """Truncate string for logging"""
    if not s or len(s) <= max_length:
        return s
    return s[:max_length] + "..."
