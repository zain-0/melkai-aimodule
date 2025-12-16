#!/usr/bin/env python3
"""
Health Check Script for MelkAI Module
Tests if the application is running and healthy
"""

import sys
import requests
import time
from typing import Tuple

# Configuration
API_HOST = "18.119.209.125"  # Your EC2 IP
API_PORT = "8000"
HEALTH_ENDPOINT = f"http://{API_HOST}:{API_PORT}/health"
DOCS_ENDPOINT = f"http://{API_HOST}:{API_PORT}/docs"
TIMEOUT = 10


def check_health() -> Tuple[bool, str]:
    """Check if the API health endpoint responds"""
    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return True, f"✓ API is healthy: {data}"
        else:
            return False, f"✗ Health check failed with status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, f"✗ Cannot connect to {HEALTH_ENDPOINT}"
    except requests.exceptions.Timeout:
        return False, f"✗ Request timed out after {TIMEOUT} seconds"
    except Exception as e:
        return False, f"✗ Error: {str(e)}"


def check_docs() -> Tuple[bool, str]:
    """Check if the API documentation is accessible"""
    try:
        response = requests.get(DOCS_ENDPOINT, timeout=TIMEOUT)
        if response.status_code == 200:
            return True, f"✓ API docs accessible at {DOCS_ENDPOINT}"
        else:
            return False, f"✗ Docs check failed with status {response.status_code}"
    except Exception as e:
        return False, f"✗ Cannot access docs: {str(e)}"


def main():
    """Run all health checks"""
    print("=" * 60)
    print("MelkAI Module - Health Check")
    print("=" * 60)
    print(f"\nTarget: {API_HOST}:{API_PORT}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    all_passed = True
    
    # Check health endpoint
    print("1. Checking health endpoint...")
    health_ok, health_msg = check_health()
    print(f"   {health_msg}")
    all_passed = all_passed and health_ok
    
    # Check docs endpoint
    print("\n2. Checking API documentation...")
    docs_ok, docs_msg = check_docs()
    print(f"   {docs_msg}")
    all_passed = all_passed and docs_ok
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All checks passed! API is running correctly.")
        print("=" * 60)
        print(f"\nYou can access the API at:")
        print(f"  • API Docs: {DOCS_ENDPOINT}")
        print(f"  • Health Check: {HEALTH_ENDPOINT}")
        print(f"  • Base URL: http://{API_HOST}:{API_PORT}")
        sys.exit(0)
    else:
        print("✗ Some checks failed. Please verify:")
        print("  1. Docker container is running")
        print("  2. EC2 security group allows port 8000")
        print("  3. Application started successfully")
        print("\nTo check logs:")
        print(f"  ssh ubuntu@{API_HOST} 'cd ~/melkai-aimodule && sudo docker-compose logs'")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
