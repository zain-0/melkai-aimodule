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


class FileSizeError(APIException):
    """Raised when uploaded file exceeds size limit"""
    def __init__(self, max_size_mb: int):
        super().__init__(
            message=f"File size exceeds {max_size_mb}MB limit",
            error_code="FILE_TOO_LARGE",
            details=f"Maximum allowed file size is {max_size_mb}MB",
            suggestion=f"Please upload a file smaller than {max_size_mb}MB",
            status_code=413
        )


class UnsupportedFileTypeError(APIException):
    """Raised when uploaded file type is not supported"""
    def __init__(self, file_type: str, supported_types: list):
        super().__init__(
            message=f"Unsupported file type: {file_type}",
            error_code="UNSUPPORTED_FILE_TYPE",
            details=f"Supported file types: {', '.join(supported_types)}",
            suggestion=f"Please upload one of the following file types: {', '.join(supported_types)}",
            status_code=415
        )


class RateLimitError(APIException):
    """Raised when rate limit is exceeded"""
    def __init__(self, retry_after_seconds: int = 60):
        super().__init__(
            message="Rate limit exceeded",
            error_code="RATE_LIMIT_EXCEEDED",
            details=f"Too many requests. Please retry after {retry_after_seconds} seconds",
            suggestion=f"Wait {retry_after_seconds} seconds before making another request",
            status_code=429
        )


class ServerError(APIException):
    """Raised for general server errors"""
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(
            message=message,
            error_code="SERVER_ERROR",
            details=details,
            suggestion="Please try again later. If the problem persists, contact support",
            status_code=500
        )
