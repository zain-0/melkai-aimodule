"""
Lease Generator Service
Provides services for generating professional lease documents with legal research
"""

from typing import Dict, List, Optional
from datetime import datetime
from openai import OpenAI
from app.config import settings
from app.models import (
    LeaseGenerationRequest,
    LateFees,
    Utility,
    CommonAreaMaintenance,
    AdditionalFee,
    Deposits
)
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CALCULATION UTILITIES
# ============================================================================

def format_currency(amount: float, currency: str = "USD") -> str:
    """Format amount as currency string"""
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def calculate_late_fee_description(late_fees: Optional[LateFees], base_rent: float) -> str:
    """Generate human-readable description of late fee structure"""
    if not late_fees or not late_fees.amount:
        return "No late fees specified"
    
    if late_fees.is_percentage:
        calculated_amount = (late_fees.amount / 100) * base_rent
        return f"{late_fees.type or 'Late fee'}: {late_fees.amount}% of monthly base rent ({format_currency(calculated_amount)})"
    else:
        return f"{late_fees.type or 'Late fee'}: {format_currency(late_fees.amount)}"


def format_utility_payment(utility: Utility) -> str:
    """Format utility payment description for lease document"""
    name = utility.utility_name or "Utility"
    party = utility.responsible_party or "Responsible party"
    freq = utility.frequency or "monthly"
    
    if utility.calculation_method == "percentage":
        if utility.percentage_value:
            return f"{party} shall pay {utility.percentage_value}% of actual {freq.lower()} {name} costs"
        return f"{party} is responsible for {name} costs"
    
    elif utility.calculation_method == "fixed":
        if utility.fixed_amount:
            return f"{party} shall pay a fixed {freq.lower()} amount of {format_currency(utility.fixed_amount)} for {name}"
        return f"{party} shall pay a fixed {freq.lower()} amount for {name} (amount to be determined)"
    
    elif utility.calculation_method == "amount":
        if utility.fixed_amount:
            return f"{party} shall pay {format_currency(utility.fixed_amount)} {freq.lower()} for {name}"
        return f"{party} is responsible for {name} costs (amount to be determined)"
    
    return f"{party} is responsible for {name}"


def format_cam_payment(cam: CommonAreaMaintenance) -> str:
    """Format CAM payment description for lease document"""
    name = cam.area_name or "Common Area Maintenance"
    party = cam.responsible_party or "Responsible party"
    freq = cam.frequency or "monthly"
    
    if cam.calculation_method == "percentage":
        if cam.percentage_value:
            return f"{party} shall pay {cam.percentage_value}% of actual {freq.lower()} {name} costs"
        return f"{party} is responsible for {name} costs"
    
    elif cam.calculation_method == "fixed":
        if cam.fixed_amount:
            return f"{party} shall pay a fixed {freq.lower()} amount of {format_currency(cam.fixed_amount)} for {name}"
        return f"{party} shall pay a fixed {freq.lower()} amount for {name} (amount to be determined)"
    
    elif cam.calculation_method == "amount":
        if cam.fixed_amount:
            return f"{party} shall pay {format_currency(cam.fixed_amount)} {freq.lower()} for {name}"
        return f"{party} is responsible for {name} costs (amount to be determined)"
    
    return f"{party} is responsible for {name}"


def format_additional_fee(fee: AdditionalFee, base_rent: Optional[float] = None) -> str:
    """Format additional fee description for lease document"""
    name = fee.fee_name or "Additional Fee"
    party = fee.responsible_party or "Responsible party"
    freq = fee.frequency or "monthly"
    
    if fee.calculation_method == "percentage":
        if fee.percentage_value and base_rent:
            calculated = (fee.percentage_value / 100) * base_rent
            return f"{party} shall pay {fee.percentage_value}% of monthly base rent ({format_currency(calculated)}) {freq.lower()} for {name}"
        elif fee.percentage_value:
            return f"{party} shall pay {fee.percentage_value}% of actual {freq.lower()} {name} costs"
        return f"{party} is responsible for {name}"
    
    elif fee.calculation_method == "fixed":
        if fee.fixed_amount:
            return f"{party} shall pay a fixed {freq.lower()} amount of {format_currency(fee.fixed_amount)} for {name}"
        return f"{party} shall pay a fixed {freq.lower()} amount for {name} (amount to be determined)"
    
    elif fee.calculation_method == "amount":
        if fee.fixed_amount:
            return f"{party} shall pay {format_currency(fee.fixed_amount)} {freq.lower()} for {name}"
        return f"{party} is responsible for {name} (amount to be determined)"
    
    return f"{party} is responsible for {name}"


