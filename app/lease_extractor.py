"""
Main lease extractor with async parallel processing
"""
import asyncio
import logging
import time
import copy
from typing import Dict, Any, List, Optional
from pydantic import ValidationError

from app.lease_bedrock_client import LeaseBedrockClient
from app.lease_pdf_processor import LeasePDFProcessor, PDFWindow
from app.lease_prompts import build_extraction_prompt
from app.lease_merger import merge_window_results
from app.lease_schemas import LeaseData, ExtractionMetadata, LeaseExtractionResponse

logger = logging.getLogger(__name__)


class LeaseExtractor:
    """Production-grade lease extraction with async parallel processing"""
    
    def __init__(self, region: str, access_key: Optional[str], secret_key: Optional[str],
                 model_id: str, temperature: float, max_tokens: int, 
                 max_concurrent: int, timeout: int,
                 window_size: int, window_overlap: int):
        self.bedrock_client = LeaseBedrockClient(
            region=region,
            max_concurrent=max_concurrent,
            access_key=access_key,
            secret_key=secret_key
        )
        self.pdf_processor = LeasePDFProcessor(
            window_size=window_size,
            window_overlap=window_overlap
        )
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        logger.info("LeaseExtractor initialized")
    
    async def extract_lease(self, pdf_bytes: bytes, filename: str = "upload.pdf"):
        """Complete lease extraction pipeline"""
        start_time = time.time()
        logger.info(f"Starting extraction: {filename}")
        
        try:
            # Step 1: Extract & window PDF
            windows, pdf_metadata = await self.pdf_processor.extract_and_window(
                pdf_bytes=pdf_bytes, filename=filename
            )
            logger.info(f"Created {len(windows)} windows from {pdf_metadata['total_pages']} pages")
            
            # Step 2: Extract from all windows in parallel
            window_results = await self.parallel_extract(windows)
            
            # Step 3: Merge & deduplicate
            merged_data, merge_metadata = merge_window_results(window_results)
            
            # Step 4: Validate schema
            try:
                lease_data = LeaseData(**merged_data)
            except ValidationError as e:
                logger.warning(f"Validation error, attempting to clean: {e}")
                cleaned_data = self._clean_validation_errors(merged_data, e)
                try:
                    lease_data = LeaseData(**cleaned_data)
                except ValidationError:
                    # Last resort - construct model
                    lease_data = LeaseData.model_construct(**cleaned_data)
                    logger.warning("Used model_construct to bypass validation")
            
            # Step 5: Build metadata & summary
            processing_time = time.time() - start_time
            
            # Calculate token usage
            total_input_tokens = sum(r.get('usage', {}).get('input_tokens', 0) for r in window_results)
            total_output_tokens = sum(r.get('usage', {}).get('output_tokens', 0) for r in window_results)
            
            metadata = ExtractionMetadata(
                processing_time=round(processing_time, 2),
                total_windows=len(windows),
                total_pages=pdf_metadata['total_pages'],
                confidence_scores=merge_metadata.get('confidence_scores', {}),
                conflicts_found=merge_metadata.get('conflicts_found', False),
                conflict_details=merge_metadata.get('conflict_details', []),
                token_usage={
                    'input_tokens': total_input_tokens,
                    'output_tokens': total_output_tokens,
                    'total_tokens': total_input_tokens + total_output_tokens
                },
                window_timings=[
                    {
                        'window_id': r['window_id'],
                        'duration': r['duration'],
                        'success': 'error' not in r
                    }
                    for r in window_results
                ]
            )
            
            summary = self._generate_summary(lease_data, metadata)
            logger.info(f"Extraction complete: {processing_time:.2f}s")
            
            return LeaseExtractionResponse(data=lease_data, metadata=metadata, summary=summary)
        except Exception as e:
            logger.error(f"Extraction failed: {e}", exc_info=True)
            raise
    
    async def parallel_extract(self, windows: List[PDFWindow]) -> List[Dict[str, Any]]:
        """
        Extract data from all windows in parallel using asyncio.gather
        
        Args:
            windows: List of PDFWindow objects
            
        Returns:
            List of extraction results
        """
        logger.info(f"Starting parallel extraction for {len(windows)} windows")
        
        # Create tasks for all windows
        tasks = [
            self.extract_from_window(window)
            for window in windows
        ]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle errors
        processed_results = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Window {idx} extraction failed: {result}")
                # Add empty result for failed window
                processed_results.append({
                    'window_id': idx,
                    'data': {},
                    'error': str(result),
                    'duration': 0,
                    'usage': {'input_tokens': 0, 'output_tokens': 0}
                })
            else:
                processed_results.append(result)
        
        # Log summary
        successful = sum(1 for r in processed_results if not r.get('error'))
        failed = len(processed_results) - successful
        
        logger.info(
            f"Parallel extraction complete: "
            f"{successful} successful, {failed} failed"
        )
        
        return processed_results
    
    async def extract_from_window(self, window: PDFWindow) -> Dict[str, Any]:
        """
        Extract data from a single window
        
        Args:
            window: PDFWindow object
            
        Returns:
            Extraction result with data and metadata
        """
        start_time = time.time()
        
        logger.debug(f"Extracting from {window}")
        
        try:
            # Get window context
            context = self.pdf_processor.get_window_context(window)
            
            # Build extraction prompt
            prompt = build_extraction_prompt(window.text, context)
            
            # Log prompt length for debugging
            logger.info(
                f"Window {window.window_id}: Sending {len(prompt)} chars, "
                f"PDF text length: {len(window.text)} chars"
            )
            
            # Invoke Bedrock
            response = await self.bedrock_client.invoke_model_async(
                prompt=prompt,
                model_id=self.model_id,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.timeout
            )
            
            # Parse JSON from response (with retry on failure)
            try:
                extracted_data = await self.bedrock_client.extract_json_from_response(response)
            except ValueError as json_error:
                # JSON parsing failed - retry once with stricter instructions
                logger.warning(f"Window {window.window_id}: JSON parse failed, retrying with stricter prompt")
                
                strict_prompt = prompt + "\n\n⚠️ CRITICAL: Previous response had formatting issues. Output MUST be ONLY valid JSON. Start with { and end with }. Absolutely NO explanatory text before or after the JSON."
                
                response = await self.bedrock_client.invoke_model_async(
                    prompt=strict_prompt,
                    model_id=self.model_id,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout
                )
                
                try:
                    extracted_data = await self.bedrock_client.extract_json_from_response(response)
                    logger.info(f"Window {window.window_id}: Retry successful")
                except ValueError:
                    logger.error(f"Window {window.window_id}: Retry also failed - {json_error}")
                    raise
            
            # Debug: Log extracted data summary
            logger.info(
                f"Window {window.window_id} extracted: "
                f"{len(extracted_data.get('utility_responsibilities', []))} utilities, "
                f"{len(extracted_data.get('additional_fees', []))} fees, "
                f"rent={extracted_data.get('rent_and_deposits', {}).get('monthly_base_rent')}"
            )
            
            duration = time.time() - start_time
            
            logger.debug(
                f"Window {window.window_id} extracted in {duration:.2f}s "
                f"({response['usage']['input_tokens']}+{response['usage']['output_tokens']} tokens)"
            )
            
            return {
                'window_id': window.window_id,
                'data': extracted_data,
                'duration': round(duration, 2),
                'usage': response['usage'],
                'stop_reason': response.get('stop_reason')
            }
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Window {window.window_id} extraction failed: {e}")
            
            return {
                'window_id': window.window_id,
                'data': {},
                'error': str(e),
                'duration': round(duration, 2),
                'usage': {'input_tokens': 0, 'output_tokens': 0}
            }
    
    def _clean_validation_errors(
        self,
        data: Dict[str, Any],
        error: ValidationError
    ) -> Dict[str, Any]:
        """
        Clean data to remove fields causing validation errors
        
        Args:
            data: Original merged data
            error: Pydantic ValidationError
            
        Returns:
            Cleaned data dict
        """
        cleaned = copy.deepcopy(data)
        
        # Collect items to remove (array index errors)
        items_to_remove = []  # [(field_name, index), ...]
        
        # Parse error locations
        for err in error.errors():
            loc = err['loc']
            error_type = err['type']
            
            logger.debug(f"Validation error at {'.'.join(map(str, loc))}: {error_type}")
            
            # If error is in an array item, mark entire item for removal
            if len(loc) >= 2 and isinstance(loc[1], int):
                field_name = loc[0]
                index = loc[1]
                items_to_remove.append((field_name, index))
                logger.debug(f"Marking {field_name}[{index}] for removal")
            # If error is in top-level field, try setting to None
            elif len(loc) == 1:
                field_name = loc[0]
                if field_name in cleaned:
                    cleaned[field_name] = None
                    logger.debug(f"Set {field_name} to None")
        
        # Remove invalid array items (in reverse order to maintain indices)
        for field_name, index in sorted(set(items_to_remove), key=lambda x: x[1], reverse=True):
            if field_name in cleaned and isinstance(cleaned[field_name], list):
                if index < len(cleaned[field_name]):
                    removed = cleaned[field_name].pop(index)
                    logger.info(f"Removed invalid item from {field_name}[{index}]: {removed}")
        
        return cleaned
    
    def _generate_summary(
        self,
        lease_data: LeaseData,
        metadata: ExtractionMetadata
    ) -> str:
        """
        Generate human-readable extraction summary
        
        Args:
            lease_data: Extracted lease data
            metadata: Extraction metadata
            
        Returns:
            Summary string
        """
        lines = []
        
        # Basic info
        lines.append(f"Lease extraction completed in {metadata.processing_time}s")
        lines.append(f"Processed {metadata.total_pages} pages in {metadata.total_windows} windows")
        
        # Token usage
        tokens = metadata.token_usage
        lines.append(
            f"Tokens used: {tokens.get('input_tokens', 0)} input + "
            f"{tokens.get('output_tokens', 0)} output = {tokens.get('total_tokens', 0)} total"
        )
        
        # Data summary
        if lease_data.term:
            term = lease_data.term
            start_date = getattr(term, 'lease_start_date', None)
            end_date = getattr(term, 'lease_end_date', None)
            if start_date and end_date:
                lines.append(f"Term: {start_date} to {end_date}")
        
        if lease_data.rent_and_deposits:
            rent = lease_data.rent_and_deposits
            monthly_rent = getattr(rent, 'monthly_base_rent', None)
            security = getattr(rent, 'security_deposit', None)
            if monthly_rent:
                lines.append(f"Monthly rent: ${monthly_rent:,.2f}")
            if security:
                lines.append(f"Security deposit: ${security:,.2f}")
        
        # Counts
        counts = []
        if lease_data.utility_responsibilities:
            counts.append(f"{len(lease_data.utility_responsibilities)} utilities")
        if lease_data.common_area_maintenance:
            counts.append(f"{len(lease_data.common_area_maintenance)} CAM items")
        if lease_data.additional_fees:
            counts.append(f"{len(lease_data.additional_fees)} additional fees")
        if lease_data.rent_increase_schedule:
            counts.append(f"{len(lease_data.rent_increase_schedule)} rent increases")
        
        if counts:
            lines.append(f"Extracted: {', '.join(counts)}")
        
        # Warnings
        if metadata.conflicts_found:
            lines.append(
                f"⚠️ {len(metadata.conflict_details)} conflicts detected - review recommended"
            )
        
        return "\n".join(lines)
    
    async def close(self):
        """Cleanup resources"""
        await self.bedrock_client.close()
