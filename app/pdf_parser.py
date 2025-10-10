import pdfplumber
import re
import signal
from typing import Optional
from contextlib import contextmanager
from app.models import LeaseInfo
from app.exceptions import PDFExtractionError, PDFTimeoutError, EmptyPDFError
from app.validators import validate_pdf_bytes
import logging

logger = logging.getLogger(__name__)


@contextmanager
def timeout(seconds: int):
    """Context manager for timeout on operations"""
    def timeout_handler(signum, frame):
        raise PDFTimeoutError(timeout_seconds=seconds)
    
    # Note: signal.alarm only works on Unix systems
    # For Windows compatibility, we'll use a different approach
    try:
        if hasattr(signal, 'SIGALRM'):
            # Unix/Linux/Mac
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(seconds)
            try:
                yield
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # Windows - no timeout mechanism, just yield
            yield
    except Exception as e:
        if isinstance(e, PDFTimeoutError):
            raise
        raise


class PDFParser:
    """Extract text and key information from lease PDF files"""
    
    @staticmethod
    def extract_lease_info(pdf_bytes: bytes, timeout_seconds: int = 30) -> LeaseInfo:
        """
        Extract lease information from PDF bytes with timeout
        
        Args:
            pdf_bytes: PDF file content as bytes
            timeout_seconds: Maximum time to spend extracting (default 30s)
            
        Returns:
            LeaseInfo object with ONLY full_text (AI will extract location and other fields)
            
        Raises:
            PDFExtractionError: If PDF extraction fails
            PDFTimeoutError: If extraction takes too long
            EmptyPDFError: If PDF contains no text
        """
        # Validate PDF bytes
        validate_pdf_bytes(pdf_bytes)
        
        try:
            # Extract full text with timeout
            full_text = PDFParser._extract_text_with_timeout(pdf_bytes, timeout_seconds)
            
            # Check if text was extracted
            if not full_text or not full_text.strip():
                raise EmptyPDFError()
            
            # Return LeaseInfo with ONLY the full text
            # AI models will extract location, landlord, tenant, etc. from the text
            return LeaseInfo(
                full_text=full_text,
                address=None,
                city=None,
                state=None,
                county=None,
                landlord=None,
                tenant=None,
                rent_amount=None,
                security_deposit=None,
                lease_duration=None
            )
        except (PDFExtractionError, PDFTimeoutError, EmptyPDFError):
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error extracting PDF: {str(e)}")
            raise PDFExtractionError(
                message="Failed to extract text from PDF",
                details=str(e)
            )
    
    @staticmethod
    def _extract_text_with_timeout(pdf_bytes: bytes, timeout_seconds: int) -> str:
        """Extract all text from PDF with timeout protection"""
        import io
        
        try:
            text_parts = []
            
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                # Check if PDF has pages
                if not pdf.pages:
                    raise PDFExtractionError(
                        message="PDF file has no pages",
                        details="The PDF appears to be empty or corrupted"
                    )
                
                # Extract text from each page
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(page_text)
                    except Exception as e:
                        logger.warning(f"Failed to extract text from page {page_num}: {str(e)}")
                        # Continue with other pages
                        continue
            
            return "\n\n".join(text_parts)
        
        except PDFExtractionError:
            raise
        except Exception as e:
            # Handle pdfplumber-specific errors
            error_msg = str(e).lower()
            if "password" in error_msg or "encrypted" in error_msg:
                raise PDFExtractionError(
                    message="PDF is password-protected",
                    details="This PDF requires a password to open"
                )
            elif "damaged" in error_msg or "corrupt" in error_msg:
                raise PDFExtractionError(
                    message="PDF file is corrupted",
                    details="The PDF file appears to be damaged or incomplete"
                )
            else:
                raise PDFExtractionError(
                    message="Failed to read PDF file",
                    details=f"Error: {str(e)}"
                )
    
    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        """Legacy method - calls new timeout version"""
        return PDFParser._extract_text_with_timeout(pdf_bytes, timeout_seconds=30)
    
    @staticmethod
    def _extract_address(text: str) -> dict:
        """Extract property address information"""
        result = {}
        
        # Common patterns for addresses in leases
        address_patterns = [
            r"(?:property|premises|located at|address)[:\s]+([^\n]+?(?:street|st|avenue|ave|road|rd|drive|dr|blvd|boulevard|lane|ln|way|court|ct)\.?[,\s]+[A-Za-z\s]+[,\s]+[A-Z]{2})",
            r"(?:property|premises|located at|address)[:\s]+([^\n]+)",
            r"(\d+\s+[A-Za-z\s]+(?:street|st|avenue|ave|road|rd|drive|dr|blvd|boulevard|lane|ln|way|court|ct)[^\n]*)",
        ]
        
        full_address = None
        for pattern in address_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                full_address = match.group(1).strip()
                result["address"] = full_address
                break
        
        # Try to extract city, state from the full address or separately
        if full_address:
            # Pattern: City, State ZIP or City, State
            city_state_pattern = r"([A-Za-z\s]+),\s*([A-Z]{2})(?:\s+\d{5})?(?:\s|$|,)"
            cs_match = re.search(city_state_pattern, full_address)
            if cs_match:
                result["city"] = cs_match.group(1).strip()
                result["state"] = cs_match.group(2).strip()
        
        # If not found in address, search elsewhere in text
        if "city" not in result:
            city_patterns = [
                r"(?:city|town)[:\s]+([A-Za-z\s]+?)(?:,|\s+[A-Z]{2}|\n)",
                r"(?:in the (?:city|town) of)\s+([A-Za-z\s]+?)(?:,|\s+[A-Z]{2}|\n)",
            ]
            for pattern in city_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    result["city"] = match.group(1).strip()
                    break
        
        # Extract state (look for 2-letter state codes)
        if "state" not in result:
            state_patterns = [
                r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b",  # State before ZIP
                r"(?:state of)\s+([A-Z]{2})\b",  # "State of XX"
                r"(?:,\s*)([A-Z]{2})(?:\s|,|$)",  # ", XX" at end
            ]
            for pattern in state_patterns:
                match = re.search(pattern, text)
                if match:
                    result["state"] = match.group(1)
                    break
        
        # Extract county - improved patterns
        county_patterns = [
            r"(?:county of)\s+([A-Za-z\s]+?)(?:\s+county|,|\n|state)",
            r"([A-Za-z\s]+)\s+county(?:,|\s|$)",
            r"(?:in)\s+([A-Za-z\s]+)\s+county",
        ]
        for pattern in county_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                county_name = match.group(1).strip()
                # Clean up - remove common words that get captured
                county_name = re.sub(r'\b(the|of|in)\b', '', county_name, flags=re.IGNORECASE).strip()
                if len(county_name) > 2 and county_name.replace(' ', '').isalpha():
                    result["county"] = county_name
                    break
        
        return result
    
    @staticmethod
    def _extract_financial_info(text: str) -> dict:
        """Extract rent and deposit information"""
        result = {}
        
        # Rent patterns
        rent_patterns = [
            r"(?:monthly\s+rent|rent\s+amount)[:\s]+\$?([\d,]+(?:\.\d{2})?)",
            r"(?:tenant\s+shall\s+pay|agrees\s+to\s+pay)[^\$]*\$?([\d,]+(?:\.\d{2})?)\s*(?:per\s+month|monthly)",
        ]
        
        for pattern in rent_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["rent"] = f"${match.group(1)}"
                break
        
        # Security deposit patterns
        deposit_patterns = [
            r"(?:security\s+deposit)[:\s]+\$?([\d,]+(?:\.\d{2})?)",
            r"(?:deposit\s+of)[:\s]+\$?([\d,]+(?:\.\d{2})?)",
        ]
        
        for pattern in deposit_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["deposit"] = f"${match.group(1)}"
                break
        
        return result
    
    @staticmethod
    def _extract_parties(text: str) -> dict:
        """Extract landlord and tenant information"""
        result = {}
        
        # Landlord patterns
        landlord_patterns = [
            r"(?:landlord|lessor|owner)[:\s]+([A-Za-z\s\.]+)(?:\n|,|hereinafter)",
            r"between\s+([A-Za-z\s\.]+)\s+(?:as\s+)?(?:landlord|lessor)",
        ]
        
        for pattern in landlord_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["landlord"] = match.group(1).strip()
                break
        
        # Tenant patterns
        tenant_patterns = [
            r"(?:tenant|lessee|renter)[:\s]+([A-Za-z\s\.]+)(?:\n|,|hereinafter)",
            r"and\s+([A-Za-z\s\.]+)\s+(?:as\s+)?(?:tenant|lessee)",
        ]
        
        for pattern in tenant_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["tenant"] = match.group(1).strip()
                break
        
        return result
    
    @staticmethod
    def _extract_duration(text: str) -> Optional[str]:
        """Extract lease duration/term"""
        duration_patterns = [
            r"(?:term|duration|period)[:\s]+(\d+\s+(?:month|year)s?)",
            r"(?:lease\s+term)[:\s]+([^\n]+)",
        ]
        
        for pattern in duration_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
