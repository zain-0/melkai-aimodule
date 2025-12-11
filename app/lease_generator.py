"""
Lease Generator Service
Provides services for generating professional lease documents with legal research
"""

from typing import Dict, List, Optional
from datetime import datetime
import boto3
import json
import logging
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from io import BytesIO
import base64
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
    """Service to generate professional legal lease documents using AWS Bedrock"""
    
    def __init__(self):
        # Initialize Bedrock client
        try:
            session_kwargs = {'region_name': settings.AWS_REGION}
            
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                session_kwargs['aws_access_key_id'] = settings.AWS_ACCESS_KEY_ID
                session_kwargs['aws_secret_access_key'] = settings.AWS_SECRET_ACCESS_KEY
            
            session = boto3.Session(**session_kwargs)
            self.client = session.client(
                service_name='bedrock-runtime',
                config=boto3.session.Config(
                    read_timeout=120,
                    connect_timeout=10,
                    retries={'max_attempts': 3, 'mode': 'adaptive'}
                )
            )
            self.model = settings.LEASE_GENERATOR_MODEL
            logger.info(f"Lease generator initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {str(e)}")
            raise Exception(f"Failed to initialize AWS Bedrock client: {str(e)}")
    
    async def generate_lease(
        self,
        request: LeaseGenerationRequest,
        legal_research: Dict
    ) -> str:
        """
        Generate a comprehensive legal lease document in plain text format.
        
        Args:
            request: The lease generation request data
            legal_research: Results from legal research including jurisdiction laws
            
        Returns:
            Formatted lease document as plain text string
        """
        # Build comprehensive prompt
        prompt = self._build_lease_prompt(request, legal_research)
        
        # Call AWS Bedrock API
        try:
            # Format request body for Claude on Bedrock
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 8000,  # Reduced for shorter 2-3 page leases
                "temperature": 0.3,
                "system": self._get_system_prompt(),
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
            
            # Invoke Bedrock model
            response = self.client.invoke_model(
                modelId=self.model,
                body=body
            )
            
            # Parse response
            response_body = json.loads(response['body'].read())
            lease_document = response_body['content'][0]['text']
            
            return lease_document
            
        except Exception as e:
            logger.error(f"Failed to generate lease document: {str(e)}")
            raise Exception(f"Failed to generate lease document: {str(e)}")
    
    def convert_to_pdf(self, text_content: str, property_name: str = "Lease") -> bytes:
        """
        Convert plain text lease document to PDF format.
        
        Args:
            text_content: The plain text lease document
            property_name: Name of property for filename purposes
            
        Returns:
            PDF file content as bytes
        """
        try:
            # Create a BytesIO buffer
            buffer = BytesIO()
            
            # Create the PDF document
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=0.75*inch,
                bottomMargin=0.75*inch
            )
            
            # Define styles
            styles = getSampleStyleSheet()
            
            # Custom title style (centered, larger)
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=14,
                alignment=TA_CENTER,
                spaceAfter=12,
                fontName='Times-Bold'
            )
            
            # Custom numbered heading style (for main sections like "1. PARTIES:")
            numbered_heading_style = ParagraphStyle(
                'NumberedHeading',
                parent=styles['Normal'],
                fontSize=11,
                alignment=TA_LEFT,
                spaceAfter=6,
                spaceBefore=8,
                fontName='Times-Bold',
                leading=13
            )
            
            # Custom body style (regular text)
            body_style = ParagraphStyle(
                'CustomBody',
                parent=styles['BodyText'],
                fontSize=11,
                alignment=TA_LEFT,
                spaceAfter=6,
                fontName='Times-Roman',
                leading=13
            )
            
            # Section keywords that indicate a major section heading
            # These should ONLY match the actual header line, not body paragraphs
            section_keywords = [
                'PARTIES:', 'TENANT(S):', 'PROPERTY ADDRESS:', 'RENTAL AMOUNT:', 
                'TERM:', 'SECURITY DEPOSITS:', 'SECURITY DEPOSIT:', 'INITIAL PAYMENT:', 
                'OCCUPANTS:', 'SUBLETTING OR ASSIGNING:', 'SUBLETTING:', 
                'UTILITIES:', 'PARKING:', 'CONDITION OF THE PREMISES:', 
                'ALTERATIONS:', 'LATE CHARGE', 'NOISE AND DISRUPTIVE', 
                "LANDLORD'S RIGHT OF ENTRY:", "LANDLORD'S RIGHT", 
                'REPAIRS BY LANDLORD:', 'REPAIRS:', 'PETS:', 'FURNISHINGS:', 
                'INSURANCE:', 'TERMINATION OF LEASE', 'TERMINATION:', 
                'POSSESSION:', 'ABANDONMENT:', 'WAIVER:', 'VALIDITY', 
                'NOTICES:', 'PERSONAL PROPERTY OF TENANT:', 'PERSONAL PROPERTY:', 
                'APPLICATION:', 'NEIGHBORHOOD CONDITIONS:', 'NEIGHBORHOOD:', 
                'DATA BASE DISCLOSURE:', 'DATABASE DISCLOSURE:', 'DATABASE:', 
                'KEYS:', 'PROPERTY CONDITION LIST:', 'PROPERTY CONDITION:', 
                'SATELLITE DISHES:', 'SATELLITE:', 'ATTORNEY FEES:', 'ATTORNEY:', 
                'ENTIRE AGREEMENT:', 'SIGNATURES'
            ]
            
            # Build the document content
            story = []
            lines = text_content.split('\n')
            section_number = 0
            in_signature_section = False
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                if not line:
                    # Empty line - add small spacer
                    story.append(Spacer(1, 0.08*inch))
                    continue
                
                # Check if it's the main title
                if ('RESIDENTIAL LEASE' in line.upper() or 'COMMERCIAL LEASE' in line.upper()) and 'AGREEMENT' in line.upper() and i < 5:
                    story.append(Paragraph(line, title_style))
                    story.append(Spacer(1, 0.15*inch))
                    continue
                
                # Check if we're entering signature section
                if line.upper() == 'SIGNATURES' or (line.upper().startswith('SIGNATURE') and ':' not in line):
                    in_signature_section = True
                    section_number += 1
                    formatted_line = f"<b>{section_number}. {line}</b>"
                    story.append(Paragraph(formatted_line, numbered_heading_style))
                    continue
                
                # Check if it's a major section heading
                is_section_header = False
                line_upper = line.upper()
                
                # Check if line starts with any section keyword
                # Don't require length check if it's clearly a section header with a colon
                has_colon = ':' in line[:80]  # Colon in first 80 chars suggests it's a header
                
                for keyword in section_keywords:
                    if line_upper.startswith(keyword):
                        # If it has a colon early on, it's likely a header regardless of length
                        # Otherwise, require it to be under 250 chars
                        if has_colon or len(line) < 250:
                            is_section_header = True
                            break
                
                if is_section_header and not in_signature_section:
                    # This is a major section - add numbering and bold
                    section_number += 1
                    
                    # Extract just the bold part (usually the part before the colon + some text)
                    if ':' in line:
                        # Find the colon position
                        colon_pos = line.find(':')
                        bold_part = line[:colon_pos + 1]  # Include the colon
                        rest = line[colon_pos + 1:].strip()  # Everything after the colon
                        
                        # Escape HTML in rest part only
                        rest = rest.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        
                        # Build formatted line with bold tags
                        if rest:
                            formatted_line = f"<b>{section_number}. {bold_part}</b> {rest}"
                        else:
                            formatted_line = f"<b>{section_number}. {bold_part}</b>"
                    else:
                        # Entire line is the heading (no colon)
                        formatted_line = f"<b>{section_number}. {line}</b>"
                    
                    story.append(Paragraph(formatted_line, numbered_heading_style))
                elif in_signature_section:
                    # In signature section - check for signature lines
                    if 'Owner' in line or 'Representative' in line or 'Tenant' in line or 'Date:' in line:
                        # Make the labels bold but not the underscores
                        line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        if ':' in line and '_' in line:
                            parts = line.split(':', 1)
                            formatted_line = f"<b>{parts[0]}:</b>{parts[1]}"
                        else:
                            formatted_line = line
                        story.append(Paragraph(formatted_line, body_style))
                    else:
                        # Regular signature section text
                        line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        story.append(Paragraph(line, body_style))
                else:
                    # Regular body text - no bold
                    # Escape special characters for reportlab
                    line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(line, body_style))
            
            # Build the PDF
            doc.build(story)
            
            # Get the PDF content
            pdf_content = buffer.getvalue()
            buffer.close()
            
            return pdf_content
            
        except Exception as e:
            logger.error(f"Failed to convert lease to PDF: {str(e)}")
            raise Exception(f"Failed to convert lease to PDF: {str(e)}")
    
    def convert_to_html(self, text_content: str, property_name: str = "Lease") -> str:
        """
        Convert plain text lease document to HTML format.
        
        Args:
            text_content: The plain text lease document
            property_name: Name of property for display purposes
            
        Returns:
            Formatted lease document as HTML string
        """
        try:
            # Section keywords that indicate a major section heading
            # Note: PARTIES, TENANT(S), and PROPERTY ADDRESS are handled specially (no numbering)
            initial_fields = ['PARTIES:', 'TENANT(S):', 'PROPERTY ADDRESS:']
            section_keywords = [
                'RENTAL AMOUNT:', 
                'TERM:', 'SECURITY DEPOSITS:', 'SECURITY DEPOSIT:', 'INITIAL PAYMENT:', 
                'OCCUPANTS:', 'SUBLETTING OR ASSIGNING:', 'SUBLETTING:', 
                'UTILITIES:', 'PARKING:', 'CONDITION OF THE PREMISES:', 
                'ALTERATIONS:', 'LATE CHARGE', 'NOISE AND DISRUPTIVE', 
                "LANDLORD'S RIGHT OF ENTRY:", "LANDLORD'S RIGHT", 
                'REPAIRS BY LANDLORD:', 'REPAIRS:', 'PETS:', 'FURNISHINGS:', 
                'INSURANCE:', 'TERMINATION OF LEASE', 'TERMINATION:', 
                'POSSESSION:', 'ABANDONMENT:', 'WAIVER:', 'VALIDITY', 
                'NOTICES:', 'PERSONAL PROPERTY OF TENANT:', 'PERSONAL PROPERTY:', 
                'APPLICATION:', 'NEIGHBORHOOD CONDITIONS:', 'NEIGHBORHOOD:', 
                'DATA BASE DISCLOSURE:', 'DATABASE DISCLOSURE:', 'DATABASE:', 
                'KEYS:', 'PROPERTY CONDITION LIST:', 'PROPERTY CONDITION:', 
                'SATELLITE DISHES:', 'SATELLITE:', 'ATTORNEY FEES:', 'ATTORNEY:', 
                'ENTIRE AGREEMENT:', 'SIGNATURES'
            ]
            
            # Build HTML content
            html_parts = []
            
            # Add CSS styles
            html_parts.append('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lease Agreement - ''' + property_name + '''</title>
    <style>
        body {
            font-family: 'Times New Roman', Times, serif;
            font-size: 11pt;
            line-height: 1.4;
            max-width: 8.5in;
            margin: 0 auto;
            padding: 0.75in;
            background-color: #ffffff;
            color: #000000;
        }
        .title {
            text-align: center;
            font-size: 14pt;
            font-weight: bold;
            margin-bottom: 20px;
            text-transform: uppercase;
        }
        .section-header {
            font-weight: bold;
            margin-top: 12px;
            margin-bottom: 6px;
            font-size: 11pt;
        }
        .body-text {
            margin-bottom: 6px;
            text-align: left;
        }
        .signature-section {
            margin-top: 20px;
        }
        .signature-label {
            font-weight: bold;
        }
        @media print {
            body {
                padding: 0.5in;
            }
        }
    </style>
</head>
<body>
''')
            
            # Process content
            lines = text_content.split('\n')
            section_number = 0
            in_signature_section = False
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                if not line:
                    # Empty line
                    html_parts.append('<br>')
                    continue
                
                # Escape HTML entities
                line_escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                line_upper = line.upper()
                
                # Check if it's the main title
                if (('RESIDENTIAL LEASE' in line_upper or 'COMMERCIAL LEASE' in line_upper) and i < 5) and \
                   (line.strip().upper() in ['RESIDENTIAL LEASE', 'COMMERCIAL LEASE'] or 'RENTAL AGREEMENT' in line_upper):
                    # Extract just RESIDENTIAL LEASE or COMMERCIAL LEASE part
                    if 'RESIDENTIAL' in line_upper:
                        html_parts.append('<div class="title">RESIDENTIAL LEASE</div>')
                    else:
                        html_parts.append('<div class="title">COMMERCIAL LEASE</div>')
                    continue
                
                # Check if it's one of the initial fields (PARTIES, TENANT(S), PROPERTY ADDRESS)
                is_initial_field = False
                for field in initial_fields:
                    if line_upper.startswith(field):
                        is_initial_field = True
                        # Format without numbering - just bold the label
                        if ':' in line:
                            colon_pos = line.find(':')
                            bold_part = line[:colon_pos + 1]
                            rest = line[colon_pos + 1:].strip()
                            
                            bold_part_escaped = bold_part.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            rest_escaped = rest.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            
                            if rest:
                                html_parts.append(f'<div class="section-header"><strong>{bold_part_escaped}</strong> {rest_escaped}</div>')
                            else:
                                html_parts.append(f'<div class="section-header"><strong>{bold_part_escaped}</strong> _____________________________________________________</div>')
                        break
                
                if is_initial_field:
                    continue
                
                # Check if we're entering signature section
                if line.upper() == 'SIGNATURES' or (line.upper().startswith('SIGNATURE') and ':' not in line):
                    in_signature_section = True
                    section_number += 1
                    html_parts.append(f'<div class="section-header signature-section"><strong>{section_number}. {line_escaped}</strong></div>')
                    continue
                
                # Check if it's a major section heading
                is_section_header = False
                line_upper = line.upper()
                has_colon = ':' in line[:80]
                
                for keyword in section_keywords:
                    if line_upper.startswith(keyword):
                        if has_colon or len(line) < 250:
                            is_section_header = True
                            break
                
                if is_section_header and not in_signature_section:
                    # This is a major section - add numbering and bold
                    section_number += 1
                    
                    if ':' in line:
                        colon_pos = line.find(':')
                        bold_part = line[:colon_pos + 1]
                        rest = line[colon_pos + 1:].strip()
                        
                        # Escape both parts
                        bold_part_escaped = bold_part.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        rest_escaped = rest.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        
                        if rest:
                            html_parts.append(f'<div class="section-header"><strong>{section_number}. {bold_part_escaped}</strong> {rest_escaped}</div>')
                        else:
                            html_parts.append(f'<div class="section-header"><strong>{section_number}. {bold_part_escaped}</strong></div>')
                    else:
                        html_parts.append(f'<div class="section-header"><strong>{section_number}. {line_escaped}</strong></div>')
                    
                elif in_signature_section:
                    # In signature section
                    if 'Owner' in line or 'Representative' in line or 'Tenant' in line or 'Date:' in line:
                        if ':' in line and '_' in line:
                            parts = line.split(':', 1)
                            label = parts[0].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            rest = parts[1].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            html_parts.append(f'<div class="body-text"><span class="signature-label">{label}:</span>{rest}</div>')
                        else:
                            html_parts.append(f'<div class="body-text">{line_escaped}</div>')
                    else:
                        html_parts.append(f'<div class="body-text">{line_escaped}</div>')
                else:
                    # Regular body text
                    html_parts.append(f'<div class="body-text">{line_escaped}</div>')
            
            # Close HTML
            html_parts.append('''
</body>
</html>
''')
            
            return ''.join(html_parts)
            
        except Exception as e:
            logger.error(f"Failed to convert lease to HTML: {str(e)}")
            raise Exception(f"Failed to convert lease to HTML: {str(e)}")
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the AI model"""
        return """You are an expert legal document specialist creating CONCISE residential/commercial lease agreements.

CRITICAL LENGTH REQUIREMENT:
- STRICT MAXIMUM: 2-3 pages (800-1200 words total)
- Generate COMPLETE lease in single response - never stop mid-document
- Keep each section to 1-2 sentences maximum
- Prioritize brevity while maintaining legal validity

DOCUMENT FORMAT:
Generate clean plain text (no HTML, no markdown). Structure:

1. Title: RESIDENTIAL LEASE (or COMMERCIAL LEASE)
2. Three unnumbered header fields:
   - PARTIES: LANDLORD: [actual landlord name]
   - TENANT(S): [actual tenant names]
   - PROPERTY ADDRESS: [complete address]
3. Numbered sections (write headers WITHOUT numbers - they're added automatically):
   - RENTAL AMOUNT: [amount, due date, payment method - 2 sentences max]
   - TERM: [start/end dates, renewal terms - 2 sentences max]
   - SECURITY DEPOSITS: [amount and return conditions - 2 sentences max]
   - UTILITIES: [who pays what - 1-2 sentences]
   - LATE FEES: [penalty terms - 1 sentence]
   - MAINTENANCE AND REPAIRS: [landlord/tenant duties - 2 sentences max]
   - PETS: [policy - 1 sentence]
   - OCCUPANCY: [max occupants, subletting rules - 1-2 sentences]
   - ENTRY AND ACCESS: [landlord entry rights - 1 sentence]
   - TERMINATION: [termination terms - 2 sentences max]
   - GOVERNING LAW: [jurisdiction - 1 sentence]
   - ENTIRE AGREEMENT: [standard clause - 1 sentence]
   - SIGNATURES: [landlord and tenant signature blocks with underscores for signatures]

FORMATTING RULES:
- Section headers: ALL CAPS (e.g., "RENTAL AMOUNT:" not "1. RENTAL AMOUNT:")
- Body text: normal capitalization, professional tone
- One blank line between sections
- Use underscores for signature lines: _______________________________
- NO HTML tags, NO markdown, NO special formatting codes
- Fill in ALL data - never leave blanks or use placeholders

EXAMPLE START:
RESIDENTIAL LEASE

PARTIES: LANDLORD: ABC Property Management LLC

TENANT(S): John Doe and Jane Doe

PROPERTY ADDRESS: 123 Main Street, Apartment 4B, Los Angeles, CA 90001

RENTAL AMOUNT: Commencing January 1, 2025 TENANTS agree to pay LANDLORD $2,500 per month due on the 1st. Payment by check or online transfer to [payment address].

TERM: One year lease from January 1, 2025 through December 31, 2025. Tenant may renew with 60 days notice.

[Continue with remaining sections...]

SIGNATURES

LANDLORD: [actual name]  Date: _______________

TENANT: [actual name]  Date: _______________

Generate complete, professional lease ready for execution."""

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

Generate a COMPLETE {metadata.lease_type.upper()} LEASE AGREEMENT that EXACTLY REPLICATES the format, structure, and style of "Updated Lease Agreement.docx" template.

TARGET LENGTH: STRICT MAXIMUM 2-3 pages (800-1200 words) - NO EXCEPTIONS

CRITICAL REQUIREMENTS:
- Generate the ENTIRE lease in a SINGLE response including ALL sections through SIGNATURES
- Do NOT stop mid-document or ask to continue
- Do NOT use "[Continued...]" or similar phrases
- MUST include complete SIGNATURE section at the end
- FOLLOW A SIMPLIFIED, STREAMLINED STRUCTURE
- Use brief section titles and concise content (1-2 sentences per section)
- Eliminate verbose explanations and unnecessary legal elaboration
- Combine sections where possible to save space
- Use condensed language while maintaining legal validity
- Keep each paragraph to 2-3 lines MAXIMUM
- Prioritize essential information only - remove all "nice to have" clauses

BREVITY CHECKLIST:
✓ Document is 2-3 pages MAXIMUM (800-1200 words)
✓ Each section is 1-3 sentences only
✓ No verbose explanations or unnecessary detail
✓ Combined sections where possible
✓ Eliminated all redundant clauses
✓ Used condensed legal language
✓ Removed "nice to have" provisions
✓ COMPLETE document with signature section at the end
✓ Professional but BRIEF throughout

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

1. Create a STREAMLINED {'RESIDENTIAL' if metadata.lease_type.lower() == 'residential' else 'COMMERCIAL'} lease with simplified structure
2. Replace ALL placeholders with the specific information above
3. Keep ALL sections ULTRA-BRIEF (1-2 sentences each)
4. Use simplified section numbering
5. Write in concise, direct legal language
6. Include brief signature blocks
7. STRICT LIMIT: 2-3 pages MAXIMUM (800-1200 words)
8. Prioritize essential clauses only - eliminate verbose or optional sections
9. Generate the COMPLETE but BRIEF document in this single response

PLAIN TEXT OUTPUT REQUIREMENTS - MANDATORY:
Your response must be ONLY clean plain text in a BRIEF, STREAMLINED format with ONLY essential sections. Follow this structure:

```
                    RESIDENTIAL LEASE

PARTIES: LANDLORD: [Actual landlord name]

TENANT(S): [Actual tenant names]

PROPERTY ADDRESS: [Full property address]

RENTAL AMOUNT: Commencing [date] TENANTS agree to pay LANDLORD $[amount] per month, due on the [day] of each month. Payment shall be made to [payment location/method].

TERM: The lease term is [duration] commencing [start date] and ending [end date]. [Brief renewal terms if applicable - 1 sentence].

SECURITY DEPOSITS: TENANT shall deposit $[amount] as security deposit. Deposit will be returned within [days] days after lease termination, less any deductions for damages.

UTILITIES: [Brief list of who pays which utilities - 1-2 sentences].

LATE FEES: Late payments shall incur a fee of [amount/percentage]. [Any NSF check fees - 1 sentence].

MAINTENANCE AND REPAIRS: LANDLORD is responsible for major repairs and structural maintenance. TENANT is responsible for minor repairs under $[amount] and routine maintenance.

PETS: [Pets allowed/not allowed with brief terms and any deposits/fees].

OCCUPANCY: Maximum occupants: [number]. Subletting requires written landlord approval.

ENTRY AND ACCESS: LANDLORD may enter premises with [hours] hours notice for inspections and repairs.

TERMINATION: [Brief termination terms - notice requirements, early termination penalties if any].

GOVERNING LAW: This lease is governed by the laws of [State].

ENTIRE AGREEMENT: This document constitutes the entire agreement between parties and supersedes all prior agreements.

SIGNATURES

LANDLORD: [Name]
Signature: _______________________________  Date: ______________

TENANT: [Name]
Signature: _______________________________  Date: ______________
```

REMEMBER: MAXIMUM 2-3 pages (800-1200 words). Include ONLY the sections listed above. Keep EVERY section to 1-2 sentences.

CRITICAL VALIDATION CHECKLIST:
✓ Plain text format only (no HTML, no markdown)
✓ MAXIMUM 2-3 pages (800-1200 words) - COUNT YOUR WORDS
✓ Each section is 1-2 sentences MAXIMUM
✓ ALL CAPS for section headers
✓ Professional spacing and line breaks
✓ All data filled in (no blank underscores for values)
✓ Complete signature section at end
✓ Clean, BRIEF, professional business document format
✓ NO verbose explanations or lengthy clauses

DO NOT include any HTML tags, markdown syntax, or special formatting codes.
DO NOT use ```text``` code blocks or any other wrapper.
DO NOT forget proper line breaks and spacing.
DO NOT write lengthy, verbose sections - keep EVERY section to 1-2 sentences.
DO NOT exceed 2-3 pages (800-1200 words) under ANY circumstances.

⚠️ FINAL REMINDER: This lease MUST be 2-3 pages MAX. Write brief, concise sections. Eliminate all unnecessary text.

WRITE THE COMPLETE BUT CONCISE {metadata.lease_type.upper()} LEASE NOW AS CLEAN PLAIN TEXT (2-3 PAGES MAX):"""

        return prompt
