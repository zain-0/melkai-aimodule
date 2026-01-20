# CI/CD Deployment Checklist

## Pre-Deployment Checklist

### ✅ 1. GitHub Repository Setup
- [x] Repository: https://github.com/zain-0/melkai-aimodule
- [ ] Add collaborators if needed
- [ ] Configure branch protection rules for `main`
- [ ] Enable GitHub Actions in repository settings

### ✅ 2. GitHub Secrets Configuration

Go to: **Repository → Settings → Secrets and variables → Actions**

#### Required Secrets:
- [ ] `AWS_ACCESS_KEY_ID` - For CI testing only (production uses IAM role)
- [ ] `AWS_SECRET_ACCESS_KEY` - For CI testing only
- [ ] `DEPLOY_HOST` - Set to: `18.119.209.125`
- [ ] `DEPLOY_USER` - Set to: `ubuntu`
- [ ] `DEPLOY_SSH_KEY` - Full content of `agenticai_melkpm.pem`
- [ ] `DEPLOY_PORT` - Set to: `22` (optional, defaults to 22)

#### Optional Secrets:
- [ ] `DOCKERHUB_USERNAME` - For Docker Hub publishing
- [ ] `DOCKERHUB_TOKEN` - Docker Hub access token
- [ ] `SLACK_WEBHOOK` - For Slack notifications
- [ ] `STAGING_HOST` - If using separate staging server

### ✅ 3. EC2 Server Configuration

#### Server Details:
- **IP:** 18.119.209.125
- **Domain:** melkpm.duckdns.org
- **Region:** us-east-2 (Ohio)
- **Path:** ~/melkai-aimodule

#### Verify on EC2:
```bash
# SSH into server
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Check prerequisites
docker --version          # Should be installed
docker-compose --version  # Should be installed
git --version            # Should be installed

# Check IAM role
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# Verify project directory
cd ~/melkai-aimodule
git remote -v  # Should point to github.com/zain-0/melkai-aimodule
```

#### Required on EC2:
- [x] Docker installed
- [x] Docker Compose installed
- [x] Git installed
- [x] IAM role attached with AmazonBedrockFullAccess
- [x] Security group allows ports 80, 443, 8000
- [x] Nginx configured as reverse proxy
- [x] SSL certificate via Let's Encrypt
- [x] Project cloned to ~/melkai-aimodule
- [x] .env file configured (uses IAM role, no AWS credentials)

---

## Deployment Process

### Step 1: Initial Setup (One-time)

```bash
# 1. Add GitHub secrets (see above)
# 2. Verify EC2 is ready (see above)
# 3. Push workflows to GitHub
git add .github/
git commit -m "Add CI/CD pipeline"
git push origin main
```

### Step 2: Verify Workflows

1. Go to: https://github.com/zain-0/melkai-aimodule/actions
2. Check that CI workflow started
3. Verify all checks pass (tests, linting, security)
4. Monitor CD workflow deployment

### Step 3: Verify Deployment

```bash
# Check health endpoint
curl http://18.119.209.125:8000/health
curl https://melkpm.duckdns.org/health

# Check API docs
# Open in browser: https://melkpm.duckdns.org/docs

# Check logs
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
cd ~/melkai-aimodule
sudo docker-compose logs -f --tail=50
```

---

## Workflow Triggers

### CI Workflow (ci.yml)
**Triggers:**
- Push to `main` branch
- Push to `develop` branch
- Pull request to `main` or `develop`

**Actions:**
- Run pytest tests
- Code quality checks (black, flake8, mypy)
- Security scans (safety, bandit)
- Docker build test
- Upload coverage reports

### CD Workflow (cd.yml) - Production
**Triggers:**
- Push to `main` branch
- Git tags (v*.*.*)
- Manual trigger

**Actions:**
1. Build Docker image
2. SSH to EC2 (18.119.209.125)
3. Pull latest code
4. Rebuild containers with `--no-cache`
5. Restart services
6. Health check
7. Auto-rollback on failure

### CD Staging Workflow (cd-staging.yml)
**Triggers:**
- Push to `develop` branch
- Manual trigger

**Actions:**
- Deploy to staging environment
- Separate from production

### Docker Publish (docker-publish.yml)
**Triggers:**
- Push to `main` branch
- GitHub releases

**Actions:**
- Build Docker image
- Push to GitHub Container Registry
- Tag with version numbers

---

## Branch Strategy

```
main (production)
  ↓
  ├─ Protected branch
  ├─ Requires PR approval
  ├─ CI must pass
  └─ Auto-deploys to EC2 18.119.209.125

develop (staging)
  ↓
  ├─ Integration branch
  ├─ CI tests run
  └─ Deploys to staging (if configured)

feature/* (development)
  ↓
  ├─ Feature branches
  ├─ CI tests on PR
  └─ Merge to develop first
```

---

## Testing Checklist

### Before Pushing to Main:
- [ ] Run tests locally: `pytest -v`
- [ ] Check code formatting: `black --check app/`
- [ ] Run linting: `flake8 app/`
- [ ] Test Docker build: `docker build -t melk-ai:test .`
- [ ] Create PR from feature branch to develop
- [ ] Wait for CI to pass
- [ ] Get PR approval
- [ ] Merge to main

