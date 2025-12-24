from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class SearchStrategy(str, Enum):
    """Available search strategies"""
    NATIVE_SEARCH = "native_search"  # Models search the web themselves
    DUCKDUCKGO_SEARCH = "duckduckgo_search"  # DuckDuckGo + LLM (optional fallback)
    # Keeping old enum for backward compatibility
    DUCKDUCKGO = "duckduckgo"  # Alias for DUCKDUCKGO_SEARCH


class LeaseInfo(BaseModel):
    """Extracted information from lease document"""
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    landlord: Optional[str] = None
    tenant: Optional[str] = None
    rent_amount: Optional[str] = None
    security_deposit: Optional[str] = None
    lease_duration: Optional[str] = None
    full_text: str


class Citation(BaseModel):
    """Legal citation for a violation"""
    source_url: str
    title: str
    relevant_text: str
    law_reference: Optional[str] = None  # e.g., "State Code § 123.45"
    is_gov_site: bool = False


class ViolationCategory(str, Enum):
    """Categories for lease violations"""
    RENT_INCREASE = "rent_increase"
    TENANT_OWNER_RIGHTS = "tenant_owner_rights"
    FAIR_HOUSING_LAWS = "fair_housing_laws"
    LICENSING = "licensing"
    OTHERS = "others"


class EmailRewriteRequest(BaseModel):
    """Request to rewrite text in email format"""
    text: str = Field(..., description="Text to be rewritten as an email")


class EmailRewriteResponse(BaseModel):
    """Response with rewritten email"""
    original_text: str
    email_content: str
    subject: Optional[str] = None
    status: str = "success"


class MaintenanceResponse(BaseModel):
    """Landlord's response to maintenance request evaluated against lease"""
    maintenance_request: str  # Original request from tenant
    decision: str = Field(..., description="'approved' or 'rejected'")
    response_message: str  # Professional response message from landlord
    decision_reasons: List[str]  # Reasons for approval or rejection based on lease
    lease_clauses_cited: List[str]  # Exact lease clauses supporting decision
    landlord_responsibility_clause: Optional[str] = None  # Clause if landlord must fix
    tenant_responsibility_clause: Optional[str] = None  # Clause if tenant responsible
    estimated_timeline: Optional[str] = None  # If approved, timeline from lease
    alternative_action: Optional[str] = None  # What tenant should do instead (if rejected)


class VendorWorkOrder(BaseModel):
    """AI-generated work order for vendor to fix maintenance issue"""
    maintenance_request: str  # Original request from tenant
    work_order_title: str  # Brief title for work order
    comprehensive_description: str  # Complete description with issue, property details, access, urgency, scope, requirements
    urgency_level: str = Field(..., description="'routine', 'urgent', or 'emergency'")


class MoveOutResponse(BaseModel):
    """Landlord's response to tenant move-out request evaluated against lease"""
    move_out_request: str  # Original move-out request from tenant
    decision: str = Field(..., description="'approved' or 'requires_attention'")
    response_message: str  # Professional response message for tenant
    notice_period_valid: bool  # Whether tenant gave proper notice per lease
    notice_period_required: Optional[str] = None  # Required notice period from lease
    notice_period_given: Optional[str] = None  # Actual notice given by tenant
    move_out_date: Optional[str] = None  # Requested or approved move-out date
    financial_summary: Dict[str, str]  # Security deposit, final rent, charges, refund amount
    lease_clauses_cited: List[str]  # Exact lease clauses about move-out/notice
    penalties_or_fees: Optional[List[str]] = None  # Any penalties for insufficient notice
    next_steps: List[str]  # What tenant needs to do before moving out
    estimated_refund_timeline: Optional[str] = None  # When tenant gets deposit back


class Violation(BaseModel):
    """Detected lease violation"""
    violation_type: str
    description: str
    severity: str = Field(..., description="low, medium, high, critical")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    lease_clause: str
    citations: List[Citation] = []


