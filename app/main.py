from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from enum import Enum
import logging
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from app.models import (
    AnalysisResult,
    ComparisonResult,
    ModelInfo,
    SearchStrategy,
    CategorizedAnalysisResult,
    MaintenanceResponse,
    VendorWorkOrder,
    TenantMessageRewrite,
    MoveOutResponse,
    MaintenanceWorkflow,
    MaintenanceChatRequest,
    MaintenanceChatResponse,
    MaintenanceRequestExtraction,
    LeaseGenerationRequestWrapper,
    LeaseGenerationResponse,
    EmailRewriteRequest,
    EmailRewriteResponse
)
from app.analyzer import LeaseAnalyzer
from app.bedrock_client import BedrockClient
from app.lease_generator import LegalResearchService, LeaseGenerationService
from app.config import settings
from app.lease_schemas import LeaseExtractionResponse
from app.lease_extractor import LeaseExtractor
from app.lease_utils import validate_pdf_file, generate_request_id, estimate_cost

# Enums for dropdown selections in Swagger UI
class ProviderEnum(str, Enum):
    """Available AI providers on AWS Bedrock"""
    anthropic = "anthropic"
    meta = "meta"
    mistral = "mistral"


class ModelEnum(str, Enum):
    """Available AI models on AWS Bedrock"""
    # Anthropic Claude (Best for legal analysis)
    claude_35_sonnet_v2 = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    claude_35_sonnet_v1 = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    claude_3_opus = "anthropic.claude-3-opus-20240229-v1:0"
    claude_3_haiku = "anthropic.claude-3-haiku-20240307-v1:0"
    
    # Meta Llama (Open source)
    llama_405b = "meta.llama3-1-405b-instruct-v1:0"
    llama_70b = "meta.llama3-1-70b-instruct-v1:0"
    llama_8b = "meta.llama3-1-8b-instruct-v1:0"
    
    # Mistral AI (European alternative)
    mistral_large = "mistral.mistral-large-2407-v1:0"
    mistral_small = "mistral.mistral-small-2402-v1:0"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
from app.exceptions import (
    APIException,
    ValidationError,
    PDFExtractionError,
    PDFTimeoutError,
    AITimeoutError,
    AIModelError,
    EmptyPDFError
)
from app.validators import (
    validate_maintenance_request,
    validate_tenant_message,
    validate_landlord_notes,
    validate_move_out_request,
    validate_owner_notes
)

logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Lease Violation Analyzer - Model Comparison API",
    description="Compare different AI models for analyzing lease agreements against government laws",
    version="1.0.0"
)

# Configure CORS to handle preflight OPTIONS requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins - adjust for production
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"]  # Expose all headers in response
)

# Custom exception handler for API exceptions
@app.exception_handler(APIException)
async def api_exception_handler(request, exc: APIException):
    """Handle custom API exceptions with structured error responses"""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )

# Initialize analyzer
analyzer = LeaseAnalyzer()

# Initialize Bedrock client (shared across all endpoints)
bedrock_client = BedrockClient()

# Initialize lease generator services
legal_research_service = LegalResearchService()
lease_generation_service = LeaseGenerationService()

# Rate limiting storage (in-memory for simplicity)
# For production, use Redis or similar
rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = 20  # requests
RATE_LIMIT_WINDOW = 60  # seconds


