"""Pytest configuration and shared fixtures"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
import sys
import os

# Add app to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def client():
    """FastAPI test client fixture"""
    from app.main import app
    return TestClient(app)


@pytest.fixture
def mock_bedrock_client():
    """Mock Bedrock client for testing without AWS calls"""
    with patch('app.bedrock_client.BedrockClient') as mock:
        mock_instance = Mock()
        mock_instance.analyze_lease_violations.return_value = {
            "lease_info": {
                "address": "123 Test St",
                "city": "Columbus",
                "state": "Ohio",
                "county": "Franklin",
                "landlord": "Test Landlord",
                "tenant": "Test Tenant",
                "rent_amount": "$1000",
                "security_deposit": "$1500",
                "lease_duration": "12 months",
                "full_text": "Test lease text"
            },
            "violations": [],
            "citations": [],
            "metrics": {
                "total_violations": 0,
                "gov_citations": 0,
                "total_citations": 0,
                "cost": 0.01,
                "time_seconds": 1.0
            }
        }
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def sample_lease_pdf():
    """Sample PDF content for testing"""
    # Minimal valid PDF
    return b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test Lease) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
307
%%EOF"""


@pytest.fixture
def sample_maintenance_request():
    """Sample maintenance request for testing"""
    return {
        "maintenance_request": "The heating system is broken and not producing heat.",
        "property_address": "123 Main St, Apt 4B",
        "lease_text": "Landlord is responsible for maintaining all heating systems in working order."
    }


@pytest.fixture
def sample_lease_text():
    """Sample lease text for testing"""
    return """
    RESIDENTIAL LEASE AGREEMENT
    
    Property Address: 123 Main Street, Apt 4B, Columbus, Ohio 43215
    County: Franklin County
    
    Landlord: ABC Property Management LLC
    Tenant: John Smith
    
    Monthly Rent: $1,200
    Security Deposit: $1,800
    Lease Term: 12 months beginning January 1, 2026
    
    TERMS AND CONDITIONS:
    
    1. RENT: Tenant shall pay rent of $1,200 on the 1st of each month.
    
    2. SECURITY DEPOSIT: A security deposit of $1,800 is required.
    
    3. MAINTENANCE: Landlord shall maintain all heating, plumbing, and electrical systems
       in good working order. Tenant is responsible for minor repairs under $50.
    
    4. LATE FEES: Rent not received by the 5th of the month will incur a $50 late fee.
    
    5. PET POLICY: No pets allowed without written permission. Pet deposit is $300.
    """