class CategorizedViolation(BaseModel):
    """Violation with category classification"""
    violation_type: str
    category: ViolationCategory
    description: str
    severity: str = Field(..., description="low, medium, high, critical")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    lease_clause: str
    citations: List[Citation] = []
    recommended_action: str = Field(default="Review with legal counsel", description="Precise action to address the violation")


class AnalysisMetrics(BaseModel):
    """Performance metrics for model analysis"""
    model_name: str
    search_strategy: SearchStrategy
    total_time_seconds: float
    cost_usd: float
    gov_citations_count: int
    total_citations_count: int
    violations_found: int
    avg_confidence_score: float
    has_law_references: bool  # Does it include specific law codes/sections?
    tokens_used: Dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}


class AnalysisResult(BaseModel):
    """Complete analysis result from a single model"""
    model_name: str
    search_strategy: SearchStrategy
    lease_info: LeaseInfo
    violations: List[Violation]
    metrics: AnalysisMetrics
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


class CategorizedAnalysisResult(BaseModel):
    """Complete analysis result with categorized violations"""
    model_name: str
    search_strategy: SearchStrategy
    lease_info: LeaseInfo
    violations_by_category: Dict[str, List[CategorizedViolation]]
    total_violations: int
    metrics: AnalysisMetrics
    timestamp: datetime = Field(default_factory=datetime.now)
    error: Optional[str] = None


class LeaseLocation(BaseModel):
    """Extracted lease location information"""
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    full_location: str  # Formatted: "City, State (County County)"


class ComparisonResult(BaseModel):
    """Comparison of multiple model analyses"""
    lease_file_name: str
    lease_location: Optional[LeaseLocation] = None  # NEW: Location extracted from PDF
    total_models_tested: int
    results: List[AnalysisResult]
    best_by_cost: Optional[str] = None
    best_by_time: Optional[str] = None
    best_by_citations: Optional[str] = None
    best_overall: Optional[str] = None
    comparison_summary: Optional["ComparisonSummary"] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ModelComparison(BaseModel):
    """Readable comparison data for a single model"""
    model_name: str
    provider: str
    search_strategy: str
    
    # Performance
    cost_usd: float
    time_seconds: float
    
    # Quality
    violations_found: int
    gov_citations: int
    total_citations: int
    avg_confidence: float
    
    # Rankings (1 = best)
    cost_rank: int
    time_rank: int
    citation_rank: int
    overall_rank: int
    
    # Status
    success: bool
    error_message: Optional[str] = None


class ComparisonSummary(BaseModel):
    """Human-readable comparison summary"""
    
    # Quick stats
    total_models: int
    successful_analyses: int
    failed_analyses: int
    
    # Cost comparison
    cheapest_model: str
    most_expensive_model: str
    avg_cost: float
    cost_range: str  # e.g., "$0.001 - $0.045"
    
    # Speed comparison
    fastest_model: str
    slowest_model: str
    avg_time: float
    time_range: str  # e.g., "8.5s - 45.2s"
    
    # Quality comparison
    most_citations_model: str
    most_violations_model: str
    highest_confidence_model: str
    
    # Detailed rankings
    models_by_cost: List[ModelComparison]
    models_by_time: List[ModelComparison]
    models_by_citations: List[ModelComparison]
    models_by_overall_score: List[ModelComparison]
    
    # Recommendations
    recommended_for_accuracy: str
    recommended_for_budget: str
    recommended_for_speed: str
    recommended_overall: str


class ModelInfo(BaseModel):
    """Information about available models"""
    model_id: str
    name: str
    provider: str
    has_native_search: bool
    estimated_cost_per_1k_tokens: Dict[str, float]  # {"input": X, "output": Y}
    context_length: int


class AnalyzeRequest(BaseModel):
    """Request for single model analysis"""
    model_name: str
    search_strategy: SearchStrategy = SearchStrategy.DUCKDUCKGO


class TenantMessageRewrite(BaseModel):
    """Tenant's rewritten maintenance message for landlord"""
    original_message: str  # What tenant typed initially
    rewritten_message: str  # AI-improved professional message
    improvements_made: List[str]  # List of improvements (clarity, professionalism, etc.)
    tone: str = Field(..., description="professional, urgent, polite, etc.")
    estimated_urgency: str = Field(..., description="routine, urgent, emergency")