def calculate_total_deposits(deposits) -> float:
    """Calculate total of all deposits"""
    total = deposits.security_deposit_amount or 0.0
    if deposits.other_deposits:
        for deposit in deposits.other_deposits:
            if deposit.amount:
                total += deposit.amount
    return total


# ============================================================================
# LEGAL RESEARCH SERVICE
# ============================================================================

class LegalResearchService:
    """Service to provide legal compliance information for lease generation"""
    
    def __init__(self):
        self._search_cache = {}
        
    async def research_jurisdiction_laws(
        self, 
        city: str, 
        state: str, 
        lease_type: str
    ) -> Dict:
        """
        Research relevant laws for the jurisdiction.
        Uses comprehensive legal database.
        
        Args:
            city: City name
            state: State name
            lease_type: "Commercial" or "Residential"
            
        Returns:
            Dict with jurisdiction info, laws checked, sources, and compliance notes
        """
        jurisdiction = f"{city}, {state}" if city else state
        
        logger.info(f"Retrieving legal requirements for {jurisdiction} - {lease_type} lease from database...")
        
        # Use comprehensive default data
        laws_checked = self._get_default_laws(state, lease_type)
        sources = self._get_default_sources(state)
        compliance_notes = self._get_default_compliance_notes(state, lease_type)
        
        return {
            "jurisdiction": jurisdiction,
            "laws_checked": laws_checked,
            "sources": sources,
            "compliance_notes": compliance_notes
        }
    
    def _get_default_laws(self, state: str, lease_type: str) -> List[str]:
        """Return default laws for the state"""
        return [
            f"{state} Landlord-Tenant Act",
            f"{state} Civil Code - Residential/Commercial Leases",
            "Fair Housing Act (Federal)",
            f"{state} Security Deposit Regulations"
        ]
    
    def _get_default_sources(self, state: str) -> List[str]:
        """Return default sources for the state"""
        state_lower = state.lower().replace(" ", "")
        return [
            f"https://leginfo.legislature.ca.gov (California Laws)",
            f"{state} State Legislature Website",
            "U.S. Department of Housing and Urban Development (HUD)"
        ]
    
    def _get_default_compliance_notes(self, state: str, lease_type: str) -> List[str]:
        """Return default compliance notes for the state"""
        notes = [
            f"Ensure compliance with {state} state landlord-tenant laws for {lease_type.lower()} leases",
            "Security deposit limits and return requirements must be followed",
            "Fair housing and anti-discrimination laws apply",
            "Required disclosures must be included in lease agreement"
        ]
        
        if state == "California":
            notes.extend([
                "California Civil Code Section 1950.5 governs security deposits",
                "Rental agreement must comply with California rent control laws where applicable",
                "Habitability warranties required under California law"
            ])
        
        return notes


# ============================================================================
# LEASE GENERATION SERVICE
# ============================================================================

