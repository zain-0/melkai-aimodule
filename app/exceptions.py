"""Custom exceptions for better error handling and user feedback"""

from typing import Optional, Dict, Any


class APIException(Exception):
    """Base exception for API errors"""
    def __init__(
        self,
        message: str,
        error_code: str,
        details: Optional[str] = None,
        suggestion: Optional[str] = None,
        status_code: int = 500
    ):
        self.message = message
        self.error_code = error_code
        self.details = details
        self.suggestion = suggestion
        self.status_code = status_code
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to structured error response"""
        error_dict = {
            "error": self.error_code,
            "message": self.message
        }
        if self.details:
            error_dict["details"] = self.details
        if self.suggestion:
            error_dict["suggestion"] = self.suggestion
        return error_dict


class ValidationError(APIException):
    """Raised when input validation fails"""
    def __init__(self, message: str, details: Optional[str] = None, suggestion: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            details=details,
            suggestion=suggestion or "Please check your input and try again",
            status_code=422
        )


class PDFExtractionError(APIException):
    """Raised when PDF extraction fails"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="PDF_EXTRACTION_FAILED",
            details=details,
            suggestion="Please ensure the PDF is not corrupted, password-protected, or scanned. Try uploading a different PDF file.",
            status_code=400
        )


class PDFTimeoutError(APIException):
    """Raised when PDF extraction times out"""
    def __init__(self, timeout_seconds: int):
        super().__init__(
            message=f"PDF extraction timed out after {timeout_seconds} seconds",
            error_code="PDF_TIMEOUT",
            details="The PDF file may be too large, corrupted, or contains complex elements",
            suggestion="Try uploading a smaller or simpler PDF file",
            status_code=408
        )


class AITimeoutError(APIException):
    """Raised when AI API call times out"""
    def __init__(self, timeout_seconds: int):
        super().__init__(
            message=f"AI processing timed out after {timeout_seconds} seconds",
            error_code="AI_TIMEOUT",
            details="The AI service took too long to respond",
            suggestion="Please try again. If the problem persists, try simplifying your request.",
            status_code=504
        )


class AIModelError(APIException):
    """Raised when AI model returns an error"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="AI_MODEL_ERROR",
            details=details,
            suggestion="The AI service encountered an error. Please try again later.",
            status_code=502
        )


class EmptyPDFError(APIException):
    """Raised when PDF contains no extractable text"""
    def __init__(self):
        super().__init__(
            message="PDF contains no extractable text",
            error_code="EMPTY_PDF",
            details="The PDF appears to be a scanned document or contains only images",
            suggestion="Please upload a text-based PDF or use OCR to convert scanned documents to text",
            status_code=400
        )
