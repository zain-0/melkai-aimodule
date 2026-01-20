# CI/CD Pipeline Setup Guide

This guide will help you set up automated testing and deployment using GitHub Actions.

## Overview

We've created three GitHub Actions workflows:

1. **CI (Continuous Integration)** - `.github/workflows/ci.yml`
   - Runs on every push and pull request
   - Executes automated tests
   - Performs code quality checks
   - Security scanning

2. **CD (Continuous Deployment)** - `.github/workflows/cd.yml`
   - Deploys to production on main branch pushes
   - Includes rollback capability
   - Health checks after deployment

3. **Docker Publishing** - `.github/workflows/docker-publish.yml`
   - Builds and publishes Docker images
   - Pushes to GitHub Container Registry
   - Tags with version numbers

---

## Setup Instructions

### Step 1: Configure GitHub Repository Secrets

Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add the following secrets:

#### AWS Credentials (Required for AI operations)
```
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
```

#### OpenRouter API Key (If using OpenRouter)
```
OPENROUTER_API_KEY=your_openrouter_key
```

#### Docker Hub Credentials (Optional - for Docker Hub publishing)
```
DOCKERHUB_USERNAME=your_dockerhub_username
DOCKERHUB_TOKEN=your_dockerhub_token
```

#### Deployment Server Credentials (For CD workflow)
```
DEPLOY_HOST=18.119.209.125
DEPLOY_USER=ubuntu
DEPLOY_SSH_KEY=-----BEGIN OPENSSH PRIVATE KEY-----
...your private key content from agenticai_melkpm.pem...
-----END OPENSSH PRIVATE KEY-----
DEPLOY_PORT=22
```

**Note:** The SSH key should be the full content of your `agenticai_melkpm.pem` file.

---

### Step 2: Update CD Workflow for Your Server

The CD workflow is already configured for EC2 at **18.119.209.125** (melkpm.duckdns.org).

The deployment path is set to: `~/melkai-aimodule`

If you need to change it, edit `.github/workflows/cd.yml` line 46:
```yaml
script: |
  cd ~/melkai-aimodule  # ← Change this if needed
  git pull origin main
  sudo docker-compose down
  sudo docker-compose build --no-cache
  sudo docker-compose up -d
```

Health check endpoints:
- HTTP: `http://18.119.209.125:8000/health`
- HTTPS: `https://melkpm.duckdns.org/health`

---

### Step 3: Push Workflows to GitHub

```bash
git add .github/
git commit -m "Add CI/CD workflows with GitHub Actions"
git push origin main
```

The workflows will automatically start running!

---

### Step 4: Create GitHub Environment (Optional but Recommended)

For production deployments, set up an environment:

1. Go to **Settings** → **Environments** → **New environment**
2. Name it `production`
3. Add **Environment protection rules**:
   - ✅ Required reviewers (add team members)
   - ✅ Wait timer (e.g., 5 minutes)
4. Add environment-specific secrets (overrides repository secrets)

---

## Workflow Triggers

### CI Workflow (ci.yml)
- ✅ Runs on every **push** to `main` or `develop` branches
- ✅ Runs on every **pull request** to `main` or `develop`
- ✅ Tests must pass before merging PRs

### CD Workflow (cd.yml)
- ✅ Runs on **push to main branch**
- ✅ Runs on **version tags** (v1.0.0, v2.1.3, etc.)
- ✅ Can be **manually triggered** via GitHub Actions UI

### Docker Publishing (docker-publish.yml)
- ✅ Runs on **push to main**
- ✅ Runs on **GitHub releases**
- ✅ Publishes to GitHub Container Registry

---

## Testing Locally Before Pushing

### Test Docker Build
```bash
docker build -t melk-ai:test .
docker run --rm -p 8000:8000 melk-ai:test
```

### Run Tests Locally
```bash
pip install pytest pytest-cov pytest-asyncio httpx
pytest test_*.py -v --cov=app
```

### Check Code Quality
```bash
pip install black flake8 mypy
black --check app/
flake8 app/
mypy app/ --ignore-missing-imports
```

---

## Viewing Workflow Results

### GitHub Actions Dashboard
1. Go to your repository on GitHub
2. Click **Actions** tab
3. View all workflow runs, logs, and results

### Status Badges
Add to your README.md:

```markdown
![CI Tests](https://github.com/YOUR_USERNAME/YOUR_REPO/actions/workflows/ci.yml/badge.svg)
![Deployment](https://github.com/YOUR_USERNAME/YOUR_REPO/actions/workflows/cd.yml/badge.svg)
```