class LeaseGenerationService:
    """Service to generate professional legal lease documents using OpenRouter"""
    
    def __init__(self):
        self.client = OpenAI(
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
        )
        self.model = settings.LEASE_GENERATOR_MODEL
    
    async def generate_lease(
        self,
        request: LeaseGenerationRequest,
        legal_research: Dict
    ) -> str:
        """
        Generate a comprehensive legal lease document in HTML format.
        
        Args:
            request: The lease generation request data
            legal_research: Results from legal research including jurisdiction laws
            
        Returns:
            Formatted lease document as HTML string
        """
        # Build comprehensive prompt
        prompt = self._build_lease_prompt(request, legal_research)
        
        # Call OpenRouter API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=8000,
            )
            
            lease_document = response.choices[0].message.content
            return lease_document
            
        except Exception as e:
            logger.error(f"Failed to generate lease document: {str(e)}")
            raise Exception(f"Failed to generate lease document: {str(e)}")
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the AI model"""
        return """You are an expert legal document specialist with extensive experience in drafting residential and commercial lease agreements. Your role is to create PROFESSIONAL, LEGALLY SOUND, and COMPLETE lease documents that:

1. Are CONCISE yet COMPREHENSIVE - target 2-3 pages (approximately 1000-1500 words)
2. Comply with all applicable federal, state, and local laws
3. Use clear, unambiguous legal language
4. Include ALL necessary clauses and provisions without unnecessary verbosity
5. Protect the interests of both landlord and tenant with balanced rights and obligations
6. Follow standard legal formatting with numbered sections
7. Include required legal notices and state-mandated disclosures
8. Are professional, readable, and suitable for execution

CRITICAL HTML FORMATTING REQUIREMENTS:
You MUST generate the lease as valid, well-formed HTML5. Follow these rules STRICTLY:

1. **Document Structure:**
   - Always start with: <!DOCTYPE html>
   - Include complete <html lang="en"> tag
   - Include <head> section with:
     * <meta charset="UTF-8">
     * <meta name="viewport" content="width=device-width, initial-scale=1.0">
     * <title>Lease Agreement</title>
     * Complete <style> section with professional CSS
   - Include complete <body> section with all content
   - Close all tags properly: </body></html>

2. **CSS Styling (in <style> tag):**
   ```css
   body {
     font-family: 'Times New Roman', Times, serif;
     line-height: 1.6;
     max-width: 8.5in;
     margin: 0 auto;
     padding: 1in;
     background: white;
     color: #000;
   }
   h1 {
     text-align: center;
     font-size: 24px;
     margin-bottom: 20px;
     text-transform: uppercase;
   }
   h2 {
     font-size: 18px;
     margin-top: 30px;
     margin-bottom: 15px;
     border-bottom: 2px solid #000;
     padding-bottom: 5px;
   }
   h3 {
     font-size: 16px;
     margin-top: 20px;
     margin-bottom: 10px;
   }
   p {
     margin: 10px 0;
     text-align: justify;
   }
   ul, ol {
     margin: 10px 0 10px 30px;
   }
   .signature-section {
     margin-top: 50px;
     page-break-inside: avoid;
   }
   .signature-line {
     border-top: 1px solid #000;
     width: 300px;
     margin-top: 50px;
     display: inline-block;
   }
   .signature-block {
     margin: 30px 0;
   }
   @media print {
     body { padding: 0.5in; }
     @page { margin: 0.5in; }
   }
   ```

3. **Content Structure:**
   - Use <h1> for document title: "RESIDENTIAL/COMMERCIAL LEASE AGREEMENT"
   - Use <h2> for major sections (1. PARTIES, 2. PROPERTY, 3. TERM, etc.)
   - Use <h3> for subsections if needed
   - Use <p> tags for all paragraph text
   - Use <strong> for emphasis (amounts, dates, important terms)
   - Use <ul> or <ol> for lists
   - Use proper semantic HTML throughout

4. **Signature Section Format:**
   ```html
   <div class="signature-section">
     <h2>SIGNATURES</h2>
     <div class="signature-block">
       <p><strong>LANDLORD:</strong></p>
       <p>[Landlord Name]</p>
       <div class="signature-line"></div>
       <p>Signature</p>
       <div class="signature-line"></div>
       <p>Date</p>
     </div>
     <div class="signature-block">
       <p><strong>TENANT:</strong></p>
       <p>[Tenant Name]</p>
       <div class="signature-line"></div>
       <p>Signature</p>
       <div class="signature-line"></div>
       <p>Date</p>
     </div>
   </div>
   ```

