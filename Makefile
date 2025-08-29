# Makefile for Farmacias Siman MVP

.PHONY: help build run stop clean test lint format install dev prod logs shell

# Variables
DOCKER_COMPOSE = docker-compose
DOCKER = docker
APP_NAME = farmacias-siman-api
PYTHON = python3

# Default target
help:
	@echo "Available commands:"
	@echo "  make install    - Install Python dependencies"
	@echo "  make build      - Build Docker images"
	@echo "  make run        - Run the application with docker-compose"
	@echo "  make dev        - Run in development mode with hot reload"
	@echo "  make prod       - Build and run production image"
	@echo "  make stop       - Stop all containers"
	@echo "  make clean      - Remove containers and volumes"
	@echo "  make test       - Run tests"
	@echo "  make lint       - Run code linting"
	@echo "  make format     - Format code with black"
	@echo "  make logs       - Show container logs"
	@echo "  make shell      - Open shell in app container"
	@echo "  make db-shell   - Open PostgreSQL shell"
	@echo "  make migrate    - Run database migrations"

# Installation
install:
	pip install -r requirements.txt

# Docker commands
build:
	$(DOCKER_COMPOSE) build

run:
	$(DOCKER_COMPOSE) up -d

dev:
	$(DOCKER_COMPOSE) up

prod:
	$(DOCKER) build -f Dockerfile.prod -t $(APP_NAME):prod .
	$(DOCKER) run -d --name $(APP_NAME) -p 8000:8000 --env-file .env $(APP_NAME):prod

stop:
	$(DOCKER_COMPOSE) stop

down:
	$(DOCKER_COMPOSE) down

clean:
	$(DOCKER_COMPOSE) down -v
	$(DOCKER) system prune -f

# Development commands
test:
	pytest tests/ -v --cov=src --cov-report=html

lint:
	flake8 src/
	mypy src/

format:
	black src/
	isort src/

# Logs and debugging
logs:
	$(DOCKER_COMPOSE) logs -f app

logs-celery:
	$(DOCKER_COMPOSE) logs -f celery

logs-all:
	$(DOCKER_COMPOSE) logs -f

shell:
	$(DOCKER_COMPOSE) exec app /bin/bash

python-shell:
	$(DOCKER_COMPOSE) exec app python

# Database operations
db-shell:
	$(DOCKER_COMPOSE) exec db psql -U postgres

migrate:
	$(DOCKER_COMPOSE) exec app alembic upgrade head

# Celery operations
celery-status:
	$(DOCKER_COMPOSE) exec celery celery -A src.celery_app inspect active

celery-purge:
	$(DOCKER_COMPOSE) exec celery celery -A src.celery_app purge

flower:
	open http://localhost:5555

# Health checks
health:
	curl -f http://localhost:8000/health || exit 1

# Environment setup
env:
	cp .env.example .env
	@echo "Please edit .env file with your configuration"

# Quick start for development
quickstart: env build run
	@echo "Application is running at http://localhost:8000"
	@echo "API documentation at http://localhost:8000/docs"
	@echo "Flower (Celery monitoring) at http://localhost:5555"