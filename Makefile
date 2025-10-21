# Makefile for MelkAI Module Deployment

.PHONY: help deploy deploy-fast logs restart stop ssh clean build test

# Configuration
EC2_HOST := 18.118.110.218
EC2_USER := ubuntu
PEM_FILE := C:/Users/Zain/Downloads/agenticai_melkpm.pem
APP_DIR := /home/ubuntu/melkai-aimodule

help: ## Show this help message
	@echo "MelkAI Module - Docker Deployment Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

deploy: ## Deploy application to EC2 (full rebuild)
	@echo "Deploying to EC2..."
	@powershell -ExecutionPolicy Bypass -File deploy.ps1

deploy-fast: ## Deploy without rebuilding Docker images
	@echo "Fast deployment (skip rebuild)..."
	@powershell -ExecutionPolicy Bypass -File deploy.ps1 -SkipBuild

logs: ## View application logs
	@powershell -ExecutionPolicy Bypass -File deploy.ps1 -Logs

restart: ## Restart application containers
	@powershell -ExecutionPolicy Bypass -File deploy.ps1 -Restart

stop: ## Stop application containers
	@powershell -ExecutionPolicy Bypass -File deploy.ps1 -Stop

ssh: ## SSH into EC2 instance
	@ssh -i "$(PEM_FILE)" $(EC2_USER)@$(EC2_HOST)

clean: ## Clean up local deployment artifacts
	@echo "Cleaning up..."
	@if exist deploy_package rmdir /s /q deploy_package
	@echo "Done!"

build: ## Build Docker image locally (for testing)
	@echo "Building Docker image..."
	@docker build -t melkai-aimodule .

test-local: ## Run application locally with Docker
	@echo "Starting local Docker container..."
	@docker-compose up -d
	@echo "Application running at http://localhost:8000"
	@echo "Use 'make stop-local' to stop"

stop-local: ## Stop local Docker container
	@docker-compose down

health: ## Check application health
	@echo "Checking application health..."
	@curl -s http://$(EC2_HOST):8000/health | python -m json.tool

status: ## Check container status on EC2
	@ssh -i "$(PEM_FILE)" $(EC2_USER)@$(EC2_HOST) "cd $(APP_DIR) && sudo docker-compose ps"

shell: ## Open shell in running container
	@ssh -i "$(PEM_FILE)" $(EC2_USER)@$(EC2_HOST) "cd $(APP_DIR) && sudo docker-compose exec melkai-api /bin/bash"

update-env: ## Update .env file on EC2
	@echo "Uploading .env file..."
	@scp -i "$(PEM_FILE)" .env $(EC2_USER)@$(EC2_HOST):$(APP_DIR)/.env
	@echo "Restarting application..."
	@ssh -i "$(PEM_FILE)" $(EC2_USER)@$(EC2_HOST) "cd $(APP_DIR) && sudo docker-compose restart"
	@echo "Done!"