class MaintenanceWorkflow(BaseModel):
    """Complete maintenance workflow: tenant message, landlord evaluation, and vendor work order"""
    maintenance_request: str  # Original request from tenant
    
    # Tenant communication
    tenant_message: str  # Professional message to send to tenant
    tenant_message_tone: str  # Tone of tenant message (approved, regretful, informative)
    
    # Landlord decision
    decision: str = Field(..., description="'approved' or 'rejected'")
    decision_reasons: List[str]  # Reasons for approval or rejection based on lease
    lease_clauses_cited: List[str]  # Exact lease clauses supporting decision
    
    # Vendor work order (only if approved)
    vendor_work_order: Optional[VendorWorkOrder] = None  # None if rejected
    
    # Additional context
    estimated_timeline: Optional[str] = None  # Timeline for repair if approved
    alternative_action: Optional[str] = None  # What tenant should do if rejected


class ChatMessage(BaseModel):
    """Single message in maintenance chat conversation"""
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class MaintenanceChatRequest(BaseModel):
    """Request for maintenance assistant chatbot"""
    conversationHistory: List[ChatMessage] = Field(
        ...,
        min_length=1,
        description="Full conversation history including the new user message (oldest first). The last message must be from the user."
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "conversationHistory": [
                    {"role": "assistant", "content": "Hello! I'm here to help with your maintenance issue. What seems to be the problem?"},
                    {"role": "user", "content": "my shower has low water pressure"},
                    {"role": "assistant", "content": "Let's troubleshoot this. Is the shower head removable, or is it fixed to the pipe?"},
                    {"role": "user", "content": "it's fixed"}
                ]
            }
        }


class MaintenanceChatResponse(BaseModel):
    """Response from maintenance assistant chatbot"""
    response: str = Field(..., description="AI assistant's contextually aware response")
    suggestTicket: bool = Field(
        default=False,
        description="True if issue needs professional attention and should create ticket"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "response": "Let's troubleshoot this. Is the shower head removable, or is it fixed to the pipe?",
                "suggestTicket": False
            }
        }


class MaintenanceRequestExtraction(BaseModel):
    """Extracted maintenance request from tenant chat conversation"""
    title: str = Field(..., description="Brief title for the maintenance request (max 80 chars, from tenant's perspective)", max_length=80)
    description: str = Field(..., description="Detailed description of the issue from tenant's conversation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "title": "Broken shower head leaking water",
                "description": "The shower head in the main bathroom is broken and leaking water constantly. It's been dripping for 2 days and getting worse. The water pressure is also very low when trying to use it."
            }
        }


# ============================================================================
# LEASE GENERATOR MODELS
# ============================================================================

# Address Models
class LeaseAddress(BaseModel):
    """Address for lease property"""
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None


# Property Models
class UnitDetails(BaseModel):
    """Unit details for lease property"""
    unit_number: Optional[str] = None
    size_sq_ft: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None


class PropertyDetails(BaseModel):
    """Property details for lease"""
    name: Optional[str] = None
    address: LeaseAddress
    unit_details: Optional[UnitDetails] = None


# Party Models
class LeaseTenant(BaseModel):
    """Tenant information for lease"""
    full_name: str


class LeaseParties(BaseModel):
    """Parties involved in lease"""
    landlord_entity: str
    tenants: List[LeaseTenant]


# Lease Terms Models
class LeaseTermsDetails(BaseModel):
    """Lease term details"""
    planned_term_summary: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    length_description: Optional[str] = None
    move_in_date: Optional[str] = None
    renewal_options: Optional[str] = None
    renewal_rent_increase_terms: Optional[str] = None


# Financial Models
class BaseRent(BaseModel):
    """Base rent information"""
    amount: Optional[float] = None
    grace_period_days: Optional[int] = None


