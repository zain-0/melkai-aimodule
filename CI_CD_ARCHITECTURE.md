# CI/CD Pipeline Architecture

## 🔄 Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DEVELOPER WORKFLOW                           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │   git push origin main   │
                    └──────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      CONTINUOUS INTEGRATION (CI)                     │
│                                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │   Tests     │  │   Linting   │  │  Security   │  │  Docker   │ │
│  │  ✓ pytest  │  │  ✓ black    │  │  ✓ safety   │  │  Build    │ │
│  │  ✓ coverage│  │  ✓ flake8   │  │  ✓ bandit   │  │  Test     │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘ │
│                                                                       │
│                           ✅ All Checks Pass                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   CONTINUOUS DEPLOYMENT (CD)                         │
│                                                                       │
│  Step 1: Build Docker Image                                         │
│  ┌────────────────────────────────────────────────┐                │
│  │ docker build -t melk-ai:${{ github.sha }}      │                │
│  └────────────────────────────────────────────────┘                │
│                                   │                                  │
│  Step 2: Deploy to Server via SSH                                   │
│  ┌────────────────────────────────────────────────┐                │
│  │ ssh user@server                                 │                │
│  │ git pull origin main                            │                │
│  │ docker-compose down                             │                │
│  │ docker-compose up -d --build                    │                │
│  └────────────────────────────────────────────────┘                │
│                                   │                                  │
│  Step 3: Health Check                                               │
│  ┌────────────────────────────────────────────────┐                │
│  │ curl http://server:8000/health                  │                │
│  └────────────────────────────────────────────────┘                │
│                                   │                                  │
│                    ┌──────────────┴──────────────┐                  │
│                    ▼                              ▼                  │
│           ✅ Success                      ❌ Failure                 │
│           Deployment Complete            Automatic Rollback         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │  🚀 Live in Production   │
                    └──────────────────────────┘
```

---

## 📁 File Structure

```
.github/
├── workflows/
│   ├── ci.yml                    # Continuous Integration
│   │   ├── Run tests with pytest
│   │   ├── Code quality checks (black, flake8, mypy)
│   │   ├── Security scanning (safety, bandit)
│   │   └── Docker build test
│   │
│   ├── cd.yml                    # Continuous Deployment
│   │   ├── Build Docker image
│   │   ├── Deploy to server via SSH
│   │   ├── Health check
│   │   └── Automatic rollback on failure
│   │
│   └── docker-publish.yml        # Docker Image Publishing
│       ├── Build multi-platform images
│       ├── Push to GitHub Container Registry
│       └── Tag with version numbers

pytest.ini                        # Pytest configuration
CI_CD_SETUP_GUIDE.md             # Detailed setup instructions
CI_CD_QUICK_REFERENCE.md         # Quick reference guide
```

---

## 🎯 Trigger Matrix

| Event | CI Workflow | CD Workflow | Docker Publish |
|-------|-------------|-------------|----------------|
| Push to `main` | ✅ | ✅ | ✅ |
| Push to `develop` | ✅ | ❌ | ❌ |
| Pull Request | ✅ | ❌ | ❌ |
| Release Tag (v1.0.0) | ✅ | ✅ | ✅ |
| Manual Trigger | ✅ | ✅ | ✅ |

---

## 🔐 Required Secrets

Configure these in GitHub: **Settings → Secrets → Actions**

### AWS Credentials
```
AWS_ACCESS_KEY_ID          # For Bedrock API access
AWS_SECRET_ACCESS_KEY      # For Bedrock API access
```

### Deployment Server
```
DEPLOY_HOST                # Server IP or hostname
DEPLOY_USER                # SSH username
DEPLOY_SSH_KEY             # Private SSH key (full key)
DEPLOY_PORT                # SSH port (default: 22)
```

### Optional
```
OPENROUTER_API_KEY         # For OpenRouter models
DOCKERHUB_USERNAME         # For Docker Hub publishing
DOCKERHUB_TOKEN            # Docker Hub access token
SLACK_WEBHOOK              # For Slack notifications
```

---

## 🧪 Test Strategy

```
┌─────────────────────────────────────────────────────────┐
│                      TEST PYRAMID                        │
│                                                           │
│                      ┌────────────┐                      │
│                      │    E2E     │ Manual smoke tests   │
│                      └────────────┘                      │
│                  ┌──────────────────┐                    │
│                  │   Integration    │ API endpoint tests │
│                  └──────────────────┘                    │
│            ┌────────────────────────────┐                │
│            │        Unit Tests          │ Function tests │
│            └────────────────────────────┘                │
│                                                           │
│  All automated tests run in CI pipeline                  │
└─────────────────────────────────────────────────────────┘
```

---

## 🚦 Deployment Stages

### Stage 1: Development
```
Developer → Feature Branch → Local Tests → Pull Request
```

### Stage 2: Integration (CI)
```
Pull Request → GitHub Actions CI
  ├── Run unit tests
  ├── Run integration tests
  ├── Check code quality
  ├── Security scan
  └── Docker build test
