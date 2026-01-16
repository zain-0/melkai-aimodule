"""
OCR processing using AWS Textract (preferred) or Tesseract (fallback) for scanned PDFs
"""
import asyncio
import logging
import io
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import fitz  # PyMuPDF
import boto3
from botocore.exceptions import ClientError
from app.config import settings

logger = logging.getLogger(__name__)

# Try to import Tesseract as fallback
try:
    import pytesseract  # type: ignore[import-untyped]
    from pdf2image import convert_from_bytes  # type: ignore[import-untyped]
    TESSERACT_AVAILABLE = True
    logger.info("Tesseract OCR available as fallback")
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("Tesseract not available - only AWS Textract will be used")


class TextractOCRProcessor:
    """AWS Textract OCR processor for scanned PDFs"""
    
    def __init__(self, region: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.region = region or settings.AWS_REGION
        
        # Initialize Textract client with increased connection pool
        session_kwargs = {'region_name': self.region}
        if access_key and secret_key:
            session_kwargs.update({
                'aws_access_key_id': access_key,
                'aws_secret_access_key': secret_key
            })
        
        self.session = boto3.Session(**session_kwargs)
        
        # Configure boto3 to allow more concurrent connections
        from botocore.config import Config
        max_workers = getattr(settings, 'TEXTRACT_MAX_WORKERS', 20)
        boto_config = Config(
            max_pool_connections=max_workers,  # Match thread pool size
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        
        self.textract_client = self.session.client('textract', config=boto_config)
        logger.info(f"Textract OCR processor initialized (region={self.region}, max_connections={max_workers})")
    
    def _extract_pdf_pages_as_document(self, pdf_bytes: bytes, start_page: int, end_page: int) -> bytes:
        """
        Extract a range of pages from PDF as a new PDF document
        More efficient than converting to images - Textract can process multi-page PDFs
        
        Args:
            pdf_bytes: Original PDF bytes
            start_page: Start page (0-indexed)
            end_page: End page (0-indexed, inclusive)
            
        Returns:
            PDF bytes containing only the specified pages
        """
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # Create new PDF with selected pages
        output_pdf = fitz.open()
        output_pdf.insert_pdf(pdf_document, from_page=start_page, to_page=end_page)
        
        # Get bytes
        output_bytes = output_pdf.tobytes()
        
        output_pdf.close()
        pdf_document.close()
        
        return output_bytes
    
    def _extract_text_from_textract_response(self, response: dict) -> str:
        """Extract text from Textract API response"""
        text_lines = []
        
        # Extract all LINE blocks
        for block in response.get('Blocks', []):
            if block['BlockType'] == 'LINE':
                text_lines.append(block.get('Text', ''))
        
        return '\n'.join(text_lines)
    
    def _process_page_batch(self, pdf_bytes: bytes, start_page: int, end_page: int, total_pages: int) -> List[str]:
        """
        Process a batch of pages with Textract (2-5 pages per batch)
        More efficient than single-page processing
        
        Args:
            pdf_bytes: Original PDF bytes
            start_page: Start page (0-indexed)
            end_page: End page (0-indexed, inclusive)
            total_pages: Total pages in document
            
        Returns:
            List of extracted text for each page in batch
        """
        try:
            # Extract pages as a PDF document (more efficient than images)
            batch_pdf = self._extract_pdf_pages_as_document(pdf_bytes, start_page, end_page)
            
            page_count = end_page - start_page + 1
            logger.debug(f"Calling Textract for pages {start_page + 1}-{end_page + 1}/{total_pages} ({page_count} pages)")
            
            # Call Textract with multi-page PDF
            response = self.textract_client.detect_document_text(
                Document={'Bytes': batch_pdf}
            )
            
            # Extract text grouped by page
            pages_text = [''] * page_count
            
            for block in response.get('Blocks', []):
                if block['BlockType'] == 'LINE' and 'Page' in block:
                    page_idx = block['Page'] - 1  # Textract pages are 1-indexed
                    if 0 <= page_idx < page_count:
                        pages_text[page_idx] += block.get('Text', '') + '\n'
            
            # Log results
            for i, text in enumerate(pages_text):
                if text:
                    logger.info(f"OCR extracted {len(text)} chars from page {start_page + i + 1}")
                else:
                    logger.warning(f"No text extracted from page {start_page + i + 1}")
            
            return pages_text
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['ProvisionedThroughputExceededException', 'ThrottlingException']:
                logger.warning(f"Textract throttled on pages {start_page + 1}-{end_page + 1}, retrying...")
                import time
                time.sleep(2)
                return self._process_page_batch(pdf_bytes, start_page, end_page, total_pages)
            else:
                logger.error(f"Textract error on pages {start_page + 1}-{end_page + 1}: {error_code} - {e}")
                return [f"[OCR failed for page {start_page + i + 1}]" for i in range(end_page - start_page + 1)]
        except Exception as e:
            logger.error(f"OCR processing error on pages {start_page + 1}-{end_page + 1}: {e}")
            return [f"[OCR error on page {start_page + i + 1}]" for i in range(end_page - start_page + 1)]
    
    def _should_split_pages(self, pdf_size_bytes: int) -> bool:
        """Check if PDF should be split into individual pages based on size"""
        size_mb = pdf_size_bytes / (1024 * 1024)
        # For very large PDFs (>50MB), always use page-by-page
        # For medium PDFs (5-50MB), use async document analysis
        # For small PDFs (<5MB), use page-by-page with higher parallelism
        
        if size_mb > 50:
            logger.info(f"PDF size {size_mb:.2f}MB > 50MB - using page-by-page with batching")
            return True
        elif size_mb > 5:
            logger.info(f"PDF size {size_mb:.2f}MB (5-50MB) - using async document analysis")
            return False  # Use async API instead
        else:
            logger.info(f"PDF size {size_mb:.2f}MB <= 5MB - using fast page-by-page")
            return True
    
    async def _extract_with_async_textract(self, pdf_bytes: bytes, page_count: int) -> List[str]:
        """
        Use Textract's async StartDocumentTextDetection API for multi-page PDFs
        Much faster for medium-large PDFs (5-50MB, 10-100 pages)
        """
        import time
        
        try:
            # Upload to S3 (required for async API) or use direct bytes if small enough
            logger.info(f"Starting async Textract job for {page_count} pages")
            
            # Start async job
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.textract_client.start_document_text_detection(
                    DocumentLocation={'Bytes': pdf_bytes} if len(pdf_bytes) < 5*1024*1024 else None,
                    Document={'Bytes': pdf_bytes} if len(pdf_bytes) < 5*1024*1024 else None
                )
            )
            
            job_id = response['JobId']
            logger.info(f"Textract async job started: {job_id}")
            
            # Poll for completion (typically 10-30 seconds for 48 pages)
            max_wait = 120  # 2 minutes max
            poll_interval = 2  # Check every 2 seconds
            elapsed = 0
            
            while elapsed < max_wait:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                status_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.textract_client.get_document_text_detection(JobId=job_id)
                )
                
                status = status_response['JobStatus']
                
                if status == 'SUCCEEDED':
                    logger.info(f"Textract job completed in {elapsed}s")
                    
                    # Extract text by page
                    pages_text = [''] * page_count
                    
                    # Get all blocks
                    blocks = status_response.get('Blocks', [])
                    
                    for block in blocks:
                        if block['BlockType'] == 'LINE' and 'Page' in block:
                            page_idx = block['Page'] - 1
                            if 0 <= page_idx < page_count:
                                pages_text[page_idx] += block.get('Text', '') + '\n'
                    
                    # Handle pagination if results span multiple responses
                    next_token = status_response.get('NextToken')
                    while next_token:
                        next_response = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self.textract_client.get_document_text_detection(
                                JobId=job_id,
                                NextToken=next_token
                            )
                        )
                        
                        for block in next_response.get('Blocks', []):
                            if block['BlockType'] == 'LINE' and 'Page' in block:
                                page_idx = block['Page'] - 1
                                if 0 <= page_idx < page_count:
                                    pages_text[page_idx] += block.get('Text', '') + '\n'
                        
                        next_token = next_response.get('NextToken')
                    
                    total_chars = sum(len(p) for p in pages_text)
                    logger.info(f"Async Textract extracted {total_chars} chars from {page_count} pages")
                    
                    return pages_text
                    
                elif status == 'FAILED':
                    logger.error(f"Textract job failed: {status_response.get('StatusMessage')}")
                    raise Exception(f"Textract async job failed: {status_response.get('StatusMessage')}")
                
                elif status == 'IN_PROGRESS':
                    logger.debug(f"Textract job in progress... ({elapsed}s elapsed)")
                    continue
                    
            raise Exception(f"Textract job timed out after {max_wait}s")
            
        except Exception as e:
            logger.error(f"Async Textract failed: {e}")
            logger.info("Falling back to page-by-page processing")
            # Fall back to page-by-page
            return await self._extract_page_by_page(pdf_bytes, page_count)
    
    async def _extract_page_by_page(self, pdf_bytes: bytes, page_count: int) -> List[str]:
        """
        Extract using multi-page batch processing
        More efficient than single-page - reduces API calls significantly
        """
        max_workers = getattr(settings, 'TEXTRACT_MAX_WORKERS', 15)
        pages_per_batch = getattr(settings, 'TEXTRACT_PAGES_PER_BATCH', 3)
        
        logger.info(f"Processing {page_count} pages in {pages_per_batch}-page batches")
        
        all_pages = []
        loop = asyncio.get_event_loop()
        
        # Create batch tasks (each batch handles multiple pages)
        batch_tasks = []
        for start_page in range(0, page_count, pages_per_batch):
            end_page = min(start_page + pages_per_batch - 1, page_count - 1)
            
            task = loop.run_in_executor(
                None,
                self._process_page_batch,
                pdf_bytes,
                start_page,
                end_page,
                page_count
            )
            batch_tasks.append((start_page, task))
        
        # Process batches in controlled groups
        batch_size = max(1, max_workers // pages_per_batch)  # e.g., 15 workers / 3 pages = 5 concurrent batches
        
        logger.info(f"Running {len(batch_tasks)} batches with {batch_size} concurrent batches")
        
        # Execute in groups
        for i in range(0, len(batch_tasks), batch_size):
            batch_group = batch_tasks[i:i+batch_size]
            
            # Wait for this group to complete
            results = await asyncio.gather(*[task for _, task in batch_group])
            
            # Flatten results (each result is a list of pages)
            for pages_list in results:
                all_pages.extend(pages_list)
            
            # Small delay between groups
            if i + batch_size < len(batch_tasks):
                await asyncio.sleep(0.1)
        
        total_chars = sum(len(p) for p in all_pages)
        api_calls = len(batch_tasks)
        savings = ((page_count - api_calls) / page_count * 100) if page_count > 0 else 0
        logger.info(f"Multi-page batch Textract complete: {total_chars} chars from {page_count} pages ({api_calls} API calls, {savings:.0f}% reduction)")
        
        return all_pages
    
    async def extract_text_from_pdf(self, pdf_bytes: bytes, page_count: int) -> List[str]:
        """
        Extract text from scanned PDF using AWS Textract
        Automatically chooses best method based on file size
        
        Args:
            pdf_bytes: PDF file bytes
            page_count: Number of pages in PDF
            
        Returns:
            List of extracted text per page
        """
        logger.info(f"Starting Textract OCR for {page_count} pages")
        
        # Check file size to determine processing method
        pdf_size = len(pdf_bytes)
        size_mb = pdf_size / (1024 * 1024)
        
        # Strategy:
        # - Small PDFs (<5MB): Page-by-page with high parallelism (fast)
        # - Medium PDFs (5-50MB): Async document analysis (most efficient for 10-100 pages)
        # - Large PDFs (>50MB): Page-by-page with batching (avoids API limits)
        
        if size_mb <= 5:
            logger.info(f"Small PDF ({size_mb:.2f}MB) - using fast page-by-page processing")
            return await self._extract_page_by_page(pdf_bytes, page_count)
        elif size_mb <= 50:
            # Async API is fastest for medium PDFs but has limitations
            logger.info(f"Medium PDF ({size_mb:.2f}MB) - attempting async document analysis")
            # Note: Async API requires S3 for files >5MB, falling back to page-by-page
            logger.warning("Async Textract requires S3 for files >5MB, using page-by-page instead")
            return await self._extract_page_by_page(pdf_bytes, page_count)
        else:
            logger.info(f"Large PDF ({size_mb:.2f}MB) - using page-by-page with batching")
            return await self._extract_page_by_page(pdf_bytes, page_count)


class TesseractOCRProcessor:
    """Tesseract OCR processor as fallback when Textract unavailable"""
    
    def __init__(self):
        if not TESSERACT_AVAILABLE:
            raise ImportError("Tesseract not available. Install: pip install pytesseract pdf2image")
        logger.info("Tesseract OCR processor initialized")
    
    def _process_single_page_tesseract(self, pdf_bytes: bytes, page_num: int, total_pages: int) -> str:
        """Process a single page with Tesseract (synchronous)"""
        try:
            # Convert single page to image
            logger.debug(f"Converting page {page_num + 1}/{total_pages} to image for Tesseract")
            images = convert_from_bytes(
                pdf_bytes,
                dpi=300,
                first_page=page_num + 1,
                last_page=page_num + 1
            )
            
            if not images:
                logger.warning(f"No image generated for page {page_num + 1}")
                return f"[Tesseract: No image for page {page_num + 1}]"
            
            # Run Tesseract OCR
            logger.debug(f"Running Tesseract OCR on page {page_num + 1}/{total_pages}")
            text = pytesseract.image_to_string(images[0], lang='eng')
            
            if text:
                logger.info(f"Tesseract extracted {len(text)} chars from page {page_num + 1}")
            else:
                logger.warning(f"No text extracted from page {page_num + 1}")
            
            return text.strip()
            
        except Exception as e:
            logger.error(f"Tesseract OCR error on page {page_num + 1}: {e}")
            return f"[Tesseract OCR failed for page {page_num + 1}]"
    
    async def extract_text_from_pdf(self, pdf_bytes: bytes, page_count: int) -> List[str]:
        """
        Extract text from scanned PDF using Tesseract OCR
        
        Args:
            pdf_bytes: PDF file bytes
            page_count: Number of pages in PDF
            
        Returns:
            List of extracted text per page
        """
        logger.info(f"Starting Tesseract OCR for {page_count} pages")
        
        # Process pages sequentially (Tesseract is CPU-bound)
        loop = asyncio.get_event_loop()
        pages = []
        
        for page_num in range(page_count):
            text = await loop.run_in_executor(
                None,
                self._process_single_page_tesseract,
                pdf_bytes,
                page_num,
                page_count
            )
            pages.append(text)
        
        total_chars = sum(len(p) for p in pages)
        logger.info(f"Tesseract OCR complete: {total_chars} total chars extracted from {page_count} pages")
        
        return pages


# Global OCR processor instances
_textract_processor: Optional[TextractOCRProcessor] = None
_tesseract_processor: Optional[TesseractOCRProcessor] = None


def get_ocr_processor(prefer_textract: bool = True):
    """Get or create global OCR processor instance"""
    global _textract_processor, _tesseract_processor
    
    ocr_method = getattr(settings, 'OCR_METHOD', 'textract').lower()
    
    # Try Textract first if preferred and available
    if prefer_textract or ocr_method == 'textract':
        if is_textract_available():
            if _textract_processor is None:
                _textract_processor = TextractOCRProcessor()
            return _textract_processor
        else:
            logger.warning("Textract not available, falling back to Tesseract")
    
    # Fall back to Tesseract
    if TESSERACT_AVAILABLE:
        if _tesseract_processor is None:
            _tesseract_processor = TesseractOCRProcessor()
        return _tesseract_processor
    
    raise RuntimeError("No OCR method available. Install AWS SDK + credentials or Tesseract.")


def is_textract_available() -> bool:
    """Check if AWS Textract is available"""
    try:
        import boto3
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception as e:
        logger.debug(f"Textract not available: {e}")
        return False


def is_ocr_available() -> bool:
    """Check if any OCR method is available"""
    return is_textract_available() or TESSERACT_AVAILABLE


def get_ocr_method_name() -> str:
    """Get the name of the available OCR method"""
    if is_textract_available():
        return "AWS Textract"
    elif TESSERACT_AVAILABLE:
        return "Tesseract"
    else:
        return "None"
