# DeployCraft

Interactive CLI tool for automated web application deployment, configuration, and monitoring on Linux servers.

## Installation

```bash
pip install deploycraft
```

## Quick Start

```bash
# First-time setup
deploycraft init

# Deploy a project
deploycraft deploy

# Check status
deploycraft status
```

## Supported Stacks

- Django (Gunicorn + systemd)
- FastAPI (Uvicorn + systemd)
- Next.js (PM2)
- React Vite (Nginx static)
- React CRA (Nginx static)
- Plain HTML (Nginx static)

## Features

- Interactive deployment wizard
- Auto-detection of project dependencies
- PostgreSQL, Redis, Celery auto-configuration
- Nginx reverse proxy + Let's Encrypt SSL
- Versioned deployments with rollback
- System monitoring with email alerts

## Development

```bash
pip install -e ".[dev]"
pytest
```
