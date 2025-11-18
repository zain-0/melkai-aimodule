from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from enum import Enum
import logging
import asyncio
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
    MaintenanceWorkflow
)
from app.analyzer import LeaseAnalyzer
from app.openrouter_client import OpenRouterClient
from app.config import settings

# Enums for dropdown selections in Swagger UI
class ProviderEnum(str, Enum):
    """Available AI providers"""
    openai = "openai"
    anthropic = "anthropic"
    google = "google"
    meta = "meta"
    mistral = "mistral"
    deepseek = "deepseek"
    qwen = "qwen"
    perplexity = "perplexity"


class ModelEnum(str, Enum):
    """Available AI models with web search capabilities"""
    # Perplexity (Native Search Built-in)
    perplexity_sonar_pro = "perplexity/sonar-pro"
    perplexity_sonar = "perplexity/sonar"
    perplexity_sonar_reasoning = "perplexity/sonar-reasoning"
    
    # Anthropic Claude (2025 working models)
    claude_sonnet_45 = "anthropic/claude-sonnet-4.5"
    claude_37_sonnet = "anthropic/claude-3.7-sonnet"
    claude_opus_4 = "anthropic/claude-opus-4"
    
    # OpenAI (Latest with search)
    gpt_5 = "openai/gpt-5"
    gpt_5_mini = "openai/gpt-5-mini"
    gpt_4o = "openai/gpt-4o"
    
    # Google Gemini (Working 2.5 series)
    gemini_25_flash = "google/gemini-2.5-flash-preview-09-2025"
    gemini_25_flash_lite = "google/gemini-2.5-flash-lite"
    
    # Meta Llama
    llama_4_scout = "meta-llama/llama-4-scout"
    llama_33_free = "meta-llama/llama-3.3-8b-instruct:free"
    
    # Mistral (Working models)
    mistral_medium = "mistralai/mistral-medium-3.1"
    devstral_medium = "mistralai/devstral-medium"
    
    # DeepSeek (Working models)
    deepseek_v32 = "deepseek/deepseek-v3.2-exp"
    deepseek_chat_free = "deepseek/deepseek-chat-v3.1:free"
    
    # Qwen (Working models)
    qwen3_max = "qwen/qwen3-max"
    qwen3_coder_plus = "qwen/qwen3-coder-plus"

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
            "tenant_rewrite": "/tenant/rewrite",
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
        models = OpenRouterClient.get_available_models()
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
    openrouter_client = OpenRouterClient()
    result = openrouter_client.evaluate_maintenance_request(
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
    openrouter_client = OpenRouterClient()
    result = openrouter_client.generate_vendor_work_order(
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
    
    openrouter_client = OpenRouterClient()
    result = openrouter_client.process_maintenance_workflow(
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
    openrouter_client = OpenRouterClient()
    result = openrouter_client.evaluate_move_out_request(
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
    openrouter_client = OpenRouterClient()
    result = openrouter_client.rewrite_tenant_message(
        tenant_message=validated_message
    )
    
    logger.info(f"Message rewritten successfully. Urgency: {result.estimated_urgency}")
    
    return result


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