---

## Common Deployment Patterns

### Pattern 1: Deploy on Every Push to Main
✅ **Current setup** - Automatic deployment when code is merged to main

### Pattern 2: Deploy on Manual Approval
1. Uncomment environment protection in `cd.yml`
2. Add required reviewers in GitHub settings
3. Deployment waits for approval

### Pattern 3: Deploy on Release Tags
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```
Triggers both CD and Docker publishing workflows

---

## Rollback Procedure

### Automatic Rollback
If deployment fails, the workflow automatically rolls back to the previous version.

### Manual Rollback
Via SSH:
```bash
ssh user@your-server
cd /path/to/deployment
git log --oneline  # Find previous commit
git checkout <commit-hash>
docker-compose down
docker-compose up -d --build
```

Via GitHub Actions:
1. Go to **Actions** tab
2. Find the last successful deployment
3. Click **Re-run jobs**

---

## Monitoring and Notifications

### Slack Notifications (Optional)
Add to workflow after deployment:
```yaml
- name: Notify Slack
  uses: slackapi/slack-github-action@v1.25.0
  with:
    webhook: ${{ secrets.SLACK_WEBHOOK }}
    payload: |
      {
        "text": "🚀 Deployment successful - ${{ github.sha }}"
      }
```

### Email Notifications
GitHub automatically sends emails on workflow failures to committers.

### Discord/Teams
Similar setup using respective webhook actions.

---

## Best Practices

### 1. Branch Protection Rules
- ✅ Require status checks to pass before merging
- ✅ Require pull request reviews
- ✅ Require branches to be up to date

### 2. Testing Strategy
- ✅ Unit tests run on every commit
- ✅ Integration tests on staging environment
- ✅ Manual smoke tests after production deployment

### 3. Deployment Strategy
- ✅ Deploy to staging first (create staging workflow)
- ✅ Run automated tests on staging
- ✅ Manual approval for production
- ✅ Blue-green or canary deployments for zero downtime

### 4. Security
- ✅ Never commit secrets to repository
- ✅ Use GitHub Secrets for all credentials
- ✅ Rotate secrets regularly
- ✅ Use least-privilege access for service accounts

---

## Troubleshooting

### Workflow Not Running?
1. Check workflow file syntax (YAML is indent-sensitive)
2. Verify branch names in triggers match your branches
3. Check repository permissions for GitHub Actions

### Deployment Failing?
1. Check SSH connection: `ssh -i key.pem user@host`
2. Verify server has Git and Docker installed
3. Check server disk space: `df -h`
4. Review deployment logs in Actions tab

### Tests Failing?
1. Check AWS credentials are valid
2. Ensure all secrets are set in GitHub
3. Review test logs for specific failures
4. Run tests locally to reproduce issues

### Docker Build Failing?
1. Test Dockerfile locally: `docker build -t test .`
2. Check requirements.txt has all dependencies
3. Verify base image is accessible
4. Review build logs for error messages

---

## Scaling Up

### Add Staging Environment
Create `.github/workflows/deploy-staging.yml`:
```yaml
on:
  push:
    branches: [ develop ]
```

### Add Performance Tests
```yaml
- name: Run load tests
  run: |
    pip install locust
    locust -f locustfile.py --headless -u 10 -r 2 --run-time 1m
```

### Add Database Migrations
```yaml
- name: Run database migrations
  run: |
    python manage.py migrate
```

---

## Cost Optimization

### GitHub Actions is FREE for:
- ✅ Public repositories (unlimited minutes)
- ✅ Private repositories (2,000 minutes/month on free plan)

### Tips to Reduce Minutes:
1. Use caching for dependencies (`cache: 'pip'`)
2. Skip CI on documentation changes
3. Use matrix builds efficiently
4. Cancel redundant workflows

---

## Next Steps

1. ✅ Configure GitHub secrets
2. ✅ Update deployment paths in cd.yml
3. ✅ Push workflows to GitHub
4. ✅ Test by creating a pull request
5. ✅ Monitor first deployment
6. ✅ Add status badges to README
7. ✅ Set up branch protection rules
8. ✅ Create staging environment (optional)

---

## Support

- GitHub Actions Documentation: https://docs.github.com/actions
- Docker Documentation: https://docs.docker.com/
- FastAPI Deployment: https://fastapi.tiangolo.com/deployment/

For issues with this setup, check the workflow logs in the Actions tab or review the troubleshooting section above.

**🎉 Happy Deploying!**
