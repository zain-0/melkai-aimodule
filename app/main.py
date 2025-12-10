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
    LeaseGenerationRequestWrapper,
    LeaseGenerationResponse
)
from app.analyzer import LeaseAnalyzer
from app.bedrock_client import BedrockClient
from app.lease_generator import LegalResearchService, LeaseGenerationService
from app.config import settings

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
    """Root endpoint with API information"""
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
            "docs": "/docs"
        }
    }


@app.get("/models", response_model=list[ModelInfo])
async def list_models():
    """
    Get list of available models with pricing and capabilities
    
    Returns:
        List of ModelInfo objects
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
    Analyze a lease with a single model using native web search
    
    All models are instructed to search the web for relevant landlord-tenant laws.
    Use the /analyze/duckduckgo endpoint if you prefer DuckDuckGo search instead.
    
    Args:
        file: PDF lease file
        model_name: Model identifier (select from dropdown)
        search_strategy: 'native_search' (default) or 'duckduckgo_search'
        
    Returns:
        AnalysisResult with violations, citations, and performance metrics
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
    Analyze a lease with ALL available models using native web search
    
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
    Analyze a lease with all models from a specific provider
    
    Available providers: openai, anthropic, google, meta, mistral, deepseek, qwen, perplexity
    
    Args:
        provider: Provider name (select from dropdown)
        file: PDF lease file
        
    Returns:
        ComparisonResult with analysis from all models of the specified provider
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
    Analyze a lease with Mistral Medium 3.1 and categorize violations
    
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
            details=result.error,
            suggestion="Try again or contact support if the issue persists"
        )
    
    return result


@app.post("/maintenance/evaluate", response_model=MaintenanceResponse)
async def evaluate_maintenance_request(
    file: UploadFile = File(..., description="PDF lease file"),
    maintenance_request: str = Form(..., description="Maintenance request from tenant (e.g., 'Broken heater in bedroom')"),
    landlord_notes: Optional[str] = Form(None, description="Optional notes from landlord (e.g., 'Already fixed last month', 'Tenant caused damage', 'Need to schedule inspection first')")
):
    """
    Evaluate a maintenance request against the lease and approve or reject based on lease terms (FREE)
    
    Uses Llama 3.3 (FREE model) to:
    - Review the lease to determine maintenance responsibilities
    - Consider landlord's optional notes (if provided)
    - APPROVE if lease says landlord must handle this type of maintenance
    - REJECT if lease clearly states tenant is responsible
    - Default to APPROVE if unclear or not mentioned (landlord's standard duty)
    - Generate a professional response from the landlord's perspective
    - Cite exact lease clauses that support the decision
    
    **Cost**: FREE ($0.00) - Uses Llama 3.3 free model
    **The AI evaluates fairly based on lease + landlord's notes (if any).**
    
    Args:
        file: PDF lease file
        maintenance_request: The maintenance issue (e.g., "AC not working", "Leaking faucet", "Broken heater")
        landlord_notes: Optional context from landlord (e.g., "Already repaired last week", "Caused by tenant misuse")
        
    Returns:
        MaintenanceResponse with decision (approved/rejected) and lease justification
        
    Examples:
        Request: "Broken heater"
        If lease says "Landlord maintains heating systems" → APPROVED
        Response: "We have received your maintenance request regarding the heating system. 
                  Per Section 8.2 of the lease, we are responsible for maintaining heating systems. 
                  We will schedule a repair within 48 hours."
        
        Request: "Broken dishwasher" 
        If lease says "Tenant responsible for appliances" → REJECTED
        Response: "After reviewing your request, Section 12.3 of the lease states that appliance 
                  maintenance is the tenant's responsibility. Please arrange for repairs at your expense."
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
    bedrock_client = BedrockClient()
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
    Generate a professional work order for vendor/contractor to fix maintenance issue (FREE)
    
    Uses Llama 3.3 (FREE model) to:
    - Extract property address and tenant info from lease
    - Determine urgency level (routine, urgent, emergency)
    - Create detailed, vendor-focused description (excludes financial details)
    - Include access instructions and special notes
    - Add any lease requirements about repairs
    - Incorporate landlord's notes as context
    
    **Cost**: FREE ($0.00) - Uses Llama 3.3 free model
    **The AI creates a complete, professional work order ready to send to vendors.**
    
    Args:
        file: PDF lease file
        maintenance_request: The maintenance issue (e.g., "Broken heater", "Leaking faucet", "AC not working")
        landlord_notes: Optional context (e.g., "Emergency - no heat for 3 days", "Tenant available Mon-Fri 9-5")
        
    Returns:
        VendorWorkOrder with all details vendor needs to quote and complete the work
        
    Examples:
        Request: "Broken heater"
        Landlord Notes: "No heat for 2 days, freezing temps outside"
        → Work Order:
          - Title: "Emergency Heating System Repair - 123 Main St"
          - Urgency: "emergency"
          - Description: "Heating system failure reported by tenant. No heat for 2 days 
                        during freezing weather. Requires immediate HVAC inspection and repair."
          - Special Notes: "Emergency situation - freezing temperatures"
        
        Request: "Leaking kitchen faucet"
        Landlord Notes: "Tenant says it's dripping constantly"
        → Work Order:
          - Title: "Plumbing Repair - Kitchen Faucet Leak"
          - Urgency: "urgent"
          - Description: "Kitchen faucet is leaking constantly. Requires plumbing assessment 
                        and repair or replacement."
          - Special Notes: "Constant dripping - may need faucet replacement"
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
    bedrock_client = BedrockClient()
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
    Complete maintenance workflow: Evaluate request against lease + Generate messages for tenant and vendor (FREE)
    
    This is a combined endpoint that provides everything you need in one call:
    
    **What it does:**
    1. **Evaluates maintenance request** against the lease agreement
    2. **Generates professional message to tenant** (approved or rejected with explanation)
    3. **Creates vendor work order** (ONLY if approved) ready to send to contractors
    
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
    
    bedrock_client = BedrockClient()
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
    Evaluate tenant's move-out request against lease terms and calculate financial obligations (FREE)
    
    Uses Llama 3.3 (FREE model) to:
    - Check if tenant gave proper notice per lease (30, 60, 90 days, etc.)
    - Calculate final rent, security deposit refund, and any penalties
    - Determine if move-out date is valid
    - Review lease clauses about move-out procedures
    - Account for owner's notes (unpaid rent, damages, fees)
    - Provide professional response message for tenant
    - List next steps (inspection, keys, forwarding address, etc.)
    
    **Cost**: FREE ($0.00) - Uses Llama 3.3 free model
    **The AI evaluates fairly based on lease terms + owner's notes.**
    
    Args:
        file: PDF lease file
        move_out_request: Tenant's move-out notice (e.g., "I'm moving out on June 30th")
        owner_notes: Optional context from owner (e.g., "Tenant owes $500 in repairs")
        
    Returns:
        MoveOutResponse with:
        - Decision: approved or requires_attention
        - Notice period validation
        - Financial summary (deposit refund, final rent, penalties)
        - Professional response message for tenant
        - Next steps for tenant
        - Lease clauses cited
        
    Examples:
        Request: "I want to move out on July 31st" (given on July 1st)
        Lease says: "30-day notice required"
        Response: APPROVED - Proper notice given. Security deposit of $1,500 
                 will be refunded within 14 days after final inspection.
        
        Request: "Moving out in 2 weeks" (given on June 15th)
        Lease says: "60-day notice required"
        Response: REQUIRES ATTENTION - Insufficient notice. Lease requires 
                 60 days. You may be responsible for rent until August 15th 
                 or lose security deposit as penalty.
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
    bedrock_client = BedrockClient()
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
    Rewrite tenant's maintenance message to be more professional and clear (FREE)
    
    This endpoint helps tenants communicate maintenance issues effectively to their landlords.
    It uses AI (Llama 3.3 free model) to:
    - Make the message more professional and polite
    - Add structure (greeting, details, closing)
    - Clarify vague descriptions
    - Determine urgency level
    - Suggest improvements made
    
    Perfect for tenants who want to ensure their maintenance requests are:
    - Clear and specific
    - Professionally written
    - Properly structured
    - Appropriately urgent
    
    **Cost**: FREE ($0.00) - Uses Llama 3.3 free model
    
    **Request Body (JSON):**
    ```json
    {
        "message": "heater broke"
    }
    ```
    
    Args:
        message: The tenant's original message (can be informal, brief, or vague)
        
    Returns:
        TenantMessageRewrite with:
        - original_message: What the tenant typed
        - rewritten_message: AI-improved professional version
        - improvements_made: List of specific improvements
        - tone: The tone of the rewritten message
        - estimated_urgency: routine/urgent/emergency
        
    Example:
        Input: "heater broke"
        Output: 
          - Rewritten: "Hello, I wanted to report that the heating system in my unit 
            stopped working as of this morning. The unit is not producing any heat, 
            and with temperatures dropping, this is becoming uncomfortable. I would 
            appreciate it if you could arrange for a repair as soon as possible. 
            Thank you for your attention to this matter."
          - Improvements: ["Added greeting and closing", "Specified timing", 
            "Explained impact", "Professional tone"]
          - Urgency: "urgent"
    """
    # Validate input
    validated_message = validate_tenant_message(message)
    
    logger.info(f"Rewriting tenant message: {validated_message[:100]}...")
    
    # Rewrite message using AI
    bedrock_client = BedrockClient()
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
    Maintenance Assistant Chatbot - Get help with property maintenance issues (FREE)
    
    This endpoint provides an AI-powered maintenance assistant that helps tenants troubleshoot
    common property issues before creating a maintenance ticket. The assistant:
    
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
        bedrock_client = BedrockClient()
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


@app.post("/analyze/duckduckgo", response_model=AnalysisResult)
async def analyze_with_duckduckgo(
    file: UploadFile = File(..., description="PDF lease file to analyze"),
    model_name: ModelEnum = Form(..., description="Model to use for analysis")
):
    """
    Analyze a lease using DuckDuckGo search + any model (OPTIONAL FALLBACK)
    
    This endpoint uses DuckDuckGo to search for landlord-tenant laws from .gov sites,
    then provides the search results to the selected model for analysis.
    
    Most models can search the web themselves - use /analyze/single for native web search.
    This endpoint is for users who specifically want to test the DuckDuckGo approach.
    
    Args:
        file: PDF lease file
        model_name: Model identifier (select from dropdown)
        
    Returns:
        AnalysisResult with violations, citations, and performance metrics
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
    Get list of available providers with model counts
    
    Returns:
        Dict of providers and their available models
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
    """Health check endpoint"""
    return {"status": "healthy", "service": "Lease Violation Analyzer"}


@app.post("/lease/generate")
async def generate_lease(
    request: Request,
    lease_request: LeaseGenerationRequestWrapper = Body(...)
):
    """
    Generate a comprehensive lease agreement with legal research and return as HTML
    
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