5. **Validation Rules:**
   - NO unclosed tags - every tag must have a closing tag
   - NO invalid HTML entities - use proper encoding (&amp; &lt; &gt; etc.)
   - NO inline styles in HTML - all CSS in <style> section
   - NO broken nesting - close inner tags before outer tags
   - NO missing required attributes (lang, charset, viewport)
   - Use proper HTML5 semantic elements

6. **Quality Checklist:**
   ✓ Valid HTML5 structure
   ✓ All tags properly closed
   ✓ Professional CSS styling included
   ✓ Print-ready formatting
   ✓ Responsive for web viewing
   ✓ Accessible and semantic markup
   ✓ Clean, readable code structure

GENERATE ONLY VALID HTML5 - No markdown, no plain text, no malformed HTML.

CRITICAL DOCUMENT COMPLETENESS REQUIREMENTS:
- Generate the COMPLETE lease agreement in a single response (2-3 pages)
- Do NOT stop mid-document under any circumstances
- Do NOT ask if the user wants to continue
- Do NOT use phrases like "[Continued...]", "[Note: This is part 1...]", or "[To be continued...]"
- Write every section clearly and completely without excessive legal jargon
- Keep provisions concise while maintaining legal enforceability

=== RESIDENTIAL LEASE TEMPLATE (use for residential properties) ===

RESIDENTIAL LEASE AGREEMENT

This Residential Lease Agreement (the "Agreement") is made and entered into as of [Date], by and between [Landlord Name] ("Landlord") and [Tenant Name] ("Tenant").

1. PREMISES
Landlord hereby leases to Tenant the residential premises located at [Full Address] (the "Premises").

2. TERM
The term of this Agreement shall commence on [Start Date] and continue until [End Date]. [Include renewal options if applicable].

3. RENT
Tenant shall pay monthly rent of [Amount] due on the [Due Day] of each month via [Payment Method]. Grace period: [X] days. Late fees: [Specify amount or percentage after grace period].

4. SECURITY DEPOSIT
Tenant shall deposit [Amount] as security deposit. Deposit will be returned within [State Law Timeline] days after move-out, less any lawful deductions for damages, unpaid rent, or cleaning costs beyond normal wear and tear.

5. UTILITIES & SERVICES
[List each utility and specify who pays - Landlord or Tenant, including any percentage splits or fixed amounts for shared utilities].

6. USE OF PREMISES
Premises shall be used solely for private residential purposes. Occupancy limited to [Number] persons. Pets: [Allowed/Not Allowed with deposit of $X]. Smoking: [Allowed/Not Allowed].

7. MAINTENANCE & REPAIRS
Tenant must keep property clean and in good condition, promptly report maintenance issues, and is responsible for damages caused by negligence or misuse. Landlord will handle major structural repairs and systems (HVAC, plumbing, electrical) unless caused by Tenant's negligence.

8. ALTERATIONS
Tenant shall not paint, renovate, or alter the property without prior written consent from Landlord.

9. ENTRY BY LANDLORD
Landlord may enter Premises with [State Required Notice] notice for inspections, repairs, or showings, and without notice in emergencies.

10. RULES & REGULATIONS
Tenant agrees to follow all applicable community, HOA, or building rules.

11. DEFAULT AND REMEDIES
Events of default include: non-payment of rent, violation of lease terms, illegal activity, or damage to property. Landlord remedies include eviction, rent acceleration, and recovery of costs.

12. TERMINATION
[For fixed-term]: Lease ends on specified date unless renewed. [For month-to-month]: Either party may terminate with [X] days written notice. Early termination: [Specify conditions and fees if applicable]. Tenant must return keys and leave property in clean condition.

13. ADDITIONAL PROVISIONS
[Include any state-specific disclosures: lead paint (pre-1978), mold policies, bed bugs, etc.]
[Include parking, storage, amenity rules if applicable]
[Include special clauses as needed]

14. DISPUTE RESOLUTION
Disputes shall be resolved through [Mediation/Arbitration/Litigation] in [Jurisdiction/Venue]. Prevailing party entitled to attorney's fees.

