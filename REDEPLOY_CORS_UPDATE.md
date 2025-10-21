# 🔄 Redeployment Guide - CORS Fix Update

This guide walks you through redeploying your application to EC2 with the **CORS middleware fix** for the existing endpoints.

---

## 📋 Overview

**What we're doing:**
1. Stop current Docker containers on EC2
2. Package the updated application code (with CORS fix)
3. Copy new files to EC2
4. Build and start fresh containers
5. Verify CORS is working

**What Changed:**
- ✅ Added CORS middleware to `app/main.py`
- ✅ Configured to allow all origins, methods, and headers
- ✅ Fixes 404 errors on OPTIONS preflight requests

**Estimated Time:** 8-12 minutes

---

## ⚙️ Prerequisites

Before starting, ensure:
- ✅ EC2 instance is running (18.118.110.218)
- ✅ You have SSH access (PEM file at `C:\Users\Zain\Downloads\agenticai_melkpm.pem`)
- ✅ `.env` file exists on EC2 with valid `OPENROUTER_API_KEY`
- ✅ All CORS changes are saved locally in `app/main.py`

---

## 🚀 STEP-BY-STEP REDEPLOYMENT

### STEP 1: Verify CORS Fix Locally

First, verify CORS middleware is in your code:

```powershell
# Navigate to project directory
cd F:\AimTechAI\comparision-research-melk-ai

# Check CORS middleware exists
Select-String -Path "app\main.py" -Pattern "CORSMiddleware"

# Expected output:
# Should show: from fastapi.middleware.cors import CORSMiddleware
# Should show: app.add_middleware(CORSMiddleware...
```

**✅ If you see the CORS code, continue to Step 2**

---

### STEP 2: Stop Current Deployment on EC2

Connect to EC2 and stop running containers:

```powershell
# SSH into EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

**Now on EC2, run:**

```bash
# Navigate to application directory
cd ~/melkai-aimodule

# Check current container status
sudo docker-compose ps

# Stop and remove all containers
sudo docker-compose down

# Verify containers are stopped
sudo docker ps -a

# Optional: Clean up old images to save space
sudo docker system prune -a

# Exit EC2 for now
exit
```

**Expected Output:**
```
Stopping melkai-aimodule_melkai-api_1 ... done
Removing melkai-aimodule_melkai-api_1 ... done
Removing network melkai-aimodule_default ... done
```

**✅ Containers stopped and removed**

---

### STEP 3: Create Fresh Deployment Package

Back on your **local machine** (Windows PowerShell):

```powershell
# Navigate to project directory
cd F:\AimTechAI\comparision-research-melk-ai

# Remove old deployment package if exists
if (Test-Path "deploy_package") {
    Remove-Item -Recurse -Force deploy_package
    Write-Host "✅ Old deployment package removed"
}

# Create new deployment directory
New-Item -ItemType Directory -Path "deploy_package" -Force

# Copy all application files (with CORS updates)
Copy-Item -Path "app" -Destination "deploy_package\app" -Recurse -Force
Copy-Item -Path "requirements.txt" -Destination "deploy_package\" -Force
Copy-Item -Path "Dockerfile" -Destination "deploy_package\" -Force
Copy-Item -Path "docker-compose.yml" -Destination "deploy_package\" -Force

# DON'T copy .env - it already exists on EC2
# Copy .dockerignore if exists
if (Test-Path ".dockerignore") {
    Copy-Item -Path ".dockerignore" -Destination "deploy_package\" -Force
}

# Verify deployment package
Write-Host "`n📦 Deployment Package Contents:"
Get-ChildItem deploy_package -Recurse | Select-Object Name, Length

Write-Host "`n✅ Deployment package created successfully!"
```

**Expected Output:**
```
✅ Old deployment package removed
Directory: F:\AimTechAI\comparision-research-melk-ai\deploy_package
✅ Deployment package created successfully!
```

---

### STEP 4: Backup Current EC2 Deployment (Optional but Recommended)

```powershell
# SSH into EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

**On EC2:**