class LateFees(BaseModel):
    """
    Late fee structure:
    - type: Description of late fee
    - amount: If fixed, dollar value; if percentage, the percentage (e.g., 5.0 for 5%)
    - is_percentage: True if amount represents a percentage of base rent
    """
    type: Optional[str] = None
    amount: Optional[float] = None
    is_percentage: Optional[bool] = False


class OtherDeposit(BaseModel):
    """Other deposit information"""
    label: Optional[str] = None
    amount: Optional[float] = None


class Deposits(BaseModel):
    """Deposit information"""
    security_deposit_amount: Optional[float] = None
    other_deposits: Optional[List[OtherDeposit]] = []


class Financials(BaseModel):
    """Financial terms for lease"""
    base_rent: BaseRent
    late_fees: Optional[LateFees] = None
    deposits: Optional[Deposits] = None


# Responsibility Models
class Utility(BaseModel):
    """
    Utility payment structure:
    - Percentage: responsible_party pays X% of actual utility bill
    - Fixed/Amount: responsible_party pays a fixed dollar amount
    """
    utility_name: Optional[str] = None
    responsible_party: Optional[str] = Field(None, pattern="^(tenant|owner|landlord)$")
    calculation_method: Optional[str] = Field(None, pattern="^(percentage|amount|fixed)$")
    percentage_value: Optional[float] = None
    fixed_amount: Optional[float] = None
    frequency: Optional[str] = None


class CommonAreaMaintenance(BaseModel):
    """
    CAM payment structure:
    - Percentage: responsible_party pays X% of actual CAM costs
    - Fixed/Amount: responsible_party pays a fixed dollar amount
    """
    area_name: Optional[str] = None
    responsible_party: Optional[str] = Field(None, pattern="^(tenant|owner|landlord)$")
    calculation_method: Optional[str] = Field(None, pattern="^(percentage|amount|fixed)$")
    percentage_value: Optional[float] = None
    fixed_amount: Optional[float] = None
    frequency: Optional[str] = None


class AdditionalFee(BaseModel):
    """
    Additional fee structure:
    - Percentage: responsible_party pays X% of actual costs
    - Fixed/Amount: responsible_party pays a fixed dollar amount
    """
    fee_name: Optional[str] = None
    responsible_party: Optional[str] = Field(None, pattern="^(tenant|owner|landlord)$")
    calculation_method: Optional[str] = Field(None, pattern="^(percentage|amount|fixed)$")
    percentage_value: Optional[float] = None
    fixed_amount: Optional[float] = None
    frequency: Optional[str] = None


class Responsibilities(BaseModel):
    """Responsibility details for lease"""
    utilities: Optional[List[Utility]] = []
    common_area_maintenance: Optional[List[CommonAreaMaintenance]] = []
    additional_fees: Optional[List[AdditionalFee]] = []


# Legal Terms Models
class LegalAndSpecialTerms(BaseModel):
    """Legal and special terms for lease"""
    special_clauses: Optional[str] = None


# Metadata Model
class LeaseMetadata(BaseModel):
    """Metadata for lease generation"""
    lease_type: str = Field(..., pattern="^(Commercial|Residential)$")


# Main Request Model
class LeaseGenerationRequest(BaseModel):
    """Complete lease generation request"""
    metadata: LeaseMetadata
    property_details: PropertyDetails
    parties: LeaseParties
    lease_terms: LeaseTermsDetails
    financials: Financials
    responsibilities: Optional[Responsibilities] = None
    legal_and_special_terms: Optional[LegalAndSpecialTerms] = None


class LeaseGenerationRequestWrapper(BaseModel):
    """Wrapper for lease generation request"""
    lease_generation_request: LeaseGenerationRequest


# Response Models
class LegalResearchResult(BaseModel):
    """Legal research results"""
    jurisdiction: str
    laws_checked: List[str]
    sources: List[str]
    compliance_notes: List[str]


class LeaseGenerationResponse(BaseModel):
    """Response from lease generation"""
    success: bool
    lease_document: str
    word_count: int
    metadata: dict
    legal_research: LegalResearchResult
    warnings: Optional[List[str]] = []
