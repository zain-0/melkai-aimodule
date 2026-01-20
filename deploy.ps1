# MelkAI Module Deployment Script for EC2 (PowerShell)
# This script deploys the dockerized application to your EC2 instance

param(
    [switch]$SkipBuild = $false,
    [switch]$Logs = $false,
    [switch]$Stop = $false,
    [switch]$Restart = $false
)

# Configuration
$EC2_USER = "ubuntu"
$EC2_HOST = "18.119.209.125"
$PEM_FILE = "C:\Users\Zain\Downloads\agenticai_melkpm.pem"
$APP_NAME = "melkai-aimodule"
$REMOTE_DIR = "/home/ubuntu/$APP_NAME"

# Colors
$Green = "Green"
$Yellow = "Yellow"
$Red = "Red"

Write-Host "========================================" -ForegroundColor $Green
Write-Host "MelkAI Module Deployment Script" -ForegroundColor $Green
Write-Host "========================================" -ForegroundColor $Green
Write-Host ""

# Check if PEM file exists
if (-not (Test-Path $PEM_FILE)) {
    Write-Host "Error: PEM file not found at $PEM_FILE" -ForegroundColor $Red
    exit 1
}

# Handle special commands
if ($Logs) {
    Write-Host "Fetching logs from EC2..." -ForegroundColor $Yellow
    ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && sudo docker-compose logs -f"
    exit 0
}

if ($Stop) {
    Write-Host "Stopping application on EC2..." -ForegroundColor $Yellow
    ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && sudo docker-compose down"
    Write-Host "Application stopped successfully" -ForegroundColor $Green
    exit 0
}

if ($Restart) {
    Write-Host "Restarting application on EC2..." -ForegroundColor $Yellow
    ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && sudo docker-compose restart"
    Write-Host "Application restarted successfully" -ForegroundColor $Green
    exit 0
}

# Step 1: Create deployment package
Write-Host "[1/6] Creating deployment package..." -ForegroundColor $Yellow

$deployDir = "deploy_package"
if (Test-Path $deployDir) {
    Remove-Item -Recurse -Force $deployDir
}
New-Item -ItemType Directory -Path $deployDir | Out-Null

# Copy files excluding unnecessary directories
$excludeDirs = @('env', 'venv', '__pycache__', '.git', 'logs', 'deploy_package')
$excludeExtensions = @('*.pyc', '*.pyo', '*.pdf')

Get-ChildItem -Path . -Recurse | Where-Object {
    $item = $_
    $exclude = $false
    foreach ($dir in $excludeDirs) {
        if ($item.FullName -like "*\$dir\*" -or $item.Name -eq $dir) {
            $exclude = $true
            break
        }
    }
    if (-not $exclude) {
        foreach ($ext in $excludeExtensions) {
            if ($item.Name -like $ext) {
                $exclude = $true
                break
            }
        }
    }
    -not $exclude
} | ForEach-Object {
    $relativePath = $_.FullName.Substring((Get-Location).Path.Length + 1)
    $targetPath = Join-Path $deployDir $relativePath
    $targetDir = Split-Path $targetPath -Parent
    
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    
    if ($_.PSIsContainer -eq $false) {
        Copy-Item $_.FullName $targetPath
    }
}

Write-Host "✓ Deployment package created" -ForegroundColor $Green
Write-Host ""

# Step 2: Copy files to EC2
Write-Host "[2/6] Copying files to EC2 instance..." -ForegroundColor $Yellow
ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "mkdir -p $REMOTE_DIR"
scp -i $PEM_FILE -r "$deployDir\*" "${EC2_USER}@${EC2_HOST}:${REMOTE_DIR}/"

Write-Host "✓ Files copied successfully" -ForegroundColor $Green
Write-Host ""

# Step 3: Install Docker on EC2
Write-Host "[3/6] Checking Docker installation on EC2..." -ForegroundColor $Yellow
$dockerInstallScript = @'
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker ubuntu
    echo "Docker installed successfully"
else
    echo "Docker is already installed"
fi

if ! command -v docker-compose &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    echo "Docker Compose installed successfully"
else
    echo "Docker Compose is already installed"
fi
'@

ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" $dockerInstallScript

Write-Host "✓ Docker environment ready" -ForegroundColor $Green
Write-Host ""

# Step 4: Stop existing containers
Write-Host "[4/6] Stopping existing containers..." -ForegroundColor $Yellow
ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && if [ -f docker-compose.yml ]; then sudo docker-compose down || true; fi"

Write-Host "✓ Existing containers stopped" -ForegroundColor $Green
Write-Host ""

# Step 5: Build and start containers
Write-Host "[5/6] Building and starting Docker containers..." -ForegroundColor $Yellow
if ($SkipBuild) {
    ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && sudo docker-compose up -d"
} else {
    ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && sudo docker-compose build --no-cache && sudo docker-compose up -d"
}

Write-Host "✓ Containers started successfully" -ForegroundColor $Green
Write-Host ""

# Step 6: Verify deployment
Write-Host "[6/6] Verifying deployment..." -ForegroundColor $Yellow
Start-Sleep -Seconds 5
ssh -i $PEM_FILE "$EC2_USER@$EC2_HOST" "cd $REMOTE_DIR && echo 'Container status:' && sudo docker-compose ps && echo '' && echo 'Container logs (last 20 lines):' && sudo docker-compose logs --tail=20"

Write-Host ""
Write-Host "========================================" -ForegroundColor $Green
Write-Host "Deployment Complete!" -ForegroundColor $Green
Write-Host "========================================" -ForegroundColor $Green
Write-Host ""
Write-Host "API is available at: http://${EC2_HOST}:8000" -ForegroundColor $Green
Write-Host "API Documentation: http://${EC2_HOST}:8000/docs" -ForegroundColor $Green
Write-Host "Health Check: http://${EC2_HOST}:8000/health" -ForegroundColor $Green
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor $Yellow
Write-Host "  View logs: .\deploy.ps1 -Logs" -ForegroundColor $Green
Write-Host "  Restart app: .\deploy.ps1 -Restart" -ForegroundColor $Green
Write-Host "  Stop app: .\deploy.ps1 -Stop" -ForegroundColor $Green
Write-Host "  Deploy (skip build): .\deploy.ps1 -SkipBuild" -ForegroundColor $Green
Write-Host ""

# Cleanup
Remove-Item -Recurse -Force $deployDir