```bash
# Create backup of current deployment
cd ~
if [ -d "melkai-aimodule" ]; then
    cp -r melkai-aimodule melkai-aimodule-backup-$(date +%Y%m%d-%H%M%S)
    echo "✅ Backup created"
fi

# List backups
ls -la | grep melkai-aimodule

# Exit EC2
exit
```

**✅ Backup created** (optional but safe)

---

### STEP 5: Copy New Files to EC2

Back on **local machine**:

```powershell
# Copy new deployment package to EC2
Write-Host "📤 Uploading CORS-fixed files to EC2..."

scp -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" -r deploy_package/* ubuntu@18.118.110.218:~/melkai-aimodule/

Write-Host "✅ Files uploaded successfully!"
```

**Expected Output:**
```
Dockerfile                    100%  1234  500KB/s   00:00
docker-compose.yml            100%   842  400KB/s   00:00
requirements.txt              100%   450  200KB/s   00:00
...
app/__init__.py              100%    45   50KB/s    00:00
app/main.py                  100% 35KB  1.2MB/s    00:00
app/models.py                100% 12KB  800KB/s    00:00
...
```

**⏱️ This takes 1-2 minutes depending on connection speed**

---

### STEP 6: Verify Files Uploaded Correctly

```powershell
# SSH into EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
```

**On EC2:**

```bash
# Navigate to app directory
cd ~/melkai-aimodule

# Check all files are present
ls -la

# Verify CORS middleware code exists
grep -n "CORSMiddleware" app/main.py

# Expected output: Line numbers showing CORS import and configuration

# Check add_middleware call exists
grep -n "add_middleware" app/main.py

# Expected output: Line showing app.add_middleware(CORSMiddleware...

# Verify .env file still has API key (we didn't overwrite it)
if [ -f ".env" ]; then
    echo "✅ .env file exists"
    grep -q "OPENROUTER_API_KEY" .env && echo "✅ API key found in .env"
else
    echo "❌ .env file missing! You need to create it."
fi
```

**✅ All files verified**

---

### STEP 7: Build New Docker Image

**Still on EC2:**

```bash
# Make sure you're in the right directory
cd ~/melkai-aimodule

# Build new Docker image with CORS fix (this takes 5-10 minutes)
echo "🏗️ Building Docker image with CORS middleware..."
sudo docker-compose build --no-cache

# Expected output:
# Step 1/15 : FROM python:3.11-slim
# Step 2/15 : WORKDIR /app
# ...
# Successfully built abc123def456
# Successfully tagged melkai-aimodule_melkai-api:latest
```

**⏱️ Build time: 5-10 minutes**

**Troubleshooting Build Errors:**
```bash
# If build fails with network timeout
sudo docker-compose build --no-cache

# If build fails with disk space
sudo docker system prune -a
df -h  # Check disk space

# If build fails with dependencies
cat requirements.txt  # Verify requirements file
```

**✅ Docker image built successfully**

---

### STEP 8: Start New Containers

**Still on EC2:**

```bash
# Start containers in detached mode
sudo docker-compose up -d

# Wait a few seconds for startup
sleep 5

# Check container status
sudo docker-compose ps

# Expected output:
#       Name                     Command          State           Ports
# ------------------------------------------------------------------------
# melkai-aimodule_melkai-api_1   uvicorn app.main:app ... Up     0.0.0.0:8000->8000/tcp
```

**✅ Containers started**

---

### STEP 9: Verify Application Started Successfully

**Still on EC2:**

```bash
# Check container logs for startup
sudo docker-compose logs --tail=50

# Look for these success indicators:
# ✅ "Application startup complete"
# ✅ "Uvicorn running on http://0.0.0.0:8000"
# ❌ No error messages or exceptions

# Test health endpoint from EC2
curl http://localhost:8000/health

# Expected output:
# {"status":"healthy","service":"Lease Violation Analyzer"}
```

**If you see errors in logs:**
```bash
# View full logs
sudo docker-compose logs

# Restart if needed
sudo docker-compose restart

# If still failing, check specific errors
sudo docker-compose logs | grep -i error
```

**✅ Application running successfully**

---

### STEP 10: Test CORS from EC2

**Still on EC2:**

```bash
# Test OPTIONS preflight request (this was failing before)
curl -X OPTIONS http://localhost:8000/maintenance/workflow -H "Origin: http://example.com" -H "Access-Control-Request-Method: POST" -v

# Expected output should include CORS headers:
# < HTTP/1.1 200 OK
# < access-control-allow-origin: *
# < access-control-allow-methods: *
# < access-control-allow-headers: *

# Exit EC2
exit
```

**✅ CORS headers present**

---

### STEP 11: Test from Local Machine

**Back on local machine (PowerShell):**

```powershell
# Test health endpoint
Invoke-RestMethod -Uri "http://18.118.110.218:8000/health"

# Expected output:
# status  service
# ------  -------
# healthy Lease Violation Analyzer

# Test root endpoint to see all endpoints
Invoke-RestMethod -Uri "http://18.118.110.218:8000/"

# Verify all endpoints are listed including maintenance_workflow
```

**✅ API accessible from internet**

---

### STEP 12: Test CORS Fix in Browser

**On local machine:**

```powershell
# Open API documentation in browser
Start-Process "http://18.118.110.218:8000/docs"
```

**In the browser (Swagger UI):**
1. Open browser DevTools (F12) → Network tab
2. Navigate to `POST /maintenance/workflow`
3. Click "Try it out"
4. Upload a lease PDF
5. Enter maintenance request: "Heater is broken"
6. Click "Execute"
7. **Check DevTools Network tab:**
   - ✅ Should see OPTIONS request with 200 status (not 404)
   - ✅ Should see POST request with 200 status
   - ✅ Response headers should include `access-control-allow-origin: *`

**✅ CORS fix working!**

---

### STEP 13: Test from Your Frontend Application

If you have a frontend application that was getting CORS errors:

```javascript
// Test from your frontend
fetch('http://18.118.110.218:8000/maintenance/workflow', {
  method: 'POST',
  headers: {
    'Content-Type': 'multipart/form-data',
  },
  body: formData
})
.then(response => response.json())
.then(data => console.log('Success:', data))
.catch(error => console.error('Error:', error));
```

**Expected:**
- ✅ No CORS errors in browser console
- ✅ OPTIONS preflight succeeds
- ✅ POST request succeeds
- ✅ Response data received

---

### STEP 14: Cleanup Local Files

```powershell
# Navigate to project directory
cd F:\AimTechAI\comparision-research-melk-ai

# Remove deployment package
Remove-Item -Recurse -Force deploy_package

Write-Host "✅ Cleanup complete!"
```

---

## ✅ DEPLOYMENT SUCCESS CHECKLIST

Mark each item as you complete it:

- [ ] **Step 1:** CORS fix verified locally
- [ ] **Step 2:** Current EC2 containers stopped and removed
- [ ] **Step 3:** Fresh deployment package created
- [ ] **Step 4:** Backup created (optional)
- [ ] **Step 5:** New files copied to EC2
- [ ] **Step 6:** Files verified on EC2
- [ ] **Step 7:** New Docker image built
- [ ] **Step 8:** New containers started
- [ ] **Step 9:** Application startup verified
- [ ] **Step 10:** CORS headers tested on EC2
- [ ] **Step 11:** API accessible from internet
- [ ] **Step 12:** CORS tested in browser DevTools
- [ ] **Step 13:** Frontend integration tested
- [ ] **Step 14:** Local cleanup completed

---

## 🎯 Quick Verification Commands

Run these to verify CORS is working:

### From Local Machine:
```powershell
# Health check
Invoke-RestMethod -Uri "http://18.118.110.218:8000/health"

# Test OPTIONS request (was failing before)
Invoke-WebRequest -Uri "http://18.118.110.218:8000/maintenance/workflow" -Method OPTIONS -Headers @{"Origin"="http://localhost:3000"} | Select-Object StatusCode, Headers

# Should return 200 with CORS headers
```