def check_rate_limit(client_ip: str) -> bool:
    """
    Check if client has exceeded rate limit
    
    Args:
        client_ip: Client IP address
        
    Returns:
        True if within limit, False if exceeded
    """
    now = datetime.now()
    cutoff = now - timedelta(seconds=RATE_LIMIT_WINDOW)
    
    # Remove old requests outside the window
    rate_limit_storage[client_ip] = [
        req_time for req_time in rate_limit_storage[client_ip]
        if req_time > cutoff
    ]
    
    # Check if limit exceeded
    if len(rate_limit_storage[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False
    
    # Add current request
    rate_limit_storage[client_ip].append(now)
    return True


@app.get("/")
async def root():
    """
    API Root - Get available endpoints and service info
    
    Returns overview of all API endpoints and service metadata.
    """
    return {
        "name": "Lease Violation Analyzer API",
        "version": "1.0.0",
        "description": "Compare AI models for lease violation analysis",
        "endpoints": {
            "models": "/models",
            "analyze_single": "/analyze/single",
            "analyze_compare": "/analyze/compare",
            "analyze_categorized": "/analyze/categorized",
            "maintenance_evaluate": "/maintenance/evaluate",
            "vendor_work_order": "/maintenance/vendor",
            "maintenance_workflow": "/maintenance/workflow",
            "maintenance_chat": "/tenant/chat",
            "tenant_rewrite": "/tenant/rewrite",
            "lease_generate": "/lease/generate",
            "extract_lease": "/extract-lease",
            "lease_extraction_health": "/lease-extraction/health",
            "docs": "/docs"
        }
    }


@app.get("/models", response_model=list[ModelInfo])
async def list_models():
    """
    List all available AI models with pricing and capabilities
    
    Returns pricing, speed, and feature info for all AWS Bedrock models.
    Use this to choose the right model for your needs.
    """
    try:
        models = BedrockClient.get_available_models()
        return models
    except Exception as e:
        logger.error(f"Error listing models: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/single", response_model=AnalysisResult)
async def analyze_single(
    file: UploadFile = File(..., description="PDF lease file to analyze"),
    model_name: ModelEnum = Form(..., description="Model to use for analysis"),
    search_strategy: SearchStrategy = Form(
        default=SearchStrategy.NATIVE_SEARCH,
        description="Search strategy: native_search (model searches web) or duckduckgo_search (DuckDuckGo fallback)"
    )
):
    """
    Analyze lease with single AI model for violations
    
    Upload a lease PDF and select an AI model to analyze it against landlord-tenant laws.
    Model searches the web for relevant laws and identifies potential violations.
    
    **Example Response:** Violations found (e.g., illegal security deposit amount), 
    lease clauses cited, government law citations, cost & time metrics.
    """
    try:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported"
            )
        
        # Read file
        pdf_bytes = await file.read()
        
        # Check file size
        file_size_mb = len(pdf_bytes) / (1024 * 1024)
        if file_size_mb > settings.MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit"
            )
        
        # All models in ALL_MODELS can use native search
        # No validation needed - all models are instructed to search the web
        
        # Analyze
        logger.info(f"Analyzing with {model_name} using {search_strategy}")
        result = analyzer.analyze_single(pdf_bytes, model_name, search_strategy)
        
        if result.error:
            raise HTTPException(status_code=500, detail=result.error)
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in analyze_single endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/compare", response_model=ComparisonResult)
async def analyze_compare(
    file: UploadFile = File(..., description="PDF lease file to analyze")
):
    """
    Compare ALL AI models - analyze lease with every available model
    
    Upload lease PDF to test ALL models simultaneously and compare results.
    Get cost, speed, and accuracy comparison across Anthropic, Meta, Mistral models.
    
    **Use Case:** Find the best model for your specific lease analysis needs.
    **Example:** See which model finds the most violations and costs least.
    
    This endpoint runs comprehensive benchmarking across all 19 configured models.
    Each model is instructed to search the web for relevant landlord-tenant laws.
    
    Compares: cost, time, accuracy, and citation quality.
    
    Args:
        file: PDF lease file
        
    Returns:
        ComparisonResult with analysis from all models and detailed comparison summary
    """
    try:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported"
            )
        
        # Read file
        pdf_bytes = await file.read()
        
        # Check file size
        file_size_mb = len(pdf_bytes) / (1024 * 1024)
        if file_size_mb > settings.MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit"
            )
        
        # Analyze with all models
        logger.info(f"Starting comparison analysis for {file.filename}")
        results = await analyzer.analyze_compare(pdf_bytes)
        
        if not results:
            raise HTTPException(
                status_code=500,
                detail="No successful analyses completed"
            )
        
        # Extract location from first successful result
        lease_location = None
        for result in results:
            if result.lease_info and not result.error:
                lease_location = analyzer.extract_location(result.lease_info)
                logger.info(f"Extracted lease location: {lease_location.full_location}")
                break
        
        # Generate readable comparison summary
        comparison_summary = analyzer.generate_comparison_summary(results)
        
        # Determine best models (for backward compatibility)
        valid_results = [r for r in results if r.metrics and not r.error]
        
        best_by_cost = None
        best_by_time = None
        best_by_citations = None
        best_overall = None
        
        if valid_results:
            # Best by cost (lowest)
            best_cost = min(valid_results, key=lambda x: x.metrics.cost_usd)
            best_by_cost = f"{best_cost.model_name} (${best_cost.metrics.cost_usd:.4f})"
            
            # Best by time (fastest)
            best_time = min(valid_results, key=lambda x: x.metrics.total_time_seconds)
            best_by_time = f"{best_time.model_name} ({best_time.metrics.total_time_seconds:.2f}s)"
            
            # Best by citations (most .gov citations)
            best_citations = max(valid_results, key=lambda x: x.metrics.gov_citations_count)
            best_by_citations = f"{best_citations.model_name} ({best_citations.metrics.gov_citations_count} .gov citations)"
            
            # Best overall (weighted score)
            def overall_score(result):
                # Normalize metrics (lower cost = better, lower time = better, more citations = better)
                cost_score = 1 / (result.metrics.cost_usd + 0.001)  # Avoid division by zero
                time_score = 1 / (result.metrics.total_time_seconds + 0.1)
                citation_score = result.metrics.gov_citations_count
                confidence_score = result.metrics.avg_confidence_score
                
                # Weighted combination
                return (cost_score * 0.3 + time_score * 0.2 + 
                       citation_score * 0.3 + confidence_score * 0.2)
            
            best_overall_result = max(valid_results, key=overall_score)
            best_overall = f"{best_overall_result.model_name}"
        
        return ComparisonResult(
            lease_file_name=file.filename,
            lease_location=lease_location,
            total_models_tested=len(results),
            results=results,
            best_by_cost=best_by_cost,
            best_by_time=best_by_time,
            best_by_citations=best_by_citations,
            best_overall=best_overall,
            comparison_summary=comparison_summary
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in analyze_compare endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/provider/{provider}", response_model=ComparisonResult)
async def analyze_by_provider(
    provider: ProviderEnum,
    file: UploadFile = File(..., description="PDF lease file to analyze")
):
    """
    Analyze lease with all models from one provider
    
    Compare all models from a specific provider (Anthropic, Meta, or Mistral).
    Upload lease PDF and select provider to test all their models.
    
    **Example:** Select 'anthropic' to compare Claude Opus, Sonnet, and Haiku.
    **Use Case:** Find best model within your preferred provider.
    """
    try:
        provider_value = provider.value.lower()
        
        # Map provider names to model prefixes
        provider_map = {
            "openai": "openai/",
            "anthropic": "anthropic/",
            "google": "google/",
            "meta": "meta-llama/",
            "mistral": "mistralai/",
            "deepseek": "deepseek/",
            "qwen": "qwen/",
            "perplexity": "perplexity/"
        }
        
        if provider_value not in provider_map:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid provider. Available: {', '.join(provider_map.keys())}"
            )
        
        # Validate file
        if not file.filename.endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported"
            )
        
        # Read file
        pdf_bytes = await file.read()
        
        # Check file size
        file_size_mb = len(pdf_bytes) / (1024 * 1024)
        if file_size_mb > settings.MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit"
            )
        
        # Get models for this provider
        prefix = provider_map[provider_value]
        provider_models = [m for m in settings.ALL_MODELS if m.startswith(prefix)]
        
        if not provider_models:
            raise HTTPException(
                status_code=404,
                detail=f"No models found for provider '{provider_value}'"
            )
        
        # Analyze with provider's models using native web search
        logger.info(f"Starting {provider_value} provider analysis for {file.filename} with {len(provider_models)} models")
        
        # Run models in parallel using asyncio
        async def analyze_model(model: str):
            # All models use native search (they search the web themselves)
            search_strategy = SearchStrategy.NATIVE_SEARCH
            
            # Run in executor since analyze_single is sync
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                analyzer.analyze_single,
                pdf_bytes,
                model,
                search_strategy
            )
            return result
        
        # Analyze all models in parallel
        tasks = [analyze_model(model) for model in provider_models]
        results = await asyncio.gather(*tasks)
        
        # Extract location from first successful result
        lease_location = None
        for result in results:
            if result.lease_info and not result.error:
                lease_location = analyzer.extract_location(result.lease_info)
                logger.info(f"Extracted lease location: {lease_location.full_location}")
                break
        
        # Generate readable comparison summary
        comparison_summary = analyzer.generate_comparison_summary(results)
        
        # Calculate best models for this provider
        valid_results = [r for r in results if r.metrics and not r.error]
        
        best_by_cost = None
        best_by_time = None
        best_by_citations = None
        
        if valid_results:
            best_cost = min(valid_results, key=lambda x: x.metrics.cost_usd)
            best_by_cost = f"{best_cost.model_name} (${best_cost.metrics.cost_usd:.4f})"
            
            best_time = min(valid_results, key=lambda x: x.metrics.total_time_seconds)
            best_by_time = f"{best_time.model_name} ({best_time.metrics.total_time_seconds:.2f}s)"
            
            best_citations = max(valid_results, key=lambda x: x.metrics.gov_citations_count)
            best_by_citations = f"{best_citations.model_name} ({best_citations.metrics.gov_citations_count} .gov)"
        
        return ComparisonResult(
            lease_file_name=file.filename,
            lease_location=lease_location,
            total_models_tested=len(results),
            results=results,
            best_by_cost=best_by_cost,
            best_by_time=best_by_time,
            best_by_citations=best_by_citations,
            best_overall=f"{provider_value.title()} provider comparison",
            comparison_summary=comparison_summary
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in analyze_by_provider endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze/categorized", response_model=CategorizedAnalysisResult)
async def analyze_categorized(
    file: UploadFile = File(..., description="PDF lease file to analyze")
):
    """
    Analyze lease with categorized violation breakdown
    
    Uses Mistral Medium to analyze lease and organize violations by category:
    security deposits, rent terms, maintenance, termination, discrimination, etc.
    
    **Example Output:** Violations grouped by type with lease clauses and law citations.
    **Use Case:** Get structured overview of all lease issues by category.
    
    This endpoint uses Mistral Medium 3.1 to analyze the lease and automatically
    categorize each violation into one of these categories:
    - **Rent Increase**: Violations related to rent increases, caps, notice requirements
    - **Tenant & Owner Rights**: Violations of tenant rights or landlord obligations (repairs, entry, privacy, etc.)
    - **Fair Housing Laws**: Discrimination, accessibility, protected classes violations
    - **Licensing**: Property licensing, registration, permit violations
    - **Others**: Any violation that doesn't fit the above categories
    
    The model searches the web for relevant .gov laws and provides citations for each violation.
    
    Args:
        file: PDF lease file
        
    Returns:
        CategorizedAnalysisResult with violations organized by category, lease info, and performance metrics
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise ValidationError(
            message="Invalid file type",
            details=f"File '{file.filename}' is not a PDF",
            suggestion="Please upload a PDF file"
        )
    
    # Read file
    pdf_bytes = await file.read()
    
    # Analyze with categorization
    logger.info(f"Starting categorized analysis for {file.filename}")
    result = analyzer.analyze_categorized(pdf_bytes)
    
    if result.error:
        raise AIModelError(
            message="AI categorization failed",
            details=result.error
        )
    
    return result


@app.post("/maintenance/evaluate", response_model=MaintenanceResponse)
async def evaluate_maintenance_request(
    file: UploadFile = File(..., description="PDF lease file"),
    maintenance_request: str = Form(..., description="Maintenance request from tenant (e.g., 'Broken heater in bedroom')"),
    landlord_notes: Optional[str] = Form(None, description="Optional notes from landlord (e.g., 'Already fixed last month', 'Tenant caused damage', 'Need to schedule inspection first')")
):
    """
    Evaluate maintenance request - Approve or reject based on lease (FREE)
    
    Upload lease + maintenance request to get AI decision on landlord responsibility.
    AI reviews lease, applies landlord's notes (if any), and generates professional response.
    
    **Cost:** FREE ($0.00) - Uses Llama 3.3
    **Decision:** APPROVED (landlord pays) or REJECTED (tenant pays)
    
    **Example 1:**
    - Request: "Broken heater"
    - Lease: "Landlord maintains HVAC"
    - Result: APPROVED with response message citing lease Section 8.2
    
    **Example 2:**
    - Request: "Broken dishwasher"
    - Lease: "Tenant handles appliances"
    - Landlord Notes: "Already fixed last month"
    - Result: REJECTED with explanation citing lease terms
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise ValidationError(
            message="Invalid file type",
            details=f"File '{file.filename}' is not a PDF",
            suggestion="Please upload a PDF file"
        )
    
    # Read file
    pdf_bytes = await file.read()
    
    # Validate inputs
    validated_request = validate_maintenance_request(maintenance_request)
    validated_notes = validate_landlord_notes(landlord_notes) if landlord_notes else None
    
    # Extract lease info
    from app.pdf_parser import PDFParser
    pdf_parser = PDFParser()
    lease_info = pdf_parser.extract_lease_info(pdf_bytes)
    
    # Evaluate maintenance request
    logger.info(f"Evaluating maintenance request: {validated_request[:50]}...")
    if validated_notes:
        logger.info(f"Landlord notes: {validated_notes[:100]}...")
    result = bedrock_client.evaluate_maintenance_request(
        maintenance_request=validated_request,
        lease_info=lease_info,
        landlord_notes=validated_notes
    )
    
    return result


@app.post("/maintenance/vendor", response_model=VendorWorkOrder)
async def generate_vendor_work_order(
    file: UploadFile = File(..., description="PDF lease file"),
    maintenance_request: str = Form(..., description="Maintenance request from tenant (e.g., 'Broken heater in bedroom')"),
    landlord_notes: Optional[str] = Form(None, description="Optional notes from landlord (e.g., 'Tenant says no heat for 2 days', 'Check HVAC filter first', 'Emergency - freezing temps')")
):
    """
    Generate vendor work order for maintenance issue (FREE)
    
    Create professional work order for contractors with property details, urgency, and scope.
    AI extracts info from lease and landlord notes to build complete work order.
    
    **Cost:** FREE ($0.00) - Uses Llama 3.3
    **Output:** Ready-to-send work order with address, urgency, description
    
    **Example 1:**
    - Request: "Broken heater"
    - Notes: "No heat for 2 days, freezing temps"
    - Result: Emergency work order with HVAC details and urgency flag
    
    **Example 2:**
    - Request: "Leaking faucet"
    - Notes: "Dripping constantly"
    - Result: Urgent plumbing work order with scope details
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise ValidationError(
            message="Invalid file type",
            details=f"File '{file.filename}' is not a PDF",
            suggestion="Please upload a PDF file"
        )
    
    # Read file
    pdf_bytes = await file.read()
    
    # Validate inputs
    validated_request = validate_maintenance_request(maintenance_request)
    validated_notes = validate_landlord_notes(landlord_notes) if landlord_notes else None
    
    # Extract lease info
    from app.pdf_parser import PDFParser
    pdf_parser = PDFParser()
    lease_info = pdf_parser.extract_lease_info(pdf_bytes)
    
    # Generate vendor work order
    logger.info(f"Generating vendor work order for: {validated_request[:50]}...")
    if validated_notes:
        logger.info(f"Landlord notes: {validated_notes[:100]}...")
    result = bedrock_client.generate_vendor_work_order(
        maintenance_request=validated_request,
        lease_info=lease_info,
        landlord_notes=validated_notes
    )
    
    return result


@app.post("/maintenance/workflow", response_model=MaintenanceWorkflow)
async def maintenance_workflow(
    file: UploadFile = File(..., description="PDF lease file"),
    maintenance_request: str = Form(..., description="Maintenance request from tenant (e.g., 'Broken heater in bedroom')"),
    landlord_notes: Optional[str] = Form(None, description="Optional notes from landlord (e.g., 'Emergency - no heat for 3 days', 'Tenant caused damage')")
):
    """
    Complete maintenance workflow - Evaluate + Tenant message + Vendor order (FREE)
    
    One-stop endpoint that handles entire maintenance workflow in single call.
    
    **What you get:**
    1. Decision: Approved or rejected based on lease
    2. Tenant message: Professional response for tenant
    3. Vendor work order: Ready to send (if approved)
    
    **Cost:** FREE ($0.00) - Uses Llama 3.3
    **Use Case:** Process maintenance request from start to finish instantly
    
    **Example:**
    - Request: "AC not working"
    - Lease: "Landlord maintains HVAC"
    - Result: Approved + tenant approval message + vendor work order
    
    **Uses Llama 3.3 (FREE model)** for all processing - $0.00 cost
    
    **You get:**
    - ✅ Decision (approved/rejected) based on lease terms
    - ✅ Professional message to send to tenant
    - ✅ Lease clauses cited to support decision
    - ✅ Vendor work order with all details (if approved)
    - ✅ Timeline and next steps
    
    **Examples:**
    
    **Example 1 - Approved Request:**
    ```
    Request: "Heater is broken, no heat for 2 days"
    Landlord Notes: "Emergency situation"
    
    Response:
    - Decision: "approved"
    - Tenant Message: "We have received your maintenance request regarding the heating system. 
                      Per Section 8.2 of the lease, we are responsible for maintaining heating 
                      systems. This is an emergency repair and we will dispatch a technician 
                      immediately. Expected completion: 24 hours."
    - Vendor Work Order:
        * Title: "Emergency Heater Repair - 123 Main St"
        * Description: "Heating system failure at 123 Main St, Apt 4B. No heat for 2 days 
                       during freezing temperatures. Requires immediate HVAC assessment and repair. 
                       Contact tenant John Smith at xxx-xxx-xxxx for access."
        * Urgency: "emergency"
    ```
    
    **Example 2 - Rejected Request:**
    ```
    Request: "Dishwasher stopped working"
    
    Response:
    - Decision: "rejected"
    - Tenant Message: "We have received your maintenance request regarding the dishwasher. 
                      After reviewing Section 12.3 of the lease agreement, appliance maintenance 
                      and repairs are the tenant's responsibility. Please arrange for repairs or 
                      replacement at your expense. You may hire a licensed technician of your choice."
    - Vendor Work Order: null (not generated for rejected requests)
    ```
    
    Args:
        file: PDF lease file
        maintenance_request: The maintenance issue from tenant
        landlord_notes: Optional context/notes from landlord
        
    Returns:
        MaintenanceWorkflow with complete response including:
        - decision: "approved" or "rejected"
        - tenant_message: Professional message to send to tenant
        - vendor_work_order: Complete work order (only if approved, null if rejected)
        - lease_clauses_cited: Exact lease clauses supporting the decision
        - decision_reasons: List of reasons based on lease
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise ValidationError(
            message="Invalid file type",
            details=f"File '{file.filename}' is not a PDF",
            suggestion="Please upload a PDF file"
        )
    
    # Read file
    pdf_bytes = await file.read()
    
    # Validate inputs
    validated_request = validate_maintenance_request(maintenance_request)
    validated_notes = validate_landlord_notes(landlord_notes) if landlord_notes else None
    
    # Extract lease info
    from app.pdf_parser import PDFParser
    pdf_parser = PDFParser()
    lease_info = pdf_parser.extract_lease_info(pdf_bytes)
    
    # Process maintenance workflow
    logger.info(f"Processing complete maintenance workflow for: {validated_request[:50]}...")
    if validated_notes:
        logger.info(f"Landlord notes: {validated_notes[:100]}...")
    
    result = bedrock_client.process_maintenance_workflow(
        maintenance_request=validated_request,
        lease_info=lease_info,
        landlord_notes=validated_notes
    )
    
    return result


@app.post("/move-out/evaluate", response_model=MoveOutResponse)
async def evaluate_move_out_request(
    file: UploadFile = File(..., description="PDF lease file"),
    move_out_request: str = Form(..., description="Tenant's move-out request (e.g., 'I want to move out on July 15th', 'Giving my 30-day notice')"),
    owner_notes: Optional[str] = Form(None, description="Optional notes from owner/landlord (e.g., 'Tenant still owes $200 in late fees', 'Property needs deep cleaning', 'Security deposit held for damages')")
):
    """
    Evaluate tenant move-out request and calculate financial obligations (FREE)
    
    Check if tenant gave proper notice, calculate deposit refund, and generate response.
    AI validates notice period, reviews lease terms, applies owner notes, calculates finances.
    
    **Cost:** FREE ($0.00) - Uses Llama 3.3
    **Output:** Approved/requires attention + financial summary + next steps
    
    **Example 1:**
    - Request: "Moving out July 31st" (given July 1st)
    - Lease: "30-day notice required"
    - Result: APPROVED - $1,500 deposit refund, next steps listed
    
    **Example 2:**
    - Request: "Moving out in 2 weeks"
    - Lease: "60-day notice", Owner Notes: "Owes $500"
    - Result: REQUIRES ATTENTION - Insufficient notice, may forfeit deposit
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise ValidationError(
            message="Invalid file type",
            details=f"File '{file.filename}' is not a PDF",
            suggestion="Please upload a PDF file"
        )
    
    # Read file
    pdf_bytes = await file.read()
    
    # Validate inputs
    validated_request = validate_move_out_request(move_out_request)
    validated_notes = validate_owner_notes(owner_notes) if owner_notes else None
    
    # Extract lease info
    from app.pdf_parser import PDFParser
    pdf_parser = PDFParser()
    lease_info = pdf_parser.extract_lease_info(pdf_bytes)
    
    # Evaluate move-out request
    logger.info(f"Evaluating move-out request: {validated_request[:100]}...")
    if validated_notes:
        logger.info(f"Owner notes: {validated_notes[:100]}...")
    result = bedrock_client.evaluate_move_out_request(
        move_out_request=validated_request,
        lease_info=lease_info,
        owner_notes=validated_notes
    )
    
    return result


@app.post("/tenant/rewrite", response_model=TenantMessageRewrite)
async def rewrite_tenant_message(
    message: str = Body(..., embed=True, description="Tenant's original maintenance issue description")
):
    """
    Rewrite tenant message to professional format (FREE)
    
    Transform informal tenant messages into clear, professional maintenance requests.
    AI adds structure, clarifies details, determines urgency.
    
    **Cost:** FREE ($0.00) - Uses Llama 3.3
    
    **Request Body:**
    ```json
    {"message": "heater broke"}
    ```
    
    **Example:**
    - Input: "heater broke"
    - Output: Professional message with greeting, details, urgency (urgent)
    - Improvements: Added context, specified timing, polite tone
    """
    # Validate input
    validated_message = validate_tenant_message(message)
    
    logger.info(f"Rewriting tenant message: {validated_message[:100]}...")
    
    # Rewrite message using AI
    result = bedrock_client.rewrite_tenant_message(
        tenant_message=validated_message
    )
    
    logger.info(f"Message rewritten successfully. Urgency: {result.estimated_urgency}")
    
    return result


@app.post("/tenant/chat", response_model=MaintenanceChatResponse)
async def maintenance_chat(
    request: Request,
    chat_request: MaintenanceChatRequest
):
    """
    Tenant chatbot - Troubleshoot maintenance issues interactively (FREE)
    
    AI assistant helps tenants troubleshoot issues before creating tickets.
    Provides step-by-step guidance, asks clarifying questions, suggests when to submit ticket.
    
    **Cost:** FREE ($0.00) - Uses Claude Haiku (fast)
    
    **Request Body:**
    ```json
    {
      "conversationHistory": [
        {"role": "user", "content": "My shower is leaking"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "Yes, even when turned off"}
      ]
    }
    ```
    
    **Example:** Tenant describes issue → AI asks questions → Suggests troubleshooting → 
    Determines if ticket needed → Sets suggestTicket: true when ready
    
    - **Provides step-by-step troubleshooting** for plumbing, electrical, HVAC, appliances, doors/windows
    - **Asks clarifying questions** to understand the issue better
    - **Suggests SAFE DIY solutions** that require no tools or technical expertise
    - **Knows when to escalate** to professional maintenance staff
    - **Maintains conversation context** - understands "yes", "no", "it", "that" based on chat history
    
    **Safety First:**
    - Only suggests solutions safe for tenants without tools
    - Never suggests electrical work (except checking breakers)
    - Never suggests gas appliance repairs
    - Never suggests climbing or accessing dangerous areas
    - Immediately escalates safety hazards
    
    **Escalation Logic:**
    - After 3-4 back-and-forth exchanges without resolution
    - When issue requires professional tools or expertise
    - For safety concerns (gas, electrical sparking, major leaks, etc.)
    - When tenant tries suggestions but issue persists
    
    **Cost**: FREE ($0.00) - Uses Llama 3.3 free model
    
    **Rate Limit**: 20 requests per minute per IP address
    
    **Request Format:**
    The frontend should append the new user message to the conversation history before sending.
    The last message must always be from the user.
    
    ```json
    {
        "conversationHistory": [
            {"role": "assistant", "content": "Hello! What seems to be the problem?"},
            {"role": "user", "content": "my shower has low water pressure"},
            {"role": "assistant", "content": "Let's troubleshoot this. Is the shower head removable?"},
            {"role": "user", "content": "it's fixed"}
        ]
    }
    ```
    
    **Response Format:**
    ```json
    {
        "response": "Try gently cleaning the nozzle holes with a toothpick. Can you see if water flow improves?",
        "suggestTicket": false
    }
    ```
    
    When `suggestTicket` is `true`, the response will include a message like:
    "This needs professional attention. Would you like to create a maintenance ticket?"
    
    **Example Conversation Flow:**
    
    1. User: "shower head is clogged"
       AI: "Let's troubleshoot this. Is the shower head removable, or is it fixed to the pipe?"
       suggestTicket: false
    
    2. User: "it's fixed"
       AI: "Try gently cleaning the nozzle holes with a toothpick or pin to remove mineral buildup. Can you see if water flow improves?"
       suggestTicket: false
    
    3. User: "still clogged"
       AI: "The blockage might be in the pipe connection. This needs professional attention to avoid damage. Would you like to create a maintenance ticket?"
       suggestTicket: true
    
    Args:
        request: FastAPI request object (for rate limiting)
        chat_request: Chat request with conversation history (last message must be from user)
        
    Returns:
        MaintenanceChatResponse with AI response and ticket suggestion flag
        
    Raises:
        HTTPException: 429 if rate limit exceeded
        HTTPException: 400 if request format is invalid
        HTTPException: 500 if AI service fails
    """
    # Rate limiting
    client_ip = request.client.host
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "message": f"Maximum {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds",
                "suggestion": "Please wait a moment before trying again"
            }
        )
    
    # Validate conversation history format
    for i, msg in enumerate(chat_request.conversationHistory):
        if msg.role not in ["user", "assistant"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Invalid conversation history",
                    "message": f"Message {i} has invalid role '{msg.role}'. Must be 'user' or 'assistant'",
                    "suggestion": "Check your conversationHistory format"
                }
            )
    
    # Validate last message is from user
    if not chat_request.conversationHistory or chat_request.conversationHistory[-1].role != "user":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid conversation history",
                "message": "The last message in conversationHistory must be from the user",
                "suggestion": "Append the new user message to the conversation history before sending"
            }
        )
    
    # Get the user's message from the last item in history
    user_message = chat_request.conversationHistory[-1].content
    logger.info(f"Maintenance chat from {client_ip}: '{user_message[:50]}...'")
    logger.info(f"Conversation history: {len(chat_request.conversationHistory)} messages")
    
    try:
        # Process chat request
        result = bedrock_client.maintenance_chat(
            conversation_history=chat_request.conversationHistory
        )
        
        logger.info(f"Chat response: suggestTicket={result.suggestTicket}")
        return result
        
    except Exception as e:
        logger.error(f"Error in maintenance chat: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Chat service error",
                "message": "Unable to process your message",
                "suggestion": "Please try again or contact support"
            }
        )


@app.post("/tenant/extract-request", response_model=MaintenanceRequestExtraction)
async def extract_maintenance_request(
    chat_request: MaintenanceChatRequest
):
    """
    Extract title & description from chat for maintenance ticket (FREE)
    
    Call after tenant chat ends to get structured maintenance request.
    AI analyzes full conversation and extracts concise title + detailed description.
    
    **Cost:** FREE ($0.00) - Uses Claude Haiku (fast, 1-2 seconds)
    **When to use:** After tenant finishes chatting and is ready to submit ticket
    
    **Request Body:**
    ```json
    {
      "conversationHistory": [
        {"role": "user", "content": "My shower is leaking"},
        {"role": "assistant", "content": "Where is it leaking from?"}
      ]
    }
    ```
    
    **Example Output:**
    - title: "Main bathroom shower head leaking with low pressure" (max 80 chars)
    - description: "The shower head in main bathroom is broken and leaking even when off..."
    """
    try:
        # Validate conversation history
        if not chat_request.conversationHistory or len(chat_request.conversationHistory) == 0:
            raise HTTPException(
                status_code=400,
                detail="Conversation history is required"
            )
        
        logger.info(f"Extracting maintenance request from {len(chat_request.conversationHistory)} messages")
        
        # Extract using Haiku
        result = bedrock_client.extract_maintenance_request_from_chat(
            conversation_history=chat_request.conversationHistory
        )
        
        logger.info(f"Extracted request - Title: {result.title}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting maintenance request: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Extraction failed",
                "message": "Unable to extract maintenance request from conversation",
                "suggestion": "Ensure conversation history contains maintenance-related discussion"
            }
        )


@app.post("/analyze/duckduckgo", response_model=AnalysisResult)
async def analyze_with_duckduckgo(
    file: UploadFile = File(..., description="PDF lease file to analyze"),
    model_name: ModelEnum = Form(..., description="Model to use for analysis")
):
    """
    Analyze lease using DuckDuckGo search (Optional alternative method)
    
    Uses DuckDuckGo to search .gov sites for laws, then provides results to AI model.
    Alternative to native search - use /analyze/single for default approach.
    
    **Use Case:** Test DuckDuckGo search method vs native model search
    **Example:** Upload lease + select model → AI analyzes with DuckDuckGo law search
    """
    try:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported"
            )
        
        # Read file
        pdf_bytes = await file.read()
        
        # Check file size
        file_size_mb = len(pdf_bytes) / (1024 * 1024)
        if file_size_mb > settings.MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {settings.MAX_FILE_SIZE_MB}MB limit"
            )
        
        # Analyze with DuckDuckGo search
        logger.info(f"Analyzing with {model_name} using DuckDuckGo search")
        result = analyzer.analyze_single(
            pdf_bytes, 
            model_name, 
            SearchStrategy.DUCKDUCKGO_SEARCH
        )
        
        if result.error:
            raise HTTPException(status_code=500, detail=result.error)
        
        return result
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in analyze_with_duckduckgo endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/providers")
async def list_providers():
    """
    List all AI providers and their available models
    
    Returns providers (Anthropic, Meta, Mistral) with model counts and IDs.
    """
    providers = {}
    for model_id in settings.ALL_MODELS:
        provider = model_id.split('/')[0]
        if provider not in providers:
            providers[provider] = {
                "name": provider,
                "models": [],
                "count": 0
            }
        providers[provider]["models"].append(model_id)
        providers[provider]["count"] += 1
    
    return {
        "total_providers": len(providers),
        "providers": list(providers.values())
    }


@app.get("/health")
async def health_check():
    """Service health check - Returns service status"""
    return {"status": "healthy", "service": "Lease Violation Analyzer"}


@app.post("/lease/generate")
async def generate_lease(
    request: Request,
    lease_request: LeaseGenerationRequestWrapper = Body(...)
):
    """
    Generate custom lease agreement with legal research (Premium)
    
    Create comprehensive lease document with jurisdiction-specific legal research.
    Uses Claude Sonnet 4.5 to generate complete, legally-informed lease as HTML.
    
    **Cost:** Varies - Uses Claude Sonnet 4.5 (premium model)
    **Output:** HTML lease document with proper formatting and legal clauses
    
    **Example:** Provide property details + jurisdiction → AI researches local laws → 
    Generates complete lease with state-specific clauses
    
    This endpoint:
    1. Validates the lease request data
    2. Performs jurisdiction-specific legal research
    3. Generates a complete lease document using Claude Sonnet 4.5
    4. Converts the document to HTML format with proper styling and numbering
    5. Returns ready-to-display HTML that can be rendered directly in the frontend
    5. Returns the PDF file for download
    
    Args:
        lease_request: Complete lease generation request with all required details
        
    Returns:
        LeaseGenerationResponse with generated document, word count, and legal research
        
    Raises:
        HTTPException: For validation errors or generation failures
    """
    try:
        # Check rate limit
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please try again later."
            )
        
        logger.info(f"Generating lease for property: {lease_request.lease_generation_request.property_details.name}")
        
        # Validate request data and collect warnings
        warnings = []
        req_data = lease_request.lease_generation_request
        
        # Check for missing or invalid data
        if not req_data.property_details.address.city:
            warnings.append("City not provided - using state laws only")
        
        if not req_data.property_details.address.state or req_data.property_details.address.state.upper() == "USA":
            warnings.append("Invalid state - defaulting to California laws")
            req_data.property_details.address.state = "California"
        
        if not req_data.financials.base_rent.amount or req_data.financials.base_rent.amount <= 0:
            warnings.append("Base rent amount not specified")
        
        if not req_data.lease_terms.start_date and not req_data.lease_terms.planned_term_summary:
            warnings.append("Lease start date not clearly specified")
        
        if not req_data.parties.tenants or len(req_data.parties.tenants) == 0:
            warnings.append("No tenants specified")
        
        # Perform legal research
        logger.info(f"Performing legal research for {req_data.property_details.address.city}, {req_data.property_details.address.state}")
        legal_research_dict = await legal_research_service.research_jurisdiction_laws(
            city=req_data.property_details.address.city or "Unknown",
            state=req_data.property_details.address.state,
            lease_type=req_data.metadata.lease_type
        )
        
        # Generate the lease document (plain text)
        logger.info("Generating lease document with Claude 3.5 Sonnet")
        lease_document = await lease_generation_service.generate_lease(
            request=req_data,
            legal_research=legal_research_dict
        )
        
        # Calculate word count
        word_count = len(lease_document.split())
        logger.info(f"Generated lease document with {word_count} words")
        
        # Convert to HTML
        logger.info("Converting lease document to HTML")
        property_name = req_data.property_details.name or "Lease_Agreement"
        html_content = lease_generation_service.convert_to_html(lease_document, property_name)
        
        logger.info(f"Generated HTML lease document ({len(html_content)} bytes)")
        
        # Return HTML response
        return HTMLResponse(
            content=html_content,
            status_code=200,
            headers={
                "X-Word-Count": str(word_count),
                "X-Lease-Type": req_data.metadata.lease_type,
                "X-Property-Name": req_data.property_details.name or "Unknown",
                "X-Generated-At": datetime.now().isoformat()
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating lease: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate lease: {str(e)}"
        )


@app.post("/rewrite-email", response_model=EmailRewriteResponse)
async def rewrite_as_email(request: EmailRewriteRequest):
    """
    Rewrite text as professional email (FREE)
    
    Transform any text into properly formatted business email with subject line.
    AI creates greeting, body, and closing in professional tone.
    
    **Cost:** FREE ($0.00) - Uses Claude Haiku
    
    **Request Body:**
    ```json
    {"text": "Need to talk about the lease violation"}
    ```
    
    **Example Output:**
    - subject: "Regarding Lease Agreement Discussion"
    - email_content: Professional email with proper greeting and structure
    """
    try:
        logger.info(f"Rewriting text as email (length: {len(request.text)})")
        
        # Create prompt for email rewriting
        system_prompt = """You are a professional email writing assistant. Your task is to rewrite provided text into a well-formatted, professional email.

REQUIREMENTS:
1. Create a clear, concise subject line
2. Use professional business email format with proper greeting and closing
3. Maintain the core message and intent of the original text
4. Use clear, polite, and professional language
5. Organize information logically with proper paragraphs
6. Keep it concise while being complete

OUTPUT FORMAT:
Subject: [Clear subject line]

[Email body with greeting, content, and closing]

Do NOT add any explanations, notes, or commentary outside the email format."""

        user_prompt = f"""Rewrite the following text as a professional email:

{request.text}"""

        # Call Claude Haiku model
        response = bedrock_client.generate_text(
            model_id=settings.FREE_MODEL,  # Claude 3.5 Haiku
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.3
        )
        
        # Extract email content
        email_content = response.strip()
        
        # Extract subject line if present
        subject = None
        if email_content.startswith("Subject:"):
            lines = email_content.split("\n", 1)
            subject = lines[0].replace("Subject:", "").strip()
            email_content = lines[1].strip() if len(lines) > 1 else email_content
        
        logger.info(f"Successfully rewrote text as email (subject: {subject})")
        
        return EmailRewriteResponse(
            original_text=request.text,
            email_content=email_content,
            subject=subject,
            status="success"
        )
        
    except Exception as e:
        logger.error(f"Error rewriting email: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rewrite email: {str(e)}"
        )


@app.post("/extract-lease", response_model=LeaseExtractionResponse)
async def extract_lease_data(
    file: UploadFile = File(..., description="PDF lease file to extract structured data from")
):
    """
    Extract structured data from a commercial lease PDF
    
    This endpoint uses advanced sliding window processing with AWS Bedrock Claude 3 Haiku
    to extract comprehensive lease information including:
    - Utility responsibilities
    - Common area maintenance charges
    - Additional fees
    - Tenant improvements
    - Term details (dates, renewal options)
    - Rent and deposits
    - Rent increase schedules
    - Abatements and discounts
    - Special clauses
    - NSF fees
    
    Processing time: 20-30 seconds for typical 40-page lease
    Cost: ~$0.30-0.40 per lease
    
    Args:
        file: PDF file upload (max 100MB)
        
    Returns:
        LeaseExtractionResponse with structured data, metadata, and summary
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    pdf_bytes = await file.read()
    file_size = len(pdf_bytes)
    request_id = generate_request_id(file.filename)
    
    # Validate file
    is_valid, error_msg = validate_pdf_file(file.filename, file_size)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)
    
    logger.info(f"Starting lease extraction for {file.filename} (request_id={request_id})")
    
    try:
        # Create extractor instance
        extractor = LeaseExtractor(
            region=settings.AWS_REGION,
            access_key=settings.AWS_ACCESS_KEY_ID,
            secret_key=settings.AWS_SECRET_ACCESS_KEY,
            model_id=settings.LEASE_EXTRACTION_MODEL,
            temperature=settings.LEASE_EXTRACTION_TEMPERATURE,
            max_tokens=settings.LEASE_EXTRACTION_MAX_TOKENS,
            max_concurrent=settings.LEASE_EXTRACTION_MAX_CONCURRENT,
            timeout=settings.LEASE_EXTRACTION_TIMEOUT,
            window_size=settings.LEASE_EXTRACTION_WINDOW_SIZE,
            window_overlap=settings.LEASE_EXTRACTION_WINDOW_OVERLAP
        )
        
        # Extract lease data
        result = await extractor.extract_lease(pdf_bytes=pdf_bytes, filename=file.filename)
        
        # Calculate cost estimate
        token_usage = result.metadata.token_usage
        estimated_cost = estimate_cost(
            token_usage.get('input_tokens', 0), 
            token_usage.get('output_tokens', 0), 
            "haiku"
        )
        
        logger.info(
            f"Extraction successful: {request_id}",
            extra={
                "processing_time": result.metadata.processing_time,
                "total_tokens": token_usage.get('total_tokens', 0),
                "estimated_cost": estimated_cost,
                "conflicts_found": result.metadata.conflicts_found
            }
        )
        
        # Cleanup
        await extractor.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@app.get("/lease-extraction/health")
async def lease_extraction_health():
    """
    Health check for lease extraction API
    
    Returns current configuration and status of the lease extraction system.
    """
    return {
        "status": "healthy",
        "service": "Lease Data Extraction API",
        "version": "1.0.0",
        "config": {
            "model": settings.LEASE_EXTRACTION_MODEL,
            "max_concurrent_bedrock": settings.LEASE_EXTRACTION_MAX_CONCURRENT,
            "window_size": settings.LEASE_EXTRACTION_WINDOW_SIZE,
            "window_overlap": settings.LEASE_EXTRACTION_WINDOW_OVERLAP,
            "max_pages": settings.LEASE_EXTRACTION_MAX_PAGES,
            "timeout": settings.LEASE_EXTRACTION_TIMEOUT
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
