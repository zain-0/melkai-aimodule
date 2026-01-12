"""
Pydantic schemas for lease extraction API - matching exact output specification
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, List


# Charges Schema (reusable)
class Charges(BaseModel):
    """Financial charge structure"""
    type: Literal["Amount", "Percentage"]
    amount_value: Optional[float] = None
    percentage: Optional[float] = None
    base_amount: Optional[float] = None

    @field_validator('amount_value', 'percentage', 'base_amount')
    @classmethod
    def validate_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('Value must be non-negative')
        return v


# Frequency Type
FrequencyType = Literal["Weekly", "Bi-Weekly", "Monthly", "Quarterly", "Bi-Annually", "Annually", "As Needed", "One-time", "On Demand", "Per Occurrence"]

# Responsibility Type
ResponsibilityType = Literal["Tenant", "Owner"]


# Utility Responsibilities
class UtilityResponsibility(BaseModel):
    """Utility responsibility schema"""
    utility_name: str
    responsible: ResponsibilityType
    frequency: FrequencyType
    charges: Charges


# Common Area Maintenance
class CommonAreaMaintenance(BaseModel):
    """Common area maintenance schema"""
    area_name: str
    responsible: ResponsibilityType
    frequency: FrequencyType
    charges: Charges


# Additional Fees
class AdditionalFee(BaseModel):
    """Additional fee schema"""
    fee_name: str
    responsible: ResponsibilityType
    frequency: FrequencyType
    charges: Charges


# Tenant Improvements
class TenantImprovement(BaseModel):
    """Tenant improvement schema"""
    improvement_item: str
    responsible: ResponsibilityType
    amount: Optional[float] = None
    balance: Optional[float] = None
    recovery_method: Optional[Literal["Monthly Amortization", "One-time Charge", "Rent uplift"]] = None

    @field_validator('amount', 'balance')
    @classmethod
    def validate_non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError('Amount must be non-negative')
        return v


# Term
class Term(BaseModel):
    """Lease term details"""
    lease_start_date: Optional[str] = None  # YYYY-MM-DD
    lease_end_date: Optional[str] = None    # YYYY-MM-DD
    lease_length: Optional[str] = None
    move_in_date: Optional[str] = None      # YYYY-MM-DD
    renewal_options: Optional[Literal["yes", "no"]] = None
    renewal_rent_increase: Optional[str] = None  # Can be string or number


# Late Fee
class LateFee(BaseModel):
    """Late fee structure"""
    type: Optional[Literal["Amount", "Percentage"]] = None
    amount_value: Optional[float] = None
    percentage: Optional[float] = None
    base_amount: Optional[float] = None


# Rent & Deposits
class RentAndDeposits(BaseModel):
    """Rent and deposit details"""
    monthly_base_rent: Optional[float] = None
    rent_due_date: Optional[Literal["1st", "15th", "30th"]] = None
    grace_period: Optional[int] = None
    late_fee: Optional[LateFee] = None
    security_deposit: Optional[float] = None


# Other Deposits
class OtherDeposit(BaseModel):
    """Other deposit schema"""
    label: str
    amount: float

    @field_validator('amount')
    @classmethod
    def validate_non_negative(cls, v):
        if v < 0:
            raise ValueError('Amount must be non-negative')
        return v


# Rent Increase
class RentIncrease(BaseModel):
    """Rent increase details"""
    type: Optional[Literal["Amount", "Percentage"]] = None
    value: Optional[float] = None
    percentage: Optional[float] = None
    base_amount: Optional[float] = None


# Rent Increase Schedule
class RentIncreaseSchedule(BaseModel):
    """Rent increase schedule entry"""
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD
    base_rent: Optional[float] = None
    frequency: Optional[FrequencyType] = None
    increase: Optional[RentIncrease] = None
    per_sqft_rate: Optional[float] = None


# Abatements / Discounts
class AbatementDiscount(BaseModel):
    """Abatement or discount schema"""
    event_type: Literal["Abatements", "Discounts", "Waive Rent", "Rent Credit", "Rent Abatement", "Free Rent"]
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None    # YYYY-MM-DD
    discount_amount: Optional[float] = None
    reason: Optional[str] = None


# Special Clauses
class SpecialClause(BaseModel):
    """Special clause schema"""
    description: str


# NSF Fees
class NSFFees(BaseModel):
    """NSF fees schema"""
    amount: Optional[float] = None


# Complete Lease Data Schema
class LeaseData(BaseModel):
    """Complete lease extraction data"""
    utility_responsibilities: List[UtilityResponsibility] = Field(default_factory=list)
    common_area_maintenance: List[CommonAreaMaintenance] = Field(default_factory=list)
    additional_fees: List[AdditionalFee] = Field(default_factory=list)
    tenant_improvements: List[TenantImprovement] = Field(default_factory=list)
    term: Optional[Term] = None
    rent_and_deposits: Optional[RentAndDeposits] = None
    other_deposits: List[OtherDeposit] = Field(default_factory=list)
    rent_increase_schedule: List[RentIncreaseSchedule] = Field(default_factory=list)
    abatements_discounts: List[AbatementDiscount] = Field(default_factory=list)
    special_clauses: List[SpecialClause] = Field(default_factory=list)
    nsf_fees: Optional[NSFFees] = None


# Metadata Schema
class ExtractionMetadata(BaseModel):
    """Extraction process metadata"""
    processing_time: float
    total_windows: int
    total_pages: int
    confidence_scores: dict = Field(default_factory=dict)
    conflicts_found: bool = False
    conflict_details: List[str] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    window_timings: List[dict] = Field(default_factory=list)


# Complete Response Schema
class LeaseExtractionResponse(BaseModel):
    """Complete API response"""
    data: LeaseData
    metadata: ExtractionMetadata
    summary: str


# Request Schema
class LeaseExtractionRequest(BaseModel):
    """API request schema"""
    window_size: Optional[int] = Field(default=7, ge=3, le=15)
    window_overlap: Optional[int] = Field(default=2, ge=1, le=5)