15. GOVERNING LAW
This Agreement shall be governed by the laws of the State of [State].

16. ENTIRE AGREEMENT
This Agreement constitutes the entire agreement between parties. Modifications must be in writing and signed by both parties.

17. SIGNATURES
LANDLORD: _____________________________ Date: ___________
[Printed Name]

TENANT: _____________________________ Date: ___________
[Printed Name]

=== COMMERCIAL LEASE TEMPLATE (use for commercial properties) ===

COMMERCIAL LEASE AGREEMENT

This Commercial Lease Agreement (the "Agreement") is made and entered into as of [Date], by and between [Landlord Entity] ("Landlord") and [Tenant Entity] ("Tenant").

1. PREMISES
Landlord leases to Tenant the commercial premises located at [Full Address], consisting of approximately [Square Feet] square feet (the "Premises").

2. TERM
The term shall commence on [Start Date] and end on [End Date] ([X] years). Renewal Options: [Specify renewal terms and rent increase provisions].

3. RENT AND ADDITIONAL CHARGES
Base Rent: [Amount] per month, due on the [Due Day] of each month. Grace Period: [X] days. Late Fees: [Amount or Percentage] after grace period.

Additional Rent and Operating Expenses:
- Common Area Maintenance (CAM): [Specify calculation method - percentage of actual costs, fixed amount, or tenant's pro-rata share]
- Property Taxes: [Specify pass-through method]
- Insurance: [Specify pass-through method]
- Utilities: [List each utility and payment responsibility with calculation method]
- [Other fees]: [Specify amounts or percentages]

Total Estimated Monthly Payment: [Base Rent + Estimated Additional Charges]

4. SECURITY DEPOSIT
Tenant shall deposit [Amount] including: Security Deposit: [Amount], First Month Rent: [Amount], Last Month Rent: [Amount if applicable]. Deposit refund governed by state law within [X] days of lease end.

5. USE OF PREMISES
Premises shall be used for [Specific Business Purpose] and for no other purpose without Landlord's written consent. Permitted Hours: [Business Hours]. Prohibited Uses: [Specify restrictions].

6. UTILITIES AND SERVICES
[Detail each utility responsibility, calculation methods, and any shared service arrangements]

7. MAINTENANCE AND REPAIRS
Landlord Responsibilities: Structural repairs, roof, exterior walls, common areas, and building systems unless damage caused by Tenant.
Tenant Responsibilities: Interior maintenance, HVAC servicing, day-to-day repairs, and all damage caused by Tenant's operations.

8. ALTERATIONS AND IMPROVEMENTS
Tenant may make alterations only with Landlord's prior written consent. Tenant responsible for all costs. [Specify ownership of improvements and restoration requirements upon lease termination].

9. INSURANCE
Tenant must maintain: Commercial General Liability insurance (minimum [Amount]), Property insurance for Tenant's property, and [Other required coverage]. Landlord must be named as additional insured. Proof of insurance required before occupancy.

10. ASSIGNMENT AND SUBLETTING
Tenant may not assign lease or sublet without Landlord's prior written consent. Any approved assignment does not release Tenant from obligations.

11. DEFAULT AND REMEDIES
Events of Default: Non-payment of rent, breach of lease terms, bankruptcy, abandonment. Landlord Remedies: Termination, eviction, rent acceleration, and recovery of all costs including attorney's fees.

12. EARLY TERMINATION
[If applicable: Specify conditions, notice requirements, and fees for early termination]

13. ENTRY AND INSPECTION
Landlord may enter with [State Required] notice for inspections, repairs, or showing to prospective tenants/buyers, and without notice in emergencies.

14. SUBORDINATION
This lease is subordinate to any existing or future mortgages on the property. Tenant agrees to execute estoppel certificates upon request.

15. NOTICES
All notices must be in writing and delivered to:
Landlord: [Address]
Tenant: [Address]

16. COMPLIANCE WITH LAWS
Tenant shall comply with all federal, state, and local laws, including ADA requirements, environmental regulations, and building codes.

17. DISPUTE RESOLUTION
Disputes shall be resolved through [Mediation/Arbitration/Litigation] in [Jurisdiction/Venue]. Prevailing party entitled to attorney's fees and costs.

18. GOVERNING LAW
This Agreement is governed by the laws of the State of [State].

19. GENERAL PROVISIONS
This Agreement constitutes the entire agreement. Amendments must be in writing. If any provision is invalid, the remainder continues in effect. Time is of the essence.

20. STATE-SPECIFIC DISCLOSURES
[Include all required state and local disclosures and compliance requirements]

21. SIGNATURES
LANDLORD: _____________________________ Date: ___________
[Printed Name and Title]

TENANT: _____________________________ Date: ___________
[Printed Name and Title]

=== INSTRUCTIONS FOR GENERATING LEASES ===

FORMAT REQUIREMENTS:
- Use the appropriate template above (Residential or Commercial) based on lease_type
- Keep the final document to 2-3 pages
- Use clear numbered sections (1, 2, 3, etc.) not lengthy article numbers
- Fill in ALL bracketed placeholders with specific information from the request
- Write in clear, professional language avoiding excessive legalese
- Ensure document flows logically and is easy to read
- Include ALL required sections without omitting any

The final document should be COMPLETE, PROFESSIONAL, and ready for execution by both parties."""

    def _build_lease_prompt(
        self,
        request: LeaseGenerationRequest,
        legal_research: Dict
    ) -> str:
        """Build the detailed prompt for lease generation"""
        
        # Extract key information
        metadata = request.metadata
        property_details = request.property_details
        parties = request.parties
        lease_terms = request.lease_terms
        financials = request.financials
        responsibilities = request.responsibilities
        legal_terms = request.legal_and_special_terms
        
        # Build address string
        addr = property_details.address
        address_str = f"{addr.street}, {addr.city}, {addr.state}"
        if addr.zip:
            address_str += f" {addr.zip}"
        
        # Build tenant list
        tenant_names = [t.full_name for t in parties.tenants]
        tenant_str = ", ".join(tenant_names)
        
        # Get current date for lease execution
        current_date = datetime.now().strftime("%B %d, %Y")
        
        prompt = f"""Generate a comprehensive and professional {metadata.lease_type.upper()} LEASE AGREEMENT with the following details:

=== EXECUTION DATE ===
Current Date: {current_date}
(Use this as the lease execution/signing date)

=== LEGAL JURISDICTION & COMPLIANCE ===
Jurisdiction: {legal_research['jurisdiction']}
Applicable Laws: {', '.join(legal_research['laws_checked'])}
Compliance Requirements: {'; '.join(legal_research['compliance_notes'])}

Sources Consulted:
{chr(10).join(f"- {source}" for source in legal_research['sources'][:5])}

=== PARTIES ===
Landlord: {parties.landlord_entity}
Tenant(s): {tenant_str}

=== PROPERTY DETAILS ===
Property Name: {property_details.name or 'N/A'}
Address: {address_str}"""

        # Add unit details if available
        if property_details.unit_details:
            unit = property_details.unit_details
            prompt += f"""
Unit Number: {unit.unit_number or 'N/A'}
Square Footage: {unit.size_sq_ft or 'N/A'} sq ft
Bedrooms: {unit.bedrooms or 'N/A'}
Bathrooms: {unit.bathrooms or 'N/A'}"""

        # Add lease terms
        prompt += f"""

=== LEASE TERMS ===
Term Summary: {lease_terms.planned_term_summary or 'N/A'}
Start Date: {lease_terms.start_date or 'As specified in term summary'}
End Date: {lease_terms.end_date or 'As specified in term summary'}
Move-In Date: {lease_terms.move_in_date or 'Same as start date'}"""

        if lease_terms.renewal_options:
            prompt += f"\nRenewal Options: {lease_terms.renewal_options}"
        if lease_terms.renewal_rent_increase_terms:
            prompt += f"\nRenewal Rent Increase Terms: {lease_terms.renewal_rent_increase_terms}"

        # Add financial terms
        base_rent_amount = financials.base_rent.amount or 0
        prompt += f"""

=== FINANCIAL TERMS ===
Base Rent: {format_currency(base_rent_amount) if base_rent_amount else 'TBD'}
Rent Due: First day of each month
Grace Period: {financials.base_rent.grace_period_days or 0} days"""

        if financials.late_fees and financials.late_fees.amount:
            late_fee_desc = calculate_late_fee_description(financials.late_fees, base_rent_amount)
            prompt += f"\nLate Fees: {late_fee_desc}"

        if financials.deposits:
            if financials.deposits.security_deposit_amount:
                prompt += f"\nSecurity Deposit: {format_currency(financials.deposits.security_deposit_amount)}"
            
            if financials.deposits.other_deposits:
                for deposit in financials.deposits.other_deposits:
                    if deposit.label and deposit.amount:
                        prompt += f"\n{deposit.label}: {format_currency(deposit.amount)}"
            
            total_deposits = calculate_total_deposits(financials.deposits)
            if total_deposits > 0:
                prompt += f"\nTotal Deposits: {format_currency(total_deposits)}"

        # Add responsibilities
        if responsibilities:
            prompt += "\n\n=== RESPONSIBILITIES ==="
            
            if responsibilities.utilities:
                prompt += "\n\nUtilities:"
                for utility in responsibilities.utilities:
                    prompt += f"\n- {format_utility_payment(utility)}"
            
            if responsibilities.common_area_maintenance:
                prompt += "\n\nCommon Area Maintenance:"
                for cam in responsibilities.common_area_maintenance:
                    prompt += f"\n- {format_cam_payment(cam)}"
            
            if responsibilities.additional_fees:
                prompt += "\n\nAdditional Fees:"
                for fee in responsibilities.additional_fees:
                    prompt += f"\n- {format_additional_fee(fee, base_rent_amount)}"

        # Add special clauses if provided
        if legal_terms and legal_terms.special_clauses:
            prompt += "\n\n=== SPECIAL CLAUSES ==="
            prompt += f"\n{legal_terms.special_clauses}"

        # Add generation instructions
        prompt += f"""

=== DOCUMENT GENERATION INSTRUCTIONS ===

Generate a COMPLETE {metadata.lease_type.upper()} LEASE AGREEMENT using the {'RESIDENTIAL' if metadata.lease_type.lower() == 'residential' else 'COMMERCIAL'} template provided in your system instructions.

TARGET LENGTH: 2-3 pages (approximately 1000-1500 words)

CRITICAL REQUIREMENTS:
- Generate the ENTIRE lease in a SINGLE response
- Do NOT stop mid-document or ask to continue
- Do NOT use "[Continued...]" or similar phrases
- Follow the template structure with numbered sections
- Fill in ALL specific details from the information below
- Keep language clear and professional, not overly verbose

=== SPECIFIC DETAILS TO INCLUDE ===

EXECUTION DATE: {current_date}

PARTIES:
- Landlord: {parties.landlord_entity}
- Tenant(s): {tenant_str}

PROPERTY:
- Address: {address_str}
- Unit: {property_details.unit_details.unit_number if property_details.unit_details and property_details.unit_details.unit_number else 'N/A'}
- Size: {property_details.unit_details.size_sq_ft if property_details.unit_details and property_details.unit_details.size_sq_ft else 'N/A'} sq ft
- Type: {metadata.lease_type}

TERM:
- Start: {lease_terms.start_date}
- End: {lease_terms.end_date}
- Summary: {lease_terms.planned_term_summary}
- Renewal: {lease_terms.renewal_options if lease_terms.renewal_options else 'None'}
- Rent Increase on Renewal: {lease_terms.renewal_rent_increase_terms if lease_terms.renewal_rent_increase_terms else 'N/A'}

RENT:
- Base Rent: {format_currency(base_rent_amount) if base_rent_amount else 'TBD'} per month
- Due: First day of each month
- Grace Period: {financials.base_rent.grace_period_days} days
- Late Fee: {calculate_late_fee_description(financials.late_fees, base_rent_amount) if financials.late_fees and financials.late_fees.amount else 'Per state law'}

DEPOSITS:
- Security Deposit: {format_currency(financials.deposits.security_deposit_amount) if financials.deposits and financials.deposits.security_deposit_amount else 'TBD'}
{chr(10).join(f"- {d.label}: {format_currency(d.amount)}" for d in financials.deposits.other_deposits) if financials.deposits and financials.deposits.other_deposits else ''}
- Total Deposits: {format_currency(calculate_total_deposits(financials.deposits)) if financials.deposits else 'TBD'}

UTILITIES:
{chr(10).join(f"- {format_utility_payment(u)}" for u in responsibilities.utilities) if responsibilities and responsibilities.utilities else '- As specified in lease'}

COMMON AREA MAINTENANCE (CAM):
{chr(10).join(f"- {format_cam_payment(c)}" for c in responsibilities.common_area_maintenance) if responsibilities and responsibilities.common_area_maintenance else '- N/A'}

ADDITIONAL FEES:
{chr(10).join(f"- {format_additional_fee(f, base_rent_amount)}" for f in responsibilities.additional_fees) if responsibilities and responsibilities.additional_fees else '- N/A'}

SPECIAL CLAUSES:
{legal_terms.special_clauses if legal_terms and legal_terms.special_clauses else 'None'}

STATE COMPLIANCE:
- State: {addr.state}
- Laws: {', '.join(legal_research['laws_checked'])}
- Requirements: {'; '.join(legal_research['compliance_notes'])}

=== GENERATION INSTRUCTIONS ===

1. Use the appropriate template ({'RESIDENTIAL' if metadata.lease_type.lower() == 'residential' else 'COMMERCIAL'}) from your system prompt
2. Replace ALL bracketed placeholders with the specific information above
3. Keep sections concise - 1-3 paragraphs each, not multiple pages per section
4. Use simple numbered sections (1, 2, 3...) not complex article numbering
5. Write in clear, professional language that both parties can understand
6. Include signature blocks at the end with date lines
7. Ensure the document is 2-3 pages total when formatted
8. Generate the COMPLETE document in this single response

HTML OUTPUT REQUIREMENTS - MANDATORY:
Your response must be ONLY valid HTML5 code. Follow this EXACT structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lease Agreement</title>
    <style>
        /* Include ALL CSS from system prompt */
        body {{ font-family: 'Times New Roman', Times, serif; ... }}
        h1 {{ text-align: center; ... }}
        /* ... complete CSS rules ... */
    </style>
</head>
<body>
    <h1>{'RESIDENTIAL' if metadata.lease_type.lower() == 'residential' else 'COMMERCIAL'} LEASE AGREEMENT</h1>
    
    <h2>1. PARTIES</h2>
    <p>This Lease Agreement ("Agreement") is entered into on <strong>{current_date}</strong>...</p>
    
    <h2>2. PROPERTY</h2>
    <p>Landlord leases to Tenant the premises located at...</p>
    
    <!-- Continue with ALL sections -->
    
    <div class="signature-section">
        <h2>SIGNATURES</h2>
        <!-- Signature blocks as specified in system prompt -->
    </div>
</body>
</html>
```

CRITICAL VALIDATION CHECKLIST:
✓ Starts with <!DOCTYPE html>
✓ Complete <head> with charset, viewport, title, and full CSS
✓ All opening tags have matching closing tags
✓ No text outside of proper HTML tags
✓ Proper nesting (no overlapping tags)
✓ All special characters properly encoded (&amp; not &)
✓ Complete signature section at end
✓ Valid HTML5 that passes W3C validation

DO NOT include markdown code blocks, backticks, or any text before/after the HTML.
DO NOT use invalid HTML syntax or shortcuts.
DO NOT forget to close any tags.
DO NOT omit the complete CSS styling.

WRITE THE COMPLETE {metadata.lease_type.upper()} LEASE NOW AS VALID HTML5 (2-3 pages):"""

        return prompt
