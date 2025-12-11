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
                    read_timeout=60,  # Reduced for faster EC2-to-Bedrock calls
                    connect_timeout=5,  # Faster connection on AWS network
                    retries={'max_attempts': 2, 'mode': 'standard'}  # Fewer retries for speed
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
                "max_tokens": 4000,  # Increased for longer, more comprehensive leases (1600-2000 words)
                "temperature": 0.2,  # Lower for faster, more consistent output
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
                fontSize=13,
                alignment=TA_CENTER,
                spaceAfter=12,
                fontName='Times-Bold'
            )
            
            # Custom numbered heading style (for main sections like "1. PARTIES:")
            numbered_heading_style = ParagraphStyle(
                'NumberedHeading',
                parent=styles['Normal'],
                fontSize=10.5,
                alignment=TA_LEFT,
                spaceAfter=3,
                spaceBefore=6,
                fontName='Times-Bold',
                leading=12
            )
            
            # Custom body style (regular text)
            body_style = ParagraphStyle(
                'CustomBody',
                parent=styles['BodyText'],
                fontSize=11,
                alignment=TA_LEFT,
                spaceAfter=3,
                fontName='Times-Roman',
                leading=13
            )
            
            # Section keywords that indicate a major section heading
            # These should ONLY match the actual header line, not body paragraphs
            section_keywords = [
                'PARTIES:', 'LANDLORD:', 'TENANT(S):', 'PROPERTY ADDRESS:', 'RENTAL AMOUNT:', 
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
                    # Skip empty lines - spacing handled by paragraph styles
                    continue
                
                # Check if it's the main title
                if (('RESIDENTIAL LEASE' in line.upper() or 'COMMERCIAL LEASE' in line.upper()) and i < 5):
                    story.append(Paragraph(line, title_style))
                    story.append(Spacer(1, 0.08*inch))
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
                        # Check if it's just "Date:" on its own line
                        if line.strip() == 'Date:':
                            formatted_line = f"<b>{line}</b>"
                            story.append(Paragraph(formatted_line, body_style))
                        elif ':' in line and '_' in line:
                            # Make the labels bold but not the underscores
                            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            parts = line.split(':', 1)
                            formatted_line = f"<b>{parts[0]}:</b>{parts[1]}"
                            story.append(Paragraph(formatted_line, body_style))
                        else:
                            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            story.append(Paragraph(line, body_style))
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
            # Note: PARTIES, TENANT(S), LANDLORD, PROPERTY, and LEASE TERM are handled specially (no numbering, bold headers)
            initial_fields = ['PARTIES:', 'LANDLORD:', 'TENANT(S):', 'PROPERTY ADDRESS:', 'PROPERTY:', 'LEASE TERM:']
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
            
            # Add HTML header with inline styling only
            html_parts.append('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lease Agreement - ''' + property_name + '''</title>
</head>
<body style="font-family: 'Times New Roman', Times, serif; font-size: 10pt; line-height: 1.3; max-width: 8.5in; margin: 0 auto; padding: 0.75in; background-color: #ffffff; color: #000000;">
''')
            
            # Process content
            lines = text_content.split('\n')
            section_number = 0
            in_signature_section = False
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                if not line:
                    # Skip excessive empty lines - spacing handled by CSS
                    continue
                
                # Escape HTML entities
                line_escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                line_upper = line.upper()
                
                # Check if it's the main title
                if (('RESIDENTIAL LEASE' in line_upper or 'COMMERCIAL LEASE' in line_upper) and i < 5) and \
                   (line.strip().upper() in ['RESIDENTIAL LEASE', 'COMMERCIAL LEASE', 'RESIDENTIAL LEASE AGREEMENT', 'COMMERCIAL LEASE AGREEMENT'] or 'RENTAL AGREEMENT' in line_upper):
                    # Extract just RESIDENTIAL LEASE AGREEMENT or COMMERCIAL LEASE AGREEMENT part
                    if 'RESIDENTIAL' in line_upper:
                        html_parts.append('<div style="text-align: center; font-size: 10pt; font-weight: bold; margin-bottom: 12px; text-transform: uppercase;">RESIDENTIAL LEASE AGREEMENT</div>')
                    else:
                        html_parts.append('<div style="text-align: center; font-size: 10pt; font-weight: bold; margin-bottom: 12px; text-transform: uppercase;">COMMERCIAL LEASE AGREEMENT</div>')
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
                            
                            # PARTIES field should be completely blank - no underscore, even if AI added underscores
                            if 'PARTIES:' in bold_part_escaped:
                                # Strip out any underscores the AI may have added
                                html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{bold_part_escaped}</strong></div>')
                            elif rest and not rest.strip('_').strip():
                                # If rest is only underscores or whitespace, don't include it
                                html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{bold_part_escaped}</strong></div>')
                            elif rest:
                                html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{bold_part_escaped}</strong> {rest_escaped}</div>')
                            else:
                                html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{bold_part_escaped}</strong></div>')
                        break
                
                if is_initial_field:
                    continue
                
                # Check if we're entering signature section
                if line.upper() == 'SIGNATURES' or (line.upper().startswith('SIGNATURE') and ':' not in line):
                    in_signature_section = True
                    section_number += 1
                    html_parts.append(f'<div style="font-weight: bold; margin-top: 20px; margin-bottom: 3px; font-size: 10pt;"><strong>{section_number}. {line_escaped}</strong></div>')
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
                    # This is a major section - add numbering and bold ONLY the header, not the content
                    section_number += 1
                    
                    if ':' in line:
                        colon_pos = line.find(':')
                        bold_part = line[:colon_pos + 1]
                        rest = line[colon_pos + 1:].strip()
                        
                        # Escape both parts
                        bold_part_escaped = bold_part.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        rest_escaped = rest.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        
                        if rest:
                            html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{section_number}. {bold_part_escaped}</strong> {rest_escaped}</div>')
                        else:
                            html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{section_number}. {bold_part_escaped}</strong></div>')
                    else:
                        html_parts.append(f'<div style="margin-top: 8px; margin-bottom: 3px; font-size: 10pt;"><strong>{section_number}. {line_escaped}</strong></div>')
                    
                elif in_signature_section:
                    # In signature section
                    if 'Owner' in line or 'Representative' in line or 'Tenant' in line or 'Date:' in line:
                        # Check if it's just "Date:" on its own line (without underscore)
                        if line.strip() == 'Date:':
                            html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;"><span style="font-weight: bold;">{line_escaped}</span></div>')
                        elif ':' in line and '_' in line:
                            parts = line.split(':', 1)
                            label = parts[0].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            rest = parts[1].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;"><span style="font-weight: bold;">{label}:</span>{rest}</div>')
                        else:
                            html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;">{line_escaped}</div>')
                    else:
                        html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;">{line_escaped}</div>')
                else:
                    # Regular body text - check for markdown-style bold markers
                    # Convert **TEXT:** to proper HTML bold (same font size, just bold)
                    if line.startswith('**') and ':**' in line:
                        # This is a section header formatted with markdown
                        # Extract the header part
                        end_marker = line.find(':**')
                        if end_marker > 0:
                            header_text = line[2:end_marker+1]  # Remove ** and include :
                            rest_text = line[end_marker+2:].strip()
                            
                            header_escaped = header_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            rest_escaped = rest_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            
                            # Use inline styling for body text with bold (same size as body)
                            if rest_text:
                                html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;"><strong style="font-size: 10pt;">{header_escaped}</strong> {rest_escaped}</div>')
                            else:
                                html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;"><strong style="font-size: 10pt;">{header_escaped}</strong></div>')
                            continue
                    
                    # Remove any remaining ** markers and render as body text
                    cleaned_line = line_escaped.replace('**', '')
                    html_parts.append(f'<div style="margin-bottom: 3px; text-align: left; font-size: 10pt;">{cleaned_line}</div>')
            
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
        return """Expert legal document specialist. Generate COMPLETE, DETAILED residential/commercial lease agreements.

REQUIREMENTS:
Length: 1600-2000 words (3-4 pages)
Format: Plain text only, NO markdown, NO ** or special formatting
Complete document in single response with ALL sections through SIGNATURES
Each section: 4-6 sentences with comprehensive details in PARAGRAPH form
USE EXACT DATA FROM PROMPT, no random or placeholder values

STRUCTURE:
1. Title: RESIDENTIAL LEASE AGREEMENT or COMMERCIAL LEASE AGREEMENT
2. Initial fields (NO numbering, these are BOLD headers):
   PARTIES:
   LANDLORD: [exact name from prompt]
   TENANT(S): [exact names from prompt]
   PROPERTY: [Complete property description in single flowing paragraph format. Example: "The leased premises is a 2200 square foot, 4-bedroom, 3-bathroom residential unit located at 2847 Riverfront Drive, Unit 15, Sacramento, California 95814, known as Riverside Garden Townhomes." DO NOT use line-by-line format with "Property Name:", "Address:", "Unit Number:", etc.]
   LEASE TERM: [Complete lease term details in single flowing paragraph format]
3. Main sections (plain text, headers in UPPERCASE with colon): RENTAL AMOUNT: | SECURITY DEPOSITS: | UTILITIES: | LATE FEES: | MAINTENANCE AND REPAIRS: | PETS: | OCCUPANCY: | ENTRY AND ACCESS: | TERMINATION: | GOVERNING LAW: | ENTIRE AGREEMENT: | SIGNATURE

ABSOLUTE PROHIBITION ON BULLET POINTS AND LISTS:
NEVER use bullet points, dashes, asterisks, or any list formatting (-, *, •, ◦, ▪)
NEVER start lines with hyphens or symbols
Write ALL content in flowing paragraph format
When listing items, use inline comma-separated format within sentences
Example CORRECT: "Tenant is responsible for Electricity (actual costs), Gas (actual costs), Water (100% of actual monthly costs), Sewer (actual costs), Trash Collection at $45.00 monthly, and Internet/Cable."
Example WRONG: "- Electricity (actual costs)" or "* Gas (actual costs)"

CRITICAL FORMATTING RULES:
NO markdown formatting, NO ** or __ or special characters anywhere
Section headers: Plain text UPPERCASE like "RENTAL AMOUNT:" NOT "**RENTAL AMOUNT:**" or "Rental Amount:"
PARTIES: must be on its own line with NOTHING after the colon, completely blank
Example correct format:
  PARTIES:
  LANDLORD: Riverside Properties Inc.
  
PROPERTY: BOLD header (ALL CAPS), write description as single flowing paragraph, NOT line-by-line list format
Example CORRECT: "PROPERTY: The leased premises is a 2200 square foot, 4-bedroom, 3-bathroom residential unit located at 2847 Riverfront Drive, Unit 15, Sacramento, California 95814, known as Riverside Garden Townhomes."
Example WRONG: "PROPERTY:\nProperty Name: Riverside Garden Townhomes\nAddress: 2847 Riverfront Drive"

LEASE TERM: BOLD header (ALL CAPS), write term details as single flowing paragraph
Example CORRECT: "LEASE TERM: This lease shall commence on January 1, 2024 and continue for a period of twelve (12) months, terminating on December 31, 2024."

NO underscore lines anywhere EXCEPT in signature section
Headers: UPPERCASE with colon, plain text (e.g., "RENTAL AMOUNT:" not "rental amount:")
Body: Normal case, professional, in paragraph format only
No blank lines between sections
Use EXACT amounts, dates, names, and addresses from prompt
ALL sections must be in flowing paragraph format, never line-by-line lists

SIGNATURE SECTION FORMAT (ONLY place with underscores):
  SIGNATURE
  
  LANDLORD/OWNER:
  Signature: _______________________________
  Print Name: [exact name]
  Date: _______________________________
  
  TENANT:
  Signature: _______________________________
  Print Name: [exact name]
  Date: _______________________________

IMPORTANT: Include "SIGNATURE" as a header before the signature section. Do NOT fill in the date field - leave it as blank underscore line on SAME line as "Date:". The date will be filled in manually when signed.

Generate complete, brief, professional lease now."""

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

=== GENERATE COMPLETE {metadata.lease_type.upper()} LEASE ===

Use all details above. 800-1200 words. Plain text, no blank lines between sections. Generate now:"""

        return prompt
