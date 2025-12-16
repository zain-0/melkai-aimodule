# 🚀 Complete Deployment Guide - Lease Analyzer API

Comprehensive guide for deploying, updating, and troubleshooting the Lease Analyzer API on AWS EC2 with AWS Bedrock.

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Server Details](#server-details)
3. [Prerequisites](#prerequisites)
4. [Quick Update (Code Changes Only)](#quick-update-code-changes-only)
5. [Initial Setup (First Time Deployment)](#initial-setup-first-time-deployment)
6. [AWS Bedrock Configuration](#aws-bedrock-configuration)
7. [Timeout Configuration](#timeout-configuration)
8. [Verification & Testing](#verification--testing)
9. [Troubleshooting](#troubleshooting)
10. [API Endpoints](#api-endpoints)
11. [Monitoring & Maintenance](#monitoring--maintenance)

---

## Quick Reference

### Connection
```powershell
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
```

### All-in-One Quick Update Script
```powershell
# Run from: F:\AimTechAI\comparision-research-melk-ai
cd F:\AimTechAI\comparision-research-melk-ai

# Package
if (Test-Path "deploy_package") { Remove-Item -Recurse -Force deploy_package }
New-Item -ItemType Directory -Path "deploy_package" -Force | Out-Null
Copy-Item -Path "app" -Destination "deploy_package\app" -Recurse -Force
Copy-Item -Path "requirements.txt","Dockerfile","docker-compose.yml" -Destination "deploy_package\" -Force
Write-Host "📦 Package created" -ForegroundColor Cyan

# Upload
Write-Host "📤 Uploading to EC2..." -ForegroundColor Cyan
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r deploy_package/* ubuntu@18.119.209.125:~/melkai-aimodule/
Write-Host "✅ Upload complete" -ForegroundColor Green

# Redeploy
Write-Host "🔄 Redeploying on EC2..." -ForegroundColor Cyan
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125 "cd ~/melkai-aimodule && sudo docker-compose down && sudo docker-compose build --no-cache && sudo docker-compose up -d"
Write-Host "✅ Redeploy complete" -ForegroundColor Green

# Verify
Start-Sleep -Seconds 15
Write-Host "🔍 Testing health endpoint..." -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://18.119.209.125:8000/health"
Write-Host "✅ API is healthy!" -ForegroundColor Green

# Cleanup
Remove-Item -Recurse -Force deploy_package
Write-Host "🎉 Update successful!" -ForegroundColor Green
Write-Host "API Docs: https://melkpm.duckdns.org/docs" -ForegroundColor Cyan
```

---

## Server Details

- **IP Address**: `18.119.209.125`
- **Domain**: `melkpm.duckdns.org` (with SSL via Let's Encrypt)
- **Port**: `8000`
- **Region**: `us-east-2` (Ohio)
- **OS**: Ubuntu 22.04 LTS
- **Reverse Proxy**: Nginx 1.24.0

### Infrastructure
- **AI Service**: AWS Bedrock (Claude Sonnet 4.5)
- **Container**: Docker with docker-compose
- **ASGI Server**: Uvicorn with 4 workers
- **Web Server**: Nginx with SSL termination

---

## Prerequisites

### Required Files & Access
- ✅ PEM Key: `C:\Users\Zain\Downloads\agenticai_melkpm.pem`
- ✅ SSH access to EC2 (18.119.209.125)
- ✅ AWS IAM role attached to EC2 with Bedrock permissions
- ✅ Security group allows TCP port 8000

### Local Machine Requirements
- PowerShell (Windows) or Terminal (Mac/Linux)
- SSH client (built-in)
- SCP for file transfer

### EC2 Requirements
- Docker & docker-compose installed
- Nginx configured as reverse proxy
- IAM role with `AmazonBedrockFullAccess` or equivalent

---

## Quick Update (Code Changes Only)

### 🎯 Use This When:
- ✅ EC2 is already deployed and running
- ✅ You just made code changes (bug fixes, features, CORS updates, etc.)
- ✅ Environment variables (.env) don't need to change
- ✅ No infrastructure changes needed

**Estimated Time:** 5-8 minutes

### Step 1: Package Updated Code

```powershell
cd F:\AimTechAI\comparision-research-melk-ai

if (Test-Path "deploy_package") {
    Remove-Item -Recurse -Force deploy_package
}

New-Item -ItemType Directory -Path "deploy_package" -Force

# Copy essential files
Copy-Item -Path "app" -Destination "deploy_package\app" -Recurse -Force
Copy-Item -Path "requirements.txt" -Destination "deploy_package\" -Force
Copy-Item -Path "Dockerfile" -Destination "deploy_package\" -Force
Copy-Item -Path "docker-compose.yml" -Destination "deploy_package\" -Force

Write-Host "✅ Deployment package created" -ForegroundColor Green
```

### Step 2: Upload to EC2

```powershell
# Upload files (preserves existing .env on EC2)
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r deploy_package/* ubuntu@18.119.209.125:~/melkai-aimodule/

Write-Host "✅ Files uploaded to EC2" -ForegroundColor Green
```

### Step 3: Rebuild and Restart

```powershell
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125 "cd ~/melkai-aimodule && sudo docker-compose down && sudo docker-compose build --no-cache && sudo docker-compose up -d"

Write-Host "✅ Application redeployed!" -ForegroundColor Green
```

### Step 4: Verify

```powershell
Start-Sleep -Seconds 15

# Test health endpoint
Invoke-RestMethod -Uri "http://18.119.209.125:8000/health"

# Open API docs
Start-Process "https://melkpm.duckdns.org/docs"

Write-Host "✅ Update deployed successfully!" -ForegroundColor Green
```

---

## Initial Setup (First Time Deployment)

### 🎯 Use This When:
- ✅ Setting up EC2 for the first time
- ✅ Fresh Ubuntu instance
- ✅ No Docker/Nginx installed yet

### Step 1: Connect to EC2

```powershell
# Windows PowerShell
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
```

### Step 2: Update System Packages

```bash
sudo apt update
sudo apt upgrade -y
```

### Step 3: Install Docker & Docker Compose

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Logout and login again for group changes
exit
```

**Reconnect after logout**

### Step 4: Install and Configure Nginx

```bash
# Install Nginx
sudo apt install nginx -y

# Enable and start Nginx
sudo systemctl enable nginx
sudo systemctl start nginx

# Verify Nginx is running
sudo systemctl status nginx
```

### Step 5: Configure SSL with Let's Encrypt

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain SSL certificate for melkpm.duckdns.org
sudo certbot --nginx -d melkpm.duckdns.org --non-interactive --agree-tos -m your-email@example.com

# Verify SSL renewal works
sudo certbot renew --dry-run
```

### Step 6: Configure Nginx as Reverse Proxy

Create Nginx configuration file:

```bash
sudo nano /etc/nginx/sites-available/melkpm.duckdns.org
```

Add this configuration:

```nginx
server {
    server_name melkpm.duckdns.org;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        
        # Critical: Timeout settings for long AI responses
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/melkpm.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/melkpm.duckdns.org/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = melkpm.duckdns.org) {
        return 301 https://$host$request_uri;
    }

    listen 80;
    server_name melkpm.duckdns.org;
    return 404;
}
```

Enable the site and reload Nginx:

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/melkpm.duckdns.org /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### Step 7: Upload Project Files

**Option A: Using SCP (from local machine)**
```powershell
cd F:\AimTechAI\comparision-research-melk-ai

# Upload project files
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r app requirements.txt Dockerfile docker-compose.yml ubuntu@18.119.209.125:~/melkai-aimodule/
```

**Option B: Using Git (on EC2)**
```bash
cd ~
git clone https://github.com/zain-0/melkai-aimodule.git melkai-aimodule
cd melkai-aimodule
```

### Step 8: Configure Environment Variables

```bash
cd ~/melkai-aimodule

# Create .env file
nano .env
```

Add this content:
```env
# AWS Bedrock Configuration
AWS_REGION=us-east-2

# Leave credentials empty - EC2 uses IAM role
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Application Settings
MAX_FILE_SIZE_MB=10
SEARCH_RESULTS_LIMIT=10
```

Save with `Ctrl+X`, `Y`, `Enter`

### Step 9: Build and Start Application

```bash
cd ~/melkai-aimodule

# Build Docker image
sudo docker-compose build

# Start containers
sudo docker-compose up -d

# Verify containers are running
sudo docker-compose ps

# Check logs
sudo docker-compose logs -f
```

### Step 10: Configure Security Group

1. Go to AWS Console → EC2 → Security Groups
2. Select your instance's security group
3. Add Inbound Rules:
   - Type: HTTP, Port: 80, Source: 0.0.0.0/0
   - Type: HTTPS, Port: 443, Source: 0.0.0.0/0
   - Type: Custom TCP, Port: 8000, Source: 0.0.0.0/0 (for direct access)
4. Save rules

---

## AWS Bedrock Configuration

### Current Setup
- **Service**: AWS Bedrock (us-east-2)
- **Primary Model**: Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`)
- **Fallback Models**: Llama 3.1 70B, Claude 3.5 Sonnet
- **Authentication**: EC2 IAM Role (recommended) or AWS credentials

### IAM Role Configuration (CRITICAL)

**⚠️ REQUIRED: EC2 instance MUST have IAM role with Bedrock permissions**

#### 1. Create IAM Role

```
AWS Console → IAM → Roles → Create role

Trust relationship:
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}

Attach Policy: AmazonBedrockFullAccess

OR custom policy:
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:us-east-2::foundation-model/*"
    }
  ]
}
```

#### 2. Attach IAM Role to EC2 Instance

```
AWS Console → EC2 → Instances
Select instance: 18.119.209.125
Actions → Security → Modify IAM role
Select: EC2-Bedrock-Access (or your role name)
Update IAM role
```

#### 3. Verify IAM Role

```bash
# SSH to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Check IAM role
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Should return role name
```

### Environment Configuration

When using IAM role (recommended):

```env
AWS_REGION=us-east-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

MAX_FILE_SIZE_MB=10
SEARCH_RESULTS_LIMIT=10
```

**DO NOT** set AWS credentials when using IAM role!

### Available Models

All models use cross-region inference profiles (us. prefix):

**Claude (Best for legal documents):**
- `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (Latest - Sonnet 4.5)
- `us.anthropic.claude-3-5-sonnet-20241022-v2:0`
- `us.anthropic.claude-3-opus-20240229-v1:0`

**Llama (Fast & Reliable):**
- `us.meta.llama3-1-70b-instruct-v1:0` (Default fallback)
- `us.meta.llama3-1-405b-instruct-v1:0`

---

## Timeout Configuration

### Current Configuration (Production)

**Critical: All timeout layers must be aligned for long AI responses (60-120 seconds)**

#### Nginx Timeouts (300 seconds)
```nginx
# /etc/nginx/sites-available/melkpm.duckdns.org
location / {
    proxy_connect_timeout 300s;  # Connection establishment
    proxy_send_timeout 300s;     # Request sending
    proxy_read_timeout 300s;     # Response reading
}
```

#### Uvicorn Timeouts (300 seconds)
```dockerfile
# Dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--timeout-keep-alive", "300", "--timeout-graceful-shutdown", "30"]
```

#### Boto3 Timeouts (180 seconds)
```python
# app/bedrock_client.py
config = Config(
    read_timeout=180,
    connect_timeout=10,
    retries={'max_attempts': 3, 'mode': 'adaptive'}
)
```

### Timeout Architecture

**Timeout Chain (Outermost → Innermost):**
```
Nginx (300s)
  → Uvicorn (300s)
    → Boto3 (180s)
      → AWS Bedrock (120s)
```

**Why These Values:**
- Claude Sonnet 4.5 generates detailed 2,800+ word leases
- Typical generation time: 60-120 seconds
- Nginx must be longest to avoid 504 Gateway Timeout
- Boto3 should be shorter than Uvicorn for proper error handling

### Updating Nginx Timeouts

If you need to update Nginx timeouts:

```bash
# SSH to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Edit Nginx config
sudo nano /etc/nginx/sites-available/melkpm.duckdns.org

# Update these lines in location / block:
proxy_connect_timeout 300s;
proxy_send_timeout 300s;
proxy_read_timeout 300s;

# Test configuration
sudo nginx -t

# If successful, reload Nginx
sudo systemctl reload nginx
```

---

## Verification & Testing

### 1. Health Check

```powershell
# From local machine
Invoke-RestMethod -Uri "http://18.119.209.125:8000/health"

# Expected response:
# {
#   "status": "healthy",
#   "service": "Lease Violation Analyzer"
# }
```

### 2. API Documentation

```powershell
# Open in browser
Start-Process "https://melkpm.duckdns.org/docs"
```

### 3. Test Lease Generation

```powershell
# Test with provided test file
$file = "test_lease_request.json"
$response = Invoke-RestMethod -Uri "https://melkpm.duckdns.org/lease/generate" -Method Post -InFile $file -ContentType "application/json"
Write-Host $response
```

### 4. Check Logs

```bash
# SSH to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# View real-time logs
cd ~/melkai-aimodule
sudo docker-compose logs -f

# View last 100 lines
sudo docker-compose logs --tail=100
```

### 5. Verify CORS (if using from frontend)

```bash
# Test OPTIONS preflight request
curl -X OPTIONS https://melkpm.duckdns.org/lease/generate \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -v

# Should return 200 with CORS headers:
# access-control-allow-origin: *
# access-control-allow-methods: *
# access-control-allow-headers: *
```

### 6. Test Timeout Configuration

```powershell
# Generate a lease (should take 60-120 seconds, no timeouts)
# Use Swagger UI at https://melkpm.duckdns.org/docs
# POST /lease/generate with test_lease_request.json

# Monitor in another terminal:
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
cd ~/melkai-aimodule
sudo docker-compose logs -f
```

---

## Troubleshooting

### Issue: 504 Gateway Timeout

**Symptoms:**
- Lease generation fails after 60 seconds
- Nginx returns 504 error
- Response: `<html><center><h1>504 Gateway Time-out</h1></center><hr><center>nginx/1.24.0</center></html>`

**Diagnosis:**
```bash
# SSH to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Check Nginx timeout configuration
sudo grep -r "proxy_read_timeout" /etc/nginx/sites-available/melkpm.duckdns.org

# Should show: proxy_read_timeout 300s;
```

**Solution:**
```bash
# If timeouts missing, add them
sudo nano /etc/nginx/sites-available/melkpm.duckdns.org

# Add inside location / block:
proxy_connect_timeout 300s;
proxy_send_timeout 300s;
proxy_read_timeout 300s;

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### Issue: Container Won't Start

**Symptoms:**
- `docker-compose ps` shows container as "Exit"
- Application not accessible

**Diagnosis:**
```bash
# Check logs for errors
cd ~/melkai-aimodule
sudo docker-compose logs

# Check container status
sudo docker ps -a

# Check disk space
df -h

# Check memory
free -h
```

**Solution:**
```bash
# Restart Docker service
sudo systemctl restart docker

# Clean up if disk space low
sudo docker system prune -af --volumes

# Rebuild and restart
cd ~/melkai-aimodule
sudo docker-compose down
sudo docker-compose build --no-cache
sudo docker-compose up -d
```

### Issue: AWS Credentials Error

**Symptoms:**
- Logs show: "Unable to locate credentials"
- Bedrock calls fail

**Diagnosis:**
```bash
# Check IAM role attached
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Check .env file
cat ~/melkai-aimodule/.env
```

**Solution:**
1. Attach IAM role to EC2 (see AWS Bedrock Configuration section)
2. Ensure .env does NOT have AWS credentials when using IAM role
3. Restart containers:
```bash
cd ~/melkai-aimodule
sudo docker-compose restart
```

### Issue: CORS Errors

**Symptoms:**
- Browser console shows CORS policy errors
- OPTIONS requests return 404

**Diagnosis:**
```bash
# SSH to EC2
cd ~/melkai-aimodule

# Check CORS middleware in code
grep -A 10 "CORSMiddleware" app/main.py

# Should show CORS configuration
```

**Solution:**
CORS is already configured in `app/main.py`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

If missing, add it and redeploy (use Quick Update section).

### Issue: Port Already in Use

**Symptoms:**
- Container won't start
- Error: "port is already allocated"

**Solution:**
```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>

# Or stop all Docker containers
sudo docker-compose down
sudo docker ps -a
sudo docker stop $(sudo docker ps -aq)

# Start again
cd ~/melkai-aimodule
sudo docker-compose up -d
```

### Issue: SSL Certificate Errors

**Symptoms:**
- Browser shows "Not Secure"
- SSL certificate expired

**Solution:**
```bash
# Renew Let's Encrypt certificate
sudo certbot renew

# Force renewal if needed
sudo certbot renew --force-renewal

# Reload Nginx
sudo systemctl reload nginx
```

### Issue: Out of Memory

**Symptoms:**
- Container randomly stops
- `docker stats` shows high memory usage

**Solution:**
```bash
# Check memory usage
free -h
sudo docker stats --no-stream

# Increase swap space
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make swap permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Restart containers
cd ~/melkai-aimodule
sudo docker-compose restart
```

### Issue: ValidationException from Bedrock

**Symptoms:**
- Logs show: "ValidationException: Model access not enabled"
- API returns 500 errors

**Solution:**
This is already fixed by using inference profiles with `us.` prefix. If you see this error:

1. Check model IDs in `app/config.py` - all should have `us.` prefix
2. Verify IAM role has Bedrock permissions
3. Check AWS Bedrock service is available in us-east-2

---

## API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/docs` | GET | Interactive API documentation |
| `/` | GET | List all endpoints |

### Lease Generation (AWS Bedrock)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/lease/generate` | POST | Generate HTML lease document |

**Parameters:**
- All lease details in JSON format (see test_lease_request.json)

**Response:**
- HTML lease document with inline CSS
- 2,800+ words comprehensive lease
- Print-ready format

### Testing Endpoints

**Health Check:**
```powershell
Invoke-RestMethod -Uri "https://melkpm.duckdns.org/health"
```

**API Documentation:**
```powershell
Start-Process "https://melkpm.duckdns.org/docs"
```

**Generate Lease:**
```powershell
# Using test file
$headers = @{"Content-Type" = "application/json"}
$body = Get-Content "test_lease_request.json" -Raw
$response = Invoke-RestMethod -Uri "https://melkpm.duckdns.org/lease/generate" -Method Post -Headers $headers -Body $body
Write-Host $response
```

---

## Monitoring & Maintenance

### View Real-time Logs

```bash
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
cd ~/melkai-aimodule
sudo docker-compose logs -f
```

Press `Ctrl+C` to exit.

### Check Container Status

```bash
cd ~/melkai-aimodule
sudo docker-compose ps

# Expected output:
# NAME                    STATUS              PORTS
# melkai-aimodule         Up X minutes        0.0.0.0:8000->8000/tcp
```

### Monitor Resource Usage

```bash
# Container stats
sudo docker stats --no-stream

# System resources
free -h        # Memory
df -h          # Disk
top            # CPU
```

### Restart Application

```bash
# Graceful restart
cd ~/melkai-aimodule
sudo docker-compose restart

# Full restart
sudo docker-compose down
sudo docker-compose up -d
```

### Update SSL Certificate

```bash
# Auto-renewal (runs automatically)
sudo certbot renew

# Test renewal
sudo certbot renew --dry-run

# Force renewal if needed
sudo certbot renew --force-renewal
sudo systemctl reload nginx
```

### Backup Application

```bash
# Create backup
cd ~
tar -czf melkai-backup-$(date +%Y%m%d).tar.gz melkai-aimodule/

# Exclude large files
tar -czf melkai-backup-$(date +%Y%m%d).tar.gz --exclude='*.pyc' --exclude='__pycache__' melkai-aimodule/

# List backups
ls -lh *.tar.gz
```

### Clean Up Docker

```bash
# Remove stopped containers
sudo docker container prune -f

# Remove unused images
sudo docker image prune -af

# Remove unused volumes
sudo docker volume prune -f

# Complete cleanup
sudo docker system prune -af --volumes
```

### Check Nginx Configuration

```bash
# Test configuration
sudo nginx -t

# View current config
sudo cat /etc/nginx/sites-available/melkpm.duckdns.org

# Reload after changes
sudo systemctl reload nginx

# Restart if needed
sudo systemctl restart nginx
```

---

## Summary

✅ **Deployment Options:**
- **Quick Update**: 5-8 minutes (code changes only)
- **Full Redeploy**: 10-15 minutes (with rebuild)
- **Initial Setup**: 30-45 minutes (first time)

✅ **API Accessible At:**
- **Base URL**: https://melkpm.duckdns.org
- **API Docs**: https://melkpm.duckdns.org/docs
- **Health Check**: https://melkpm.duckdns.org/health
- **Direct IP**: http://18.119.209.125:8000

✅ **Key Features:**
- AWS Bedrock AI (Claude Sonnet 4.5)
- SSL/HTTPS via Let's Encrypt
- Nginx reverse proxy with 300s timeouts
- CORS enabled for all origins
- Docker containerized
- IAM role authentication

✅ **Support:**
- GitHub: https://github.com/zain-0/melkai-aimodule
- Logs: `sudo docker-compose logs -f`
- Status: `sudo docker-compose ps`

---

**🎉 Your API is production-ready and fully configured!**