```

### Stage 3: Deployment (CD)
```
Merge to Main → GitHub Actions CD
  ├── Build production image
  ├── Deploy to server
  ├── Run health checks
  └── Notify team
```

### Stage 4: Production
```
Production Server
  ├── Monitor logs
  ├── Track metrics
  └── Auto-rollback on errors
```

---

## 📊 Monitoring Dashboard

### GitHub Actions Tab Shows:
- ✅ Workflow run status (success/failure)
- ⏱️ Execution time for each job
- 📝 Detailed logs for debugging
- 📈 Test coverage reports
- 🔒 Security scan results

### Server Monitoring:
```bash
# View application logs
docker-compose logs -f

# Check container status
docker-compose ps

# Monitor resource usage
docker stats

# Check application health
curl http://localhost:8000/health
```

---

## 🔄 Rollback Procedures

### Automatic Rollback
If deployment fails, workflow automatically:
1. Stops failed containers
2. Checks out previous Git commit
3. Rebuilds containers
4. Restarts services

### Manual Rollback
```bash
# Via GitHub Actions
1. Go to Actions tab
2. Find last successful deployment
3. Click "Re-run jobs"

# Via Server SSH
ssh user@server
cd /path/to/project
git log --oneline
git checkout <previous-commit>
docker-compose down
docker-compose up -d --build
```

---

## 🎨 Branch Strategy

```
main (production)
  ├── Protected branch
  ├── Requires PR approval
  ├── Requires passing CI checks
  └── Auto-deploys on merge

develop (staging)
  ├── Integration branch
  ├── Runs CI tests
  └── Manual deploy to staging

feature/* (development)
  ├── Feature branches
  └── Runs CI tests on PR
```

---

## 📈 Performance Metrics

### CI Pipeline Benchmarks
- Average test run time: ~3-5 minutes
- Docker build time: ~2-3 minutes
- Total CI time: ~5-8 minutes

### CD Pipeline Benchmarks
- Deployment time: ~2-3 minutes
- Health check timeout: 30 seconds
- Total CD time: ~3-4 minutes

### Cost Optimization
- GitHub Actions: Free (2,000 minutes/month)
- Uses caching to reduce build times
- Parallel job execution

---

## 🛡️ Security Best Practices

✅ Secrets stored in GitHub Secrets (encrypted)
✅ SSH keys with restricted permissions
✅ AWS credentials with least-privilege IAM roles
✅ Security scanning in every CI run
✅ Dependency vulnerability checks
✅ No secrets in code or logs

---

## 📚 Related Documentation

- [CI_CD_SETUP_GUIDE.md](CI_CD_SETUP_GUIDE.md) - Complete setup instructions
- [CI_CD_QUICK_REFERENCE.md](CI_CD_QUICK_REFERENCE.md) - Quick commands
- [README.md](README.md) - Project overview
- [DEPLOYMENT_GUIDE_COMPLETE.md](DEPLOYMENT_GUIDE_COMPLETE.md) - Manual deployment

---

## 🎯 Success Criteria

✅ All tests pass before deployment
✅ Zero-downtime deployments
✅ Automatic rollback on failures
✅ Comprehensive test coverage (>80%)
✅ Fast feedback loop (<10 minutes)
✅ Secure credential management
✅ Automated health checks
