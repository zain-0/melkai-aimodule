"""
PDF processing utilities using PyMuPDF with sliding window support and OCR fallback
"""
import asyncio
import logging
from typing import List, Dict, Optional
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Try to import OCR processor
try:
    from app.ocr_processor import get_ocr_processor, is_ocr_available, get_ocr_method_name
    OCR_AVAILABLE = is_ocr_available()
    if OCR_AVAILABLE:
        logger.info(f"OCR available: {get_ocr_method_name()}")
except ImportError as e:
    OCR_AVAILABLE = False
    logger.warning(f"OCR not available: {e}")


class PDFWindow:
    """Represents a window of PDF pages"""
    
    def __init__(self, window_id: int, start_page: int, end_page: int, page_texts: List[str], total_pages: int):
        self.window_id = window_id
        self.start_page = start_page
        self.end_page = end_page
        self.page_texts = page_texts
        self.total_pages = total_pages
        self.text = "\n\n--- PAGE BREAK ---\n\n".join(
            f"=== PAGE {start_page + i + 1} ===\n{text}" for i, text in enumerate(page_texts)
        )
    
    def __repr__(self):
        return f"PDFWindow(id={self.window_id}, pages={self.start_page+1}-{self.end_page+1}/{self.total_pages})"


class LeasePDFProcessor:
    """PDF processing with streaming and sliding windows for lease extraction"""
    
    def __init__(self, window_size: int = 5, window_overlap: int = 1):
        self.window_size = window_size
        self.window_overlap = window_overlap
    
    async def extract_pages_from_bytes(self, pdf_bytes: bytes, filename: str = "upload.pdf") -> List[str]:
        """Extract all pages from PDF bytes asynchronously"""
        logger.info(f"Extracting PDF from uploaded file: {filename}")
        try:
            loop = asyncio.get_event_loop()
            pages = await loop.run_in_executor(None, self._extract_text_from_bytes, pdf_bytes)
            
            # Check if OCR is needed (pages will be None if OCR required)
            if pages is None and OCR_AVAILABLE:
                logger.info(f"Running OCR extraction with {get_ocr_method_name()}...")
                # Get page count first
                pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
                page_count = pdf_document.page_count
                pdf_document.close()
                
                # Get appropriate OCR processor (Textract preferred, Tesseract fallback)
                ocr_processor = get_ocr_processor(prefer_textract=True)
                
                # Run OCR with file size-based splitting
                pages = await ocr_processor.extract_text_from_pdf(pdf_bytes, page_count)
                logger.info(f"OCR extracted {len(pages)} pages from PDF using {get_ocr_method_name()}")
            elif pages is None:
                # OCR needed but not available
                logger.error("OCR required but not available")
                raise ValueError(
                    "PDF appears to be scanned but OCR is not configured. "
                    "Install AWS SDK + credentials or Tesseract: pip install pytesseract pdf2image"
                )
            else:
                logger.info(f"Extracted {len(pages)} pages from PDF (native text)")
            
            return pages
        except Exception as e:
            logger.error(f"Failed to extract PDF: {e}")
            raise
    
    def _extract_text_from_bytes(self, pdf_bytes: bytes) -> List[str]:
        """Synchronous PDF text extraction using PyMuPDF"""
        pages = []
        try:
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_count = pdf_document.page_count
            
            total_text_length = 0
            for page_num in range(page_count):
                page = pdf_document[page_num]
                text = page.get_text("text").strip()
                total_text_length += len(text)
                if not text:
                    text = f"[Empty page {page_num + 1}]"
                pages.append(text)
            
            pdf_document.close()
            
            # Check if OCR needed
            avg_chars_per_page = total_text_length / page_count if page_count > 0 else 0
            from app.config import settings
            ocr_threshold = getattr(settings, 'OCR_CHARS_PER_PAGE_THRESHOLD', 100)
            
            if avg_chars_per_page < ocr_threshold:
                logger.warning(
                    f"Very little text extracted ({avg_chars_per_page:.0f} chars/page, threshold: {ocr_threshold}). "
                    f"This appears to be a scanned/image-based PDF."
                )
                
                if OCR_AVAILABLE:
                    logger.info(f"Attempting OCR extraction with {get_ocr_method_name()}...")
                    # Need to run OCR in async context, so return marker for async processing
                    # We'll handle this in the async wrapper
                    return None  # Signal that OCR is needed
                else:
                    logger.warning("OCR not available. Install AWS SDK + credentials or Tesseract (pip install pytesseract pdf2image).")
            
            return pages
        except Exception as e:
            logger.error(f"PDF text extraction failed: {e}")
            raise
    
    def create_sliding_windows(self, pages: List[str]) -> List[PDFWindow]:
        """Create overlapping windows from pages"""
        total_pages = len(pages)
        
        windows = []
        window_id = 0
        start_idx = 0
        
        while start_idx < total_pages:
            end_idx = min(start_idx + self.window_size, total_pages)
            window_pages = pages[start_idx:end_idx]
            window = PDFWindow(window_id, start_idx, end_idx - 1, window_pages, total_pages)
            windows.append(window)
            
            stride = self.window_size - self.window_overlap
            start_idx += stride
            window_id += 1
            
            if end_idx >= total_pages:
                break
        
        logger.info(f"Created {len(windows)} windows (size={self.window_size}, overlap={self.window_overlap}, total_pages={total_pages})")
        return windows
    
    async def extract_and_window(self, pdf_bytes: bytes, filename: str = "upload.pdf"):
        """Complete extraction and windowing pipeline"""
        pages = await self.extract_pages_from_bytes(pdf_bytes, filename)
        windows = self.create_sliding_windows(pages)
        metadata = {
            'total_pages': len(pages),
            'total_windows': len(windows),
            'window_size': self.window_size,
            'overlap': self.window_overlap,
            'avg_chars_per_page': sum(len(p) for p in pages) / len(pages) if pages else 0
        }
        return windows, metadata
    
    def get_window_context(self, window: PDFWindow) -> Dict:
        """Get context metadata for a window"""
        return {
            'window_id': window.window_id,
            'start_page': window.start_page + 1,  # 1-based for display
            'end_page': window.end_page + 1,      # 1-based for display
            'total_pages': window.total_pages,
            'is_first_window': window.window_id == 0,
            'is_last_window': window.end_page == window.total_pages - 1
        }
