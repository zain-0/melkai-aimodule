# 🚀 Deployment Guide - Lease Analyzer API

Complete guide for deploying and updating the Lease Analyzer API on AWS EC2.

---

## 📋 Table of Contents
1. [Quick Update (Already Deployed)](#quick-update-already-deployed)
2. [Complete Redeploy (CORS Update)](#complete-redeploy-cors-update)
3. [Initial Setup (First Time)](#initial-setup-first-time)
4. [Verification](#verification)
5. [Troubleshooting](#troubleshooting)
6. [API Endpoints](#api-endpoints)

---

## Quick Update (Already Deployed)

### 🎯 Use This Section If:
- ✅ You already have the app running on EC2
- ✅ You just need to update the code (CORS fix)
- ✅ Everything was working before

**Estimated Time:** 5-8 minutes

### Step 1: Package Updated Code

```powershell
# From your local project directory
cd F:\AimTechAI\comparision-research-melk-ai

# Create deployment package
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
# Upload files (this keeps your .env file on EC2)
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r deploy_package/* ubuntu@18.118.110.218:~/melkai-aimodule/

Write-Host "✅ Files uploaded to EC2" -ForegroundColor Green
```

### Step 3: Redeploy on EC2

```powershell
# Connect and redeploy
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218 "cd ~/melkai-aimodule && sudo docker-compose down && sudo docker-compose build --no-cache && sudo docker-compose up -d"

Write-Host "✅ Application redeployed!" -ForegroundColor Green
```

### Step 4: Verify

```powershell
# Wait for startup
Start-Sleep -Seconds 10

# Test health endpoint
Invoke-RestMethod -Uri "http://18.118.110.218:8000/health"

# Open API docs
Start-Process "http://18.118.110.218:8000/docs"

Write-Host "✅ CORS fix deployed successfully!" -ForegroundColor Green
```

### All-in-One Quick Update Script

```powershell
# Run this entire block to update everything automatically
cd F:\AimTechAI\comparision-research-melk-ai

# Package
if (Test-Path "deploy_package") { Remove-Item -Recurse -Force deploy_package }
New-Item -ItemType Directory -Path "deploy_package" -Force | Out-Null
Copy-Item -Path "app" -Destination "deploy_package\app" -Recurse -Force
Copy-Item -Path "requirements.txt","Dockerfile","docker-compose.yml" -Destination "deploy_package\" -Force
Write-Host "📦 Package created" -ForegroundColor Cyan

# Upload
Write-Host "📤 Uploading to EC2..." -ForegroundColor Cyan
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r deploy_package/* ubuntu@18.118.110.218:~/melkai-aimodule/
Write-Host "✅ Upload complete" -ForegroundColor Green

# Redeploy
Write-Host "🔄 Redeploying on EC2..." -ForegroundColor Cyan
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218 "cd ~/melkai-aimodule && sudo docker-compose down && sudo docker-compose build --no-cache && sudo docker-compose up -d"
Write-Host "✅ Redeploy complete" -ForegroundColor Green

# Verify
Start-Sleep -Seconds 10
Write-Host "🔍 Testing health endpoint..." -ForegroundColor Cyan
Invoke-RestMethod -Uri "http://18.118.110.218:8000/health"
Write-Host "✅ API is healthy!" -ForegroundColor Green

# Cleanup
Remove-Item -Recurse -Force deploy_package
Write-Host "🧹 Cleanup complete" -ForegroundColor Green

Write-Host "`n🎉 Update successful! CORS fix is live!" -ForegroundColor Green
Write-Host "Test at: http://18.118.110.218:8000/docs" -ForegroundColor Cyan
```

---

## Complete Redeploy (CORS Update)

### Required Tools
- **SSH Client**: PuTTY (Windows) or Terminal (Mac/Linux)
- **File Transfer**: WinSCP or FileZilla
- **PEM Key**: `agenticai_melkpm.pem` (located at `C:\Users\Zain\Downloads\`)

### Server Details
- **IP Address**: `18.118.110.218`
- **OS**: Ubuntu 22.04 LTS
- **Port**: `8000`
- **User**: `ubuntu`

### Environment Variables Required
```bash
OPENROUTER_API_KEY=your_api_key_here
```

---

## Initial Setup

### 1. Convert PEM to PPK (Windows/PuTTY Users)

```bash
# If using PuTTY, convert .pem to .ppk using PuTTYgen:
1. Open PuTTYgen
2. Click "Load" and select agenticai_melkpm.pem
3. Click "Save private key" as agenticai_melkpm.ppk
4. Use the .ppk file in PuTTY
```

### 2. Set PEM File Permissions (Mac/Linux)

```bash
chmod 400 C:\Users\Zain\Downloads\agenticai_melkpm.pem
```

---

## Deployment Steps

### Step 1: Connect to EC2 Instance

**Windows (PowerShell):**
```powershell
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

**Mac/Linux:**
```bash
ssh -i ~/Downloads/agenticai_melkpm.pem ubuntu@18.118.110.218
```

**Windows (PuTTY):**
1. Open PuTTY
2. Host Name: `ubuntu@18.118.110.218`
3. Connection → SSH → Auth → Browse to `.ppk` file
4. Click "Open"

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

# Logout and login again for group changes to take effect
exit
```

**Reconnect to EC2** (same command as Step 1)

### Step 4: Upload Project Files

**Option A: Using WinSCP/FileZilla**
1. Connect to `18.118.110.218` with PEM/PPK key
2. Upload entire project folder to `/home/ubuntu/lease-analyzer/`

**Option B: Using SCP (PowerShell/Terminal)**
```powershell
# From your local project directory
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r * ubuntu@18.118.110.218:/home/ubuntu/lease-analyzer/
```

**Option C: Using Git (Recommended)**
```bash
# On EC2 instance
cd /home/ubuntu
git clone https://github.com/zain-0/melkai-aimodule.git lease-analyzer
cd lease-analyzer
```

### Step 5: Configure Environment Variables

```bash
cd /home/ubuntu/lease-analyzer

# Create .env file
nano .env
```

Add the following content:
```env
OPENROUTER_API_KEY=your_actual_api_key_here
MAX_FILE_SIZE_MB=10
LOG_LEVEL=INFO
```

Press `Ctrl+X`, then `Y`, then `Enter` to save.

### Step 6: Build and Run Docker Containers

```bash
# Build the Docker image
docker-compose build

# Start the containers
docker-compose up -d

# Verify containers are running
docker-compose ps
```

Expected output:
```
NAME                          STATUS              PORTS
lease-analyzer-api-1          Up 10 seconds       0.0.0.0:8000->8000/tcp
```

### Step 7: Configure EC2 Security Group

1. Go to AWS Console → EC2 → Security Groups
2. Select your instance's security group
3. Add Inbound Rule:
   - Type: Custom TCP
   - Port: 8000
   - Source: 0.0.0.0/0 (or your IP for security)
4. Save rules

---

## Stop & Redeploy (After CORS Update)

### 🔄 Complete Redeploy - Remove Old & Deploy New

**Use this method when you've made code changes (like CORS updates) and need to completely replace the running application.**

#### Step 1: Connect to EC2

```bash
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

#### Step 2: Stop and Remove Current Deployment

```bash
# Navigate to project directory
cd /home/ubuntu/lease-analyzer

# Stop all running containers
docker-compose down

# Remove all containers, images, volumes (complete cleanup)
docker-compose down -v
docker system prune -af --volumes

# Remove the old project directory
cd /home/ubuntu
sudo rm -rf lease-analyzer
```

#### Step 3: Upload Updated Code

**Option A: Using Git (Recommended)**
```bash
# Clone fresh copy from GitHub
cd /home/ubuntu
git clone https://github.com/zain-0/melkai-aimodule.git lease-analyzer
cd lease-analyzer
```

**Option B: Using SCP from Local Machine**
```powershell
# From your Windows machine (PowerShell)
# Navigate to your project directory first
cd F:\AimTechAI\comparision-research-melk-ai

# Create deployment package
$files = @(
    "app",
    "docker-compose.yml",
    "Dockerfile",
    "requirements.txt"
)

# Upload to EC2
scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r $files ubuntu@18.118.110.218:/home/ubuntu/lease-analyzer/
```

**Option C: Using WinSCP/FileZilla**
1. Connect to `18.118.110.218` with your PEM key
2. Delete old `/home/ubuntu/lease-analyzer/` folder
3. Upload fresh project files

#### Step 4: Configure Environment

```bash
# On EC2, create .env file
cd /home/ubuntu/lease-analyzer
nano .env
```

Add:
```env
OPENROUTER_API_KEY=your_actual_api_key_here
MAX_FILE_SIZE_MB=10
LOG_LEVEL=INFO
```

Save with `Ctrl+X`, `Y`, `Enter`

#### Step 5: Deploy New Version

```bash
# Build fresh Docker image
docker-compose build --no-cache

# Start containers
docker-compose up -d

# Verify deployment
docker-compose ps
docker-compose logs -f
```

#### Step 6: Verify CORS Fix

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test from your local machine
# Open browser: http://18.118.110.218:8000/docs
# Try the /maintenance/workflow endpoint
```

---

### Quick Redeploy (Without Full Cleanup)

**Use this for minor updates when containers are working fine:**

```bash
# Connect to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218

# Navigate to project
cd /home/ubuntu/lease-analyzer

# Stop running containers
docker-compose down

# Pull latest code (if using Git)
git pull origin main

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d

# Verify deployment
docker-compose logs -f
```

### Stop the Application

```bash
# Stop containers
docker-compose down

# Stop and remove volumes (complete cleanup)
docker-compose down -v
```

### View Logs

```bash
# Follow logs in real-time
docker-compose logs -f

# View last 100 lines
docker-compose logs --tail=100

# View logs for specific service
docker-compose logs api
```

### Restart Without Rebuilding

```bash
docker-compose restart
```

---

## Verification

### 1. Check Container Status

```bash
docker-compose ps
```

### 2. Test Health Endpoint

```bash
curl http://18.118.110.218:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "Lease Violation Analyzer"
}
```

### 3. Test from Local Machine

**PowerShell/Terminal:**
```bash
curl http://18.118.110.218:8000/health
```

**Browser:**
```
http://18.118.110.218:8000/docs
```

### 4. View API Documentation

Open in browser:
```
http://18.118.110.218:8000/docs
```

You should see the interactive Swagger UI with all API endpoints.

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs for errors
docker-compose logs

# Check container status
docker ps -a

# Restart Docker service
sudo systemctl restart docker

# Check disk space
df -h

# Check memory
free -h
```

### Port Already in Use

```bash
# Find process using port 8000
sudo lsof -i :8000

# Kill the process
sudo kill -9 <PID>

# Or use different port in docker-compose.yml
```

### Permission Denied Errors

```bash
# Fix file permissions
sudo chown -R ubuntu:ubuntu /home/ubuntu/lease-analyzer
chmod -R 755 /home/ubuntu/lease-analyzer
```

### API Returns 500 Errors

```bash
# Check environment variables
docker-compose config

# Verify .env file exists
cat .env

# Check API logs
docker-compose logs api --tail=50
```

### Cannot Access from Browser

1. **Check Security Group**: Ensure port 8000 is open
2. **Check Container**: `docker-compose ps` shows "Up"
3. **Check Firewall**: `sudo ufw status` (should be inactive or allow 8000)
4. **Test Locally on EC2**:
   ```bash
   curl http://localhost:8000/health
   ```

### Docker Compose Not Found

```bash
# Reinstall docker-compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

### Out of Memory

```bash
# Check memory usage
docker stats

# Increase swap space
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## API Endpoints

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/docs` | GET | Interactive API documentation |
| `/models` | GET | List available AI models |

### Lease Analysis Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyze/single` | POST | Analyze with single model |
| `/analyze/compare` | POST | Compare all models |
| `/analyze/categorized` | POST | Categorized violation analysis |
| `/analyze/provider/{provider}` | POST | Analyze with provider's models |

### Maintenance Workflow Endpoints (FREE)

| Endpoint | Method | Description | Cost |
|----------|--------|-------------|------|
| `/maintenance/evaluate` | POST | Evaluate maintenance request | FREE |
| `/maintenance/vendor` | POST | Generate vendor work order | FREE |
| `/maintenance/workflow` | POST | Complete workflow (evaluation + messages) | FREE |

### Tenant & Move-Out Endpoints (FREE)

| Endpoint | Method | Description | Cost |
|----------|--------|-------------|------|
| `/tenant/rewrite` | POST | Rewrite tenant message professionally | FREE |
| `/move-out/evaluate` | POST | Evaluate move-out request | FREE |

---

## Testing Maintenance Workflow

### Using cURL

```bash
curl -X POST "http://18.118.110.218:8000/maintenance/workflow" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/lease.pdf" \
  -F "maintenance_request=Heater is broken" \
  -F "landlord_notes=Emergency situation"
```

### Using Python

```python
import requests

url = "http://18.118.110.218:8000/maintenance/workflow"

files = {
    'file': open('lease.pdf', 'rb')
}

data = {
    'maintenance_request': 'Heater is broken',
    'landlord_notes': 'Emergency situation'
}

response = requests.post(url, files=files, data=data)
print(response.json())
```

### Expected Response

```json
{
  "maintenance_request": "Heater is broken",
  "tenant_message": "We have received your maintenance request...",
  "tenant_message_tone": "approved",
  "decision": "approved",
  "decision_reasons": ["Heater is an essential habitability requirement"],
  "lease_clauses_cited": ["Section 8.2: Landlord maintains heating systems"],
  "vendor_work_order": {
    "maintenance_request": "Heater is broken",
    "work_order_title": "Emergency Heater Repair - 123 Main St",
    "comprehensive_description": "Heater failure reported...",
    "urgency_level": "emergency"
  },
  "estimated_timeline": "24-48 hours",
  "alternative_action": null
}
```

---

## Quick Reference Commands

### Connect to EC2
```bash
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

### Navigate to Project
```bash
cd /home/ubuntu/lease-analyzer
```

### View Logs
```bash
docker-compose logs -f
```

### Restart Application
```bash
docker-compose restart
```

### Full Redeploy
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Check Status
```bash
docker-compose ps
curl http://localhost:8000/health
```

---

## Support & Resources

- **API Documentation**: http://18.118.110.218:8000/docs
- **Repository**: https://github.com/zain-0/melkai-aimodule
- **EC2 IP**: 18.118.110.218
- **Port**: 8000

---

## Summary

✅ **Deployment complete!** Your API is now accessible at:
- **API Base URL**: http://18.118.110.218:8000
- **Interactive Docs**: http://18.118.110.218:8000/docs
- **Health Check**: http://18.118.110.218:8000/health

🎉 **Ready to use!** All endpoints are operational and using FREE Llama 3.3 model for maintenance workflows.
