"""Input validation utilities for API endpoints"""

from app.exceptions import ValidationError


def validate_text_input(
    text: str,
    field_name: str,
    min_length: int = 10,
    max_length: int = 5000,
    allow_empty: bool = False
) -> str:
    """
    Validate and sanitize text input
    
    Args:
        text: Input text to validate
        field_name: Name of the field (for error messages)
        min_length: Minimum allowed length
        max_length: Maximum allowed length
        allow_empty: Whether to allow empty strings
        
    Returns:
        Cleaned text with stripped whitespace
        
    Raises:
        ValidationError: If validation fails
    """
    # Check if None
    if text is None:
        raise ValidationError(
            message=f"{field_name} is required",
            details=f"The {field_name} field cannot be null"
        )
    
    # Strip whitespace
    cleaned_text = text.strip()
    
    # Check if empty
    if not cleaned_text:
        if allow_empty:
            return cleaned_text
        raise ValidationError(
            message=f"{field_name} cannot be empty",
            details=f"The {field_name} field contains only whitespace or is empty",
            suggestion=f"Please provide a valid {field_name}"
        )
    
    # Check minimum length
    if len(cleaned_text) < min_length:
        raise ValidationError(
            message=f"{field_name} is too short",
            details=f"The {field_name} must be at least {min_length} characters (currently {len(cleaned_text)})",
            suggestion=f"Please provide more details in your {field_name}"
        )
    
    # Check maximum length
    if len(cleaned_text) > max_length:
        raise ValidationError(
            message=f"{field_name} is too long",
            details=f"The {field_name} must be at most {max_length} characters (currently {len(cleaned_text)})",
            suggestion=f"Please shorten your {field_name} to {max_length} characters or less"
        )
    
    return cleaned_text


def validate_maintenance_request(request: str) -> str:
    """
    Validate maintenance request text
    
    Args:
        request: Maintenance request text
        
    Returns:
        Validated and cleaned request text
        
    Raises:
        ValidationError: If validation fails
    """
    return validate_text_input(
        text=request,
        field_name="maintenance request",
        min_length=5,
        max_length=2000
    )


def validate_tenant_message(message: str) -> str:
    """
    Validate tenant message for rewriting
    
    Args:
        message: Tenant's original message
        
    Returns:
        Validated and cleaned message
        
    Raises:
        ValidationError: If validation fails
    """
    return validate_text_input(
        text=message,
        field_name="tenant message",
        min_length=3,
        max_length=1000
    )


def validate_landlord_notes(notes: str) -> str:
    """
    Validate landlord notes (optional field)
    
    Args:
        notes: Landlord's notes
        
    Returns:
        Validated and cleaned notes, or empty string if empty
        
    Raises:
        ValidationError: If validation fails
    """
    if notes is None or not notes.strip():
        return ""
    
    return validate_text_input(
        text=notes,
        field_name="landlord notes",
        min_length=3,
        max_length=2000,
        allow_empty=True
    )


def validate_pdf_bytes(pdf_bytes: bytes, max_size_mb: int = 10) -> None:
    """
    Validate PDF file bytes
    
    Args:
        pdf_bytes: PDF file content
        max_size_mb: Maximum allowed file size in MB
        
    Raises:
        ValidationError: If validation fails
    """
    if not pdf_bytes:
        raise ValidationError(
            message="PDF file is empty",
            details="The uploaded file contains no data",
            suggestion="Please upload a valid PDF file"
        )
    
    # Check size
    size_mb = len(pdf_bytes) / (1024 * 1024)
    if size_mb > max_size_mb:
        raise ValidationError(
            message=f"PDF file is too large",
            details=f"File size is {size_mb:.2f}MB, maximum allowed is {max_size_mb}MB",
            suggestion=f"Please upload a PDF file smaller than {max_size_mb}MB"
        )
    
    # Check PDF magic bytes (%PDF)
    if not pdf_bytes.startswith(b'%PDF'):
        raise ValidationError(
            message="Invalid PDF file",
            details="The uploaded file does not appear to be a valid PDF",
            suggestion="Please ensure you're uploading a PDF file, not another file type renamed to .pdf"
        )
