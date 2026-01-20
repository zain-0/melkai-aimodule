# CI/CD Quick Reference

## 🚀 Quick Start

### 1. Add GitHub Secrets
Repository → Settings → Secrets → Actions → New secret

```
AWS_ACCESS_KEY_ID          = your_key (for CI testing)
AWS_SECRET_ACCESS_KEY      = your_secret (for CI testing)
DEPLOY_HOST                = 18.119.209.125
DEPLOY_USER                = ubuntu
DEPLOY_SSH_KEY             = (content of agenticai_melkpm.pem)
DEPLOY_PORT                = 22
```

**EC2 Production Note:** Production deployment uses IAM role, not AWS credentials.

### 2. Update Deployment Paths
Deployment is configured for:
- **Server:** 18.119.209.125 (melkpm.duckdns.org)
- **Path:** `~/melkai-aimodule`
- **Port:** 8000

No changes needed unless you have a different server setup.

### 3. Push to GitHub
```bash
git add .github/ CI_CD_SETUP_GUIDE.md pytest.ini
git commit -m "Add CI/CD pipeline"
git push origin main
```

---

## 📋 Workflows Summary

| Workflow | Trigger | Purpose |
|----------|---------|---------|(EC2 18.119.209.125) |
| **cd-staging.yml** | Push to develop | Deploy to staging environment
| **ci.yml** | Push/PR to main/develop | Run tests, linting, security scans |
| **cd.yml** | Push to main | Deploy to production server |
| **docker-publish.yml** | Push to main / Releases | Build & publish Docker images |

---

## 🎯 Common Commands

### Run Tests Locally
```bash
pip install pytest pytest-cov pytest-asyncio httpx
pytest -v
```

### Check Code Quality
```bash
pip install black flake8 mypy
black --check app/
flake8 app/ --count --statistics
mypy app/ --ignore-missing-imports
```

### Build Docker Image
```bash
docker build -t melk-ai:test .
docker run --rm -p 8000:8000 melk-ai:test
```

### Manual Deployment
```bashEC2 server
ssh -i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125

# Navigate to project
cd ~/melkai-aimodule

# Pull latest code
git pull origin main

# Rebuild containers
sudo docker-compose down
sudo docker-compose build --no-cache
sudo docker-compose up -d

# View logs
sudo # View logs
docker-compose logs -f
```

---

## 🔄 Deployment Workflow

```
Code Push → CI Tests → Build Docker → Deploy to Server → Health Check → ✅ Success
                ↓ (if fails)
            Automatic Rollback
```

---

## 🏷️ Version Tagging

Create a release:
```bash
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

This triggers both deployment and Docker publishing.

---

## 🛠️ Troubleshooting

### CI Failing?
1. Check test logs in Actions tab
2. Run tests locally to reproduce
3. Verify all secrets are configured

### Deployment Failing?
1. Test SSH: `ssh user@host`
2. Check server logs: `docker-compose logs`
3. Verify deployment path exists
4. Check disk space: `df -h`

### Docker Build Failing?
1. Build locally: `docker build -t test .`
2. Check Dockerfile syntax
3. Verify requirements.txt

---

## 📊 Monitoring

### View Workflow Status
- GitHub Repository → Actions tab
- Green ✅ = Success
- Red ❌ = Failed

### Check Deployment Logs
```b-i "C:\Users\Zain\Downloads\agenticai_melkpm.pem" ubuntu@18.119.209.125
sudo docker-compose -f ~/melkai-aimodule/docker-compose.yml logs -f --tail=100
```

### Health Check
```bash
# Via IP
curl http://18.119.209.125:8000/health

# Via Domain
curl https://melkpm.duckdns.org
curl http://your-server:8000/health
```

---

## 🔐 Security Checklist

- ✅ All secrets stored in GitHub Secrets
- ✅ SSH keys have restricted permissions
- ✅ AWS credentials follow least-privilege
- ✅ Security scanning enabled in CI
- ✅ Dependencies regularly updated

---

## 📈 Next Steps

1. Set up staging environment
2. Add branch protection rules
3. Configure Slack/Discord notifications
4. Enable code coverage tracking
5. Add performance tests

---

## 📚 Resources

- [Full Setup Guide](CI_CD_SETUP_GUIDE.md)
- [GitHub Actions Docs](https://docs.github.com/actions)
- [Docker Docs](https://docs.docker.com/)
