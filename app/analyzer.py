import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List
import logging
from app.models import (
    LeaseInfo, AnalysisResult, SearchStrategy, AnalysisMetrics,
    ComparisonSummary, ModelComparison, LeaseLocation,
    CategorizedAnalysisResult
)
from app.pdf_parser import PDFParser
from app.web_search import WebSearcher
from app.bedrock_client import BedrockClient
from app.config import settings

logger = logging.getLogger(__name__)


class LeaseAnalyzer:
    """Main analyzer coordinating PDF extraction, search, and AI analysis"""
    
    def __init__(self):
        self.pdf_parser = PDFParser()
        self.web_searcher = WebSearcher()
        self.bedrock_client = BedrockClient()
        self.executor = ThreadPoolExecutor(max_workers=5)
    
    @staticmethod
    def extract_location(lease_info: LeaseInfo) -> LeaseLocation:
        """
        Extract and format lease location from LeaseInfo
        
        Args:
            lease_info: Extracted lease information
            
        Returns:
            LeaseLocation with formatted location string
        """
        # Build full location string
        parts = []
        if lease_info.city:
            parts.append(lease_info.city)
        if lease_info.state:
            parts.append(lease_info.state)
        
        full_location = ", ".join(parts) if parts else "Location not specified"
        
        if lease_info.county:
            full_location += f" ({lease_info.county} County)"
        
        return LeaseLocation(
            address=lease_info.address,
            city=lease_info.city,
            state=lease_info.state,
            county=lease_info.county,
            full_location=full_location
        )
    
    def analyze_single(
        self,
        pdf_bytes: bytes,
        model_name: str,
        search_strategy: SearchStrategy
    ) -> AnalysisResult:
        """
        Analyze lease with a single model and search strategy
        
        Args:
            pdf_bytes: PDF file content
            model_name: Model to use for analysis
            search_strategy: Search strategy to use
            
        Returns:
            AnalysisResult with violations and metrics
        """
        try:
            # Extract lease info from PDF
            lease_info = self.pdf_parser.extract_lease_info(pdf_bytes)
            
            # All models now use native web search by default
            # DuckDuckGo search is only used when search_strategy is DUCKDUCKGO_SEARCH
            use_duckduckgo = (search_strategy == SearchStrategy.DUCKDUCKGO_SEARCH)
            
            # Get search results if using DuckDuckGo
            search_results = None
            if use_duckduckgo:
                location = {
                    "city": lease_info.city,
                    "state": lease_info.state,
                    "county": lease_info.county
                }
                
                # Extract legal topics from lease
                topics = self.web_searcher.extract_legal_topics(lease_info.full_text)
                
                # Search for each topic
                all_results = []
                for topic in topics[:5]:  # Limit to top 5 topics
                    topic_results = self.web_searcher.search_gov_laws(
                        topic,
                        location,
                        max_results=3
                    )
                    all_results.extend(topic_results)
                
                search_results = all_results
            
            # Analyze with AI model
            # use_native_search=True means the model will search the web itself
            # use_native_search=False means we provide DuckDuckGo search results
            # Model now extracts location from lease text
            violations, metrics, extracted_location = self.bedrock_client.analyze_lease_with_search(
                model_name=model_name,
                lease_info=lease_info,
                search_results=search_results,
                use_native_search=not use_duckduckgo
            )
            
            return AnalysisResult(
                model_name=model_name,
                search_strategy=search_strategy,
                lease_info=lease_info,
                violations=violations,
                metrics=metrics,
                error=None
            )
        
        except Exception as e:
            logger.error(f"Error in analyze_single: {str(e)}")
            
            # Return error result
            # Create empty metrics for error case
            empty_metrics = AnalysisMetrics(
                model_name=model_name,
                search_strategy=search_strategy,
                total_time_seconds=0.0,
                cost_usd=0.0,
                gov_citations_count=0,
                total_citations_count=0,
                violations_found=0,
                avg_confidence_score=0.0,
                has_law_references=False,
                tokens_used={"prompt": 0, "completion": 0, "total": 0}
            )
            
            return AnalysisResult(
                model_name=model_name,
                search_strategy=search_strategy,
                lease_info=LeaseInfo(full_text=""),
                violations=[],
                metrics=empty_metrics,
                error=str(e)
            )
    
    async def analyze_compare(self, pdf_bytes: bytes) -> List[AnalysisResult]:
        """
        Analyze lease with all available models using native web search
        
        All models are instructed to search the web for relevant laws.
        
        Args:
            pdf_bytes: PDF file content
            
        Returns:
            List of AnalysisResult for each model
        """
        tasks = []
        
        # All models use native search (they search the web themselves)
        for model in settings.ALL_MODELS:
            task = asyncio.get_event_loop().run_in_executor(
                self.executor,
                self.analyze_single,
                pdf_bytes,
                model,
                SearchStrategy.NATIVE_SEARCH
            )
            tasks.append(task)
        
        # Run all analyses in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = []
        for result in results:
            if isinstance(result, AnalysisResult):
                valid_results.append(result)
            else:
                logger.error(f"Analysis task failed: {result}")
        
        return valid_results
    
    @staticmethod
    def generate_comparison_summary(results: List[AnalysisResult]) -> ComparisonSummary:
        """
        Generate a human-readable comparison summary from analysis results
        
        Args:
            results: List of AnalysisResult objects
            
        Returns:
            ComparisonSummary with rankings and recommendations
        """
        # Filter valid results (no errors)
        valid_results = [r for r in results if r.metrics and not r.error]
        failed_results = [r for r in results if r.error]
        
        if not valid_results:
            # Return empty summary if no valid results
            return ComparisonSummary(
                total_models=len(results),
                successful_analyses=0,
                failed_analyses=len(results),
                cheapest_model="N/A",
                most_expensive_model="N/A",
                avg_cost=0.0,
                cost_range="N/A",
                fastest_model="N/A",
                slowest_model="N/A",
                avg_time=0.0,
                time_range="N/A",
                most_citations_model="N/A",
                most_violations_model="N/A",
                highest_confidence_model="N/A",
                models_by_cost=[],
                models_by_time=[],
                models_by_citations=[],
                models_by_overall_score=[],
                recommended_for_accuracy="N/A",
                recommended_for_budget="N/A",
                recommended_for_speed="N/A",
                recommended_overall="N/A"
            )
        
        # Sort by different metrics
        sorted_by_cost = sorted(valid_results, key=lambda x: x.metrics.cost_usd)
        sorted_by_time = sorted(valid_results, key=lambda x: x.metrics.total_time_seconds)
        sorted_by_citations = sorted(valid_results, key=lambda x: x.metrics.gov_citations_count, reverse=True)
        
        # Calculate overall score (weighted)
        def calc_overall_score(result: AnalysisResult) -> float:
            # Normalize metrics (0-1 scale)
            max_cost = max(r.metrics.cost_usd for r in valid_results)
            max_time = max(r.metrics.total_time_seconds for r in valid_results)
            max_citations = max(r.metrics.gov_citations_count for r in valid_results) or 1
            
            cost_score = 1 - (result.metrics.cost_usd / max_cost if max_cost > 0 else 0)
            time_score = 1 - (result.metrics.total_time_seconds / max_time if max_time > 0 else 0)
            citation_score = result.metrics.gov_citations_count / max_citations
            confidence_score = result.metrics.avg_confidence_score
            
            # Weighted combination: citations (40%), confidence (30%), cost (20%), time (10%)
            return (citation_score * 0.4 + confidence_score * 0.3 + 
                    cost_score * 0.2 + time_score * 0.1)
        
        sorted_by_overall = sorted(valid_results, key=calc_overall_score, reverse=True)
        
        # Create rankings
        cost_ranks = {r.model_name: i+1 for i, r in enumerate(sorted_by_cost)}
        time_ranks = {r.model_name: i+1 for i, r in enumerate(sorted_by_time)}
        citation_ranks = {r.model_name: i+1 for i, r in enumerate(sorted_by_citations)}
        overall_ranks = {r.model_name: i+1 for i, r in enumerate(sorted_by_overall)}
        
        # Build ModelComparison objects
        def build_comparison(result: AnalysisResult) -> ModelComparison:
            return ModelComparison(
                model_name=result.model_name,
                provider=result.model_name.split('/')[0],
                search_strategy=result.search_strategy.value,
                cost_usd=result.metrics.cost_usd,
                time_seconds=result.metrics.total_time_seconds,
                violations_found=result.metrics.violations_found,
                gov_citations=result.metrics.gov_citations_count,
                total_citations=result.metrics.total_citations_count,
                avg_confidence=result.metrics.avg_confidence_score,
                cost_rank=cost_ranks[result.model_name],
                time_rank=time_ranks[result.model_name],
                citation_rank=citation_ranks[result.model_name],
                overall_rank=overall_ranks[result.model_name],
                success=True,
                error_message=None
            )
        
        # Add failed models
        failed_comparisons = [
            ModelComparison(
                model_name=r.model_name,
                provider=r.model_name.split('/')[0],
                search_strategy=r.search_strategy.value,
                cost_usd=0.0,
                time_seconds=0.0,
                violations_found=0,
                gov_citations=0,
                total_citations=0,
                avg_confidence=0.0,
                cost_rank=len(valid_results) + 1,
                time_rank=len(valid_results) + 1,
                citation_rank=len(valid_results) + 1,
                overall_rank=len(valid_results) + 1,
                success=False,
                error_message=r.error
            )
            for r in failed_results
        ]
        
        models_by_cost = [build_comparison(r) for r in sorted_by_cost] + failed_comparisons
        models_by_time = [build_comparison(r) for r in sorted_by_time] + failed_comparisons
        models_by_citations = [build_comparison(r) for r in sorted_by_citations] + failed_comparisons
        models_by_overall = [build_comparison(r) for r in sorted_by_overall] + failed_comparisons
        
        # Calculate stats
        avg_cost = sum(r.metrics.cost_usd for r in valid_results) / len(valid_results)
        avg_time = sum(r.metrics.total_time_seconds for r in valid_results) / len(valid_results)
        
        min_cost = sorted_by_cost[0].metrics.cost_usd
        max_cost = sorted_by_cost[-1].metrics.cost_usd
        
        min_time = sorted_by_time[0].metrics.total_time_seconds
        max_time = sorted_by_time[-1].metrics.total_time_seconds
        
        # Best by confidence
        sorted_by_confidence = sorted(valid_results, key=lambda x: x.metrics.avg_confidence_score, reverse=True)
        
        # Most violations
        sorted_by_violations = sorted(valid_results, key=lambda x: x.metrics.violations_found, reverse=True)
        
        return ComparisonSummary(
            total_models=len(results),
            successful_analyses=len(valid_results),
            failed_analyses=len(failed_results),
            
            cheapest_model=f"{sorted_by_cost[0].model_name} (${sorted_by_cost[0].metrics.cost_usd:.4f})",
            most_expensive_model=f"{sorted_by_cost[-1].model_name} (${sorted_by_cost[-1].metrics.cost_usd:.4f})",
            avg_cost=avg_cost,
            cost_range=f"${min_cost:.4f} - ${max_cost:.4f}",
            
            fastest_model=f"{sorted_by_time[0].model_name} ({sorted_by_time[0].metrics.total_time_seconds:.1f}s)",
            slowest_model=f"{sorted_by_time[-1].model_name} ({sorted_by_time[-1].metrics.total_time_seconds:.1f}s)",
            avg_time=avg_time,
            time_range=f"{min_time:.1f}s - {max_time:.1f}s",
            
            most_citations_model=f"{sorted_by_citations[0].model_name} ({sorted_by_citations[0].metrics.gov_citations_count} .gov)",
            most_violations_model=f"{sorted_by_violations[0].model_name} ({sorted_by_violations[0].metrics.violations_found} violations)",
            highest_confidence_model=f"{sorted_by_confidence[0].model_name} ({sorted_by_confidence[0].metrics.avg_confidence_score:.2f})",
            
            models_by_cost=models_by_cost,
            models_by_time=models_by_time,
            models_by_citations=models_by_citations,
            models_by_overall_score=models_by_overall,
            
            recommended_for_accuracy=sorted_by_citations[0].model_name,
            recommended_for_budget=sorted_by_cost[0].model_name,
            recommended_for_speed=sorted_by_time[0].model_name,
            recommended_overall=sorted_by_overall[0].model_name
        )
        
        return valid_results
    
    def analyze_categorized(self, pdf_bytes: bytes) -> CategorizedAnalysisResult:
        """
        Analyze lease with Mistral Medium 3.1 and categorize violations
        
        Args:
            pdf_bytes: PDF file content
            
        Returns:
            CategorizedAnalysisResult with violations organized by category
        """
        try:
            logger.info("\n" + "="*80)
            logger.info("STARTING CATEGORIZED ANALYSIS")
            logger.info("="*80)
            
            # Extract lease info from PDF
            lease_info = self.pdf_parser.extract_lease_info(pdf_bytes)
            
            logger.info("\n" + "="*80)
            logger.info("CALLING AI FOR ANALYSIS (Claude 3.5 Haiku / Llama 70B)")
            logger.info("AI will: 1) Extract location, 2) Search .gov laws, 3) Find violations")
            logger.info("="*80)
            
            # Analyze with Mistral Medium 3.1 (categorized)
            violations_by_category, metrics, extracted_location = self.bedrock_client.analyze_lease_categorized(
                lease_info=lease_info
            )
            
            # Update lease_info with extracted data from AI
            logger.info("\n" + "="*80)
            logger.info("MERGING AI-EXTRACTED LOCATION DATA")
            if extracted_location:
                logger.info(f"AI extracted location: {extracted_location.get('city')}, {extracted_location.get('state')} ({extracted_location.get('county')} County)")
                logger.info(f"Address: {extracted_location.get('address')}")
                logger.info(f"Landlord: {extracted_location.get('landlord')}")
                logger.info(f"Tenant: {extracted_location.get('tenant')}")
                logger.info(f"Rent: {extracted_location.get('rent_amount')}, Deposit: {extracted_location.get('security_deposit')}, Duration: {extracted_location.get('lease_duration')}")
                
                lease_info.address = extracted_location.get("address") or lease_info.address
                lease_info.city = extracted_location.get("city") or lease_info.city
                lease_info.state = extracted_location.get("state") or lease_info.state
                lease_info.county = extracted_location.get("county") or lease_info.county
                lease_info.landlord = extracted_location.get("landlord") or lease_info.landlord
                lease_info.tenant = extracted_location.get("tenant") or lease_info.tenant
                lease_info.rent_amount = extracted_location.get("rent_amount") or lease_info.rent_amount
                lease_info.security_deposit = extracted_location.get("security_deposit") or lease_info.security_deposit
                lease_info.lease_duration = extracted_location.get("lease_duration") or lease_info.lease_duration
            else:
                logger.warning("No location data extracted by AI")
            logger.info("="*80)
            
            # Count total violations
            total_violations = sum(len(violations) for violations in violations_by_category.values())
            
            logger.info("\n" + "="*80)
            logger.info("ANALYSIS COMPLETE - RESULTS SUMMARY")
            logger.info(f"Total violations found: {total_violations}")
            for category, violations in violations_by_category.items():
                if violations:
                    logger.info(f"  - {category}: {len(violations)} violation(s)")
            logger.info(f"Analysis time: {metrics.total_time_seconds:.2f}s")
            logger.info(f"Citations: {metrics.total_citations_count} total, {metrics.gov_citations_count} .gov")
            logger.info("="*80 + "\n")
            
            # Remove full_text from response to reduce payload size
            lease_info.full_text = ""
            
            return CategorizedAnalysisResult(
                model_name="mistralai/mistral-medium-3.1",
                search_strategy=SearchStrategy.NATIVE_SEARCH,
                lease_info=lease_info,
                violations_by_category=violations_by_category,
                total_violations=total_violations,
                metrics=metrics,
                error=None
            )
        
        except Exception as e:
            logger.error(f"Error in analyze_categorized: {str(e)}")
            
            # Return error result
            empty_metrics = AnalysisMetrics(
                model_name="mistralai/mistral-medium-3.1",
                search_strategy=SearchStrategy.NATIVE_SEARCH,
                total_time_seconds=0.0,
                cost_usd=0.0,
                gov_citations_count=0,
                total_citations_count=0,
                violations_found=0,
                avg_confidence_score=0.0,
                has_law_references=False,
                tokens_used={"prompt": 0, "completion": 0, "total": 0}
            )
            
            return CategorizedAnalysisResult(
                model_name="mistralai/mistral-medium-3.1",
                search_strategy=SearchStrategy.NATIVE_SEARCH,
                lease_info=LeaseInfo(full_text=""),
                violations_by_category={
                    "rent_increase": [],
                    "tenant_owner_rights": [],
                    "fair_housing_laws": [],
                    "licensing": [],
                    "others": []
                },
                total_violations=0,
                metrics=empty_metrics,
                error=str(e)
            )