### After Deployment:
- [ ] Health endpoint responds: https://melkpm.duckdns.org/health
- [ ] API docs accessible: https://melkpm.duckdns.org/docs
- [ ] Test main endpoints:
  - [ ] POST /analyze-lease
  - [ ] POST /analyze-lease-categorized
  - [ ] POST /evaluate-maintenance-request
  - [ ] POST /rewrite-tenant-message
- [ ] Check logs for errors: `sudo docker-compose logs`
- [ ] Monitor for 5-10 minutes

---

## Monitoring

### GitHub Actions Dashboard
https://github.com/zain-0/melkai-aimodule/actions

**Monitor:**
- ✅ Workflow run status
- ⏱️ Execution time
- 📝 Test results
- 📊 Coverage reports
- 🔒 Security scan results

### EC2 Server Monitoring
```bash
# SSH to server
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Check containers
sudo docker-compose ps

# View logs
sudo docker-compose logs -f --tail=100

# Check resource usage
sudo docker stats

# Check disk space
df -h

# Check memory
free -h
```

### Application Monitoring
```bash
# Health check
curl https://melkpm.duckdns.org/health

# Check response time
time curl -s https://melkpm.duckdns.org/health

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## Rollback Procedures

### Automatic Rollback
If CD workflow fails, it automatically:
1. Stops failed containers
2. Checks out previous commit
3. Rebuilds containers
4. Restarts services

### Manual Rollback via GitHub
1. Go to: https://github.com/zain-0/melkai-aimodule/actions
2. Find last successful CD workflow
3. Click "Re-run jobs"

### Manual Rollback via SSH
```bash
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
cd ~/melkai-aimodule

# View commit history
git log --oneline -10

# Rollback to specific commit
git checkout <commit-hash>

# Rebuild and restart
sudo docker-compose down
sudo docker-compose build --no-cache
sudo docker-compose up -d

# Verify
curl http://localhost:8000/health
```

---

## Troubleshooting

### Workflow Not Running
- [ ] Check workflow syntax: `.github/workflows/*.yml`
- [ ] Verify branch names match triggers
- [ ] Check GitHub Actions is enabled
- [ ] Review repository permissions

### Deployment Failing
- [ ] Check SSH connection works
- [ ] Verify `DEPLOY_SSH_KEY` secret is correct
- [ ] Check EC2 security group allows port 22
- [ ] Verify project path exists: `~/melkai-aimodule`
- [ ] Check EC2 has enough disk space
- [ ] Review deployment logs in Actions tab

### Tests Failing
- [ ] AWS credentials configured for CI
- [ ] All required packages in requirements.txt
- [ ] Python version matches (3.11)
- [ ] Check test logs for specific failures

### Health Check Failing
- [ ] Check containers are running: `sudo docker-compose ps`
- [ ] Review application logs: `sudo docker-compose logs`
- [ ] Verify port 8000 is accessible
- [ ] Check Nginx configuration
- [ ] Test directly: `curl http://localhost:8000/health`

---

## Security Best Practices

### Secrets Management
- ✅ All credentials in GitHub Secrets
- ✅ Never commit .env or .pem files
- ✅ Use IAM role on EC2 (not hardcoded credentials)
- ✅ Rotate SSH keys periodically
- ✅ Limit GitHub secret access

### Server Security
- ✅ Security group restricts access
- ✅ SSH key-based authentication only
- ✅ SSL/TLS via Let's Encrypt
- ✅ Regular security updates
- ✅ Docker containers run non-root

### Code Security
- ✅ Security scanning in CI
- ✅ Dependency vulnerability checks
- ✅ No secrets in code or logs
- ✅ CORS properly configured

---

## Useful Commands

### Local Development
```bash
# Run tests
pytest -v --cov=app

# Format code
black app/

# Lint code
flake8 app/

# Build Docker locally
docker build -t melk-ai:local .
docker run -p 8000:8000 melk-ai:local
```

### GitHub Actions
```bash
# Trigger manual deployment
# Go to: Actions → CD → Run workflow → main

# View latest workflow
gh run list --limit 5

# View workflow details
gh run view <run-id>
```

### EC2 Management
```bash
# Quick deployment script (local)
.\deploy.ps1

# View logs
.\deploy.ps1 -Logs

# Restart
.\deploy.ps1 -Restart

# Stop
.\deploy.ps1 -Stop
```

---

## Success Criteria

### Deployment Successful When:
- ✅ All CI tests pass
- ✅ CD workflow completes without errors
- ✅ Health endpoint returns 200 OK
- ✅ API docs accessible at https://melkpm.duckdns.org/docs
- ✅ Main endpoints respond correctly
- ✅ No errors in logs
- ✅ Response time < 2 seconds
- ✅ Docker containers running and healthy

### Production Ready When:
- ✅ All workflows configured and tested
- ✅ Branch protection rules enabled
- ✅ Monitoring in place
- ✅ Rollback tested and working
- ✅ Documentation complete and accurate
- ✅ Team trained on deployment process

---

## Support & Resources

- **GitHub Repository:** https://github.com/zain-0/melkai-aimodule
- **GitHub Actions:** https://github.com/zain-0/melkai-aimodule/actions
- **Production API:** https://melkpm.duckdns.org/docs
- **Server IP:** 18.119.209.125:8000
- **Documentation:** CI_CD_SETUP_GUIDE.md, CI_CD_QUICK_REFERENCE.md

---

**Last Updated:** January 21, 2026
**Server Region:** us-east-2 (Ohio)
**Repository:** zain-0/melkai-aimodule