### From EC2:
```bash
# SSH in
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218

# Check containers
cd ~/melkai-aimodule
sudo docker-compose ps

# Check logs for CORS middleware
sudo docker-compose logs | grep -i cors

# Test OPTIONS request
curl -X OPTIONS http://localhost:8000/maintenance/workflow -H "Origin: http://example.com" -v

# Exit
exit
```

---

## 🔍 Verify CORS Fix

### Before CORS Fix:
- ❌ OPTIONS requests returned 404
- ❌ Browser showed CORS policy errors
- ❌ Frontend couldn't call API endpoints

### After CORS Fix:
- ✅ OPTIONS requests return 200
- ✅ Response includes CORS headers
- ✅ All origins allowed (`access-control-allow-origin: *`)
- ✅ All methods allowed (GET, POST, OPTIONS, etc.)
- ✅ All headers allowed
- ✅ Frontend can successfully call API

**Test it at:** `http://18.118.110.218:8000/docs`

---

## 📊 Expected Timeline

| Step | Time |
|------|------|
| 1-2. Verify & stop containers | 2 min |
| 3-4. Package & backup | 1 min |
| 5-6. Copy & verify files | 2 min |
| 7. Build Docker image | 5-10 min |
| 8-9. Start & verify | 1 min |
| 10-12. Test CORS | 2 min |
| **Total** | **13-18 min** |

---

## 🐛 Troubleshooting

### Issue: Still getting CORS errors

**Solution:**
```bash
# SSH to EC2
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218

# Verify CORS middleware is in the code
cd ~/melkai-aimodule
grep -A 10 "add_middleware" app/main.py

# Should see:
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# If not found, re-upload files (repeat Step 5)
```

### Issue: OPTIONS returns 404

**Solution:**
```bash
# Check CORS middleware is loaded
sudo docker-compose logs | grep middleware

# Restart containers
cd ~/melkai-aimodule
sudo docker-compose restart

# Test again
curl -X OPTIONS http://localhost:8000/health -v
```

### Issue: Container won't start

**Solution:**
```bash
# Check logs
cd ~/melkai-aimodule
sudo docker-compose logs

# Common issues:
# 1. Port 8000 already in use
sudo netstat -tulpn | grep 8000
sudo docker-compose down
sudo docker-compose up -d

# 2. Missing .env file
ls -la .env
# If missing, create it:
nano .env
# Add: OPENROUTER_API_KEY=your_key_here
```

### Issue: Build fails with "out of disk space"

**Solution:**
```bash
# Check disk usage
df -h

# Clean up Docker
sudo docker system prune -a
sudo docker volume prune

# Remove old backups if needed
rm -rf ~/melkai-aimodule-backup-*

# Try build again
cd ~/melkai-aimodule
sudo docker-compose build --no-cache
```

---

## 📝 Post-Deployment Monitoring

### View Real-time Logs:
```bash
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.118.110.218
cd ~/melkai-aimodule
sudo docker-compose logs -f
# Press Ctrl+C to exit
```

### Monitor CORS Requests:
```bash
# Watch for OPTIONS requests
sudo docker-compose logs -f | grep OPTIONS

# Should see 200 responses, not 404
```

### Check Resource Usage:
```bash
# Container stats
sudo docker stats --no-stream

# System resources
free -h
df -h
top
```

---

## 🎉 Deployment Complete!

Your application is now redeployed with CORS middleware fix!

**CORS is now enabled for:**
- ✅ All origins (`*`)
- ✅ All methods (GET, POST, OPTIONS, PUT, DELETE, etc.)
- ✅ All headers
- ✅ Preflight OPTIONS requests

**Test it now:**
- API Docs: `http://18.118.110.218:8000/docs`
- Health: `http://18.118.110.218:8000/health`
- Any endpoint from your frontend application

---

## 📞 Need Help?

If CORS issues persist:
1. Check browser DevTools Console for specific CORS error
2. Verify OPTIONS request in Network tab shows 200 status
3. Check response headers include `access-control-allow-origin`
4. Review logs: `sudo docker-compose logs | grep -i cors`
5. Restart containers: `sudo docker-compose restart`

---

**✨ Your API is now CORS-enabled and ready for frontend integration! ✨**
