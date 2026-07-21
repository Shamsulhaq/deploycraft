# DeployCraft

> Interactive CLI tool for automated web application deployment, configuration, and monitoring on Linux servers.

---

## Overview

DeployCraft is a Python CLI tool that guides users through deploying web applications to Linux servers. It handles the full lifecycle: cloning code, installing dependencies, configuring databases, setting up process managers, configuring reverse proxies with SSL, managing versioned releases with rollback, and monitoring system health with email alerts.

The user runs one command and answers interactive prompts. DeployCraft does the rest — installs system packages, configures services, creates databases, generates credentials, and reports back when everything is running.

---

## Tech Stack (The Tool Itself)

- **Language**: Python 3.10+
- **CLI Framework**: `typer` (command routing, arguments, help text)
- **Terminal UI**: `rich` (colors, tables, progress bars, prompts)
- **Configuration Storage**: JSON/YAML files in `/etc/deploycraft/` (global) and per-project metadata
- **Installation**: `pip install deploycraft` or one-liner shell script

---

## Target Environment

- **Primary OS**: Ubuntu 22.04+, Debian 12+
- **Secondary OS**: CentOS 9+, RHEL 9+, Amazon Linux 2023+
- **Architecture**: x86_64 and ARM64
- **Requirement**: Root or sudo access
- **OS Abstraction**: Detect OS at runtime, route commands to correct package manager (`apt` / `dnf` / `yum`)

---

## Supported Application Stacks (v1)

| Stack | App Server | Process Manager | Dependency File |
|-------|-----------|-----------------|-----------------|
| Django | Gunicorn | systemd | `requirements.txt` / `pyproject.toml` |
| FastAPI | Uvicorn | systemd | `requirements.txt` / `pyproject.toml` |
| Next.js | Node.js | PM2 | `package.json` |
| React (Vite) | Static build | Nginx (static) | `package.json` |
| React (CRA) | Static build | Nginx (static) | `package.json` |
| Plain HTML | Static files | Nginx (static) | Directory presence |

### Auto-Detected Services (per stack)

| Service | Detected From | Action |
|---------|--------------|--------|
| PostgreSQL | `psycopg2`, `django.db.backends.postgresql` in requirements/settings | Install PostgreSQL, create DB + user |
| Redis | `redis`, `django-redis`, `celery[redis]` in requirements | Install Redis server |
| Celery | `celery` in requirements | Create systemd service for worker + beat |
| Celery Beat | `django-celery-beat` or celery beat config | Create separate systemd service |
| PM2 | Next.js or Node.js stack detected | Install PM2 globally via npm |
| Node.js | `package.json` present | Install via NodeSource (LTS version) |

---

## CLI Commands

```
# Interactive Shell (no args)
deploycraft                         # Opens interactive REPL shell

# Setup
deploycraft init                    # First-time setup: admin email, SMTP config, global preferences

# Deployment
deploycraft deploy                  # Interactive deployment wizard (main flow)
deploycraft redeploy <project>      # Pull latest code from git, rebuild, restart services
deploycraft rollback <project>      # Revert to previous release version
deploycraft stable <project>        # Mark current release as stable (rollback floor)

# Project Management
deploycraft status                  # Dashboard: all projects, health, system metrics
deploycraft list                    # List all managed projects with status
deploycraft remove <project>        # Remove a project (with confirmation)
deploycraft logs <project>          # Tail logs for a project's services

# SSH Key Management
deploycraft ssh-key                 # Full SSH key wizard (generate + show + instructions)
deploycraft ssh-key show            # Display the current public key
deploycraft ssh-key generate        # Generate new Ed25519 keypair (--force to overwrite)
deploycraft ssh-key test <url>      # Test SSH connectivity to GitHub/GitLab/Bitbucket

# System User Management
deploycraft user create             # Interactive wizard: create a Linux system user
deploycraft user delete <name>      # Delete a system user (--remove-home to wipe home dir)
deploycraft user sudo <name>        # Grant sudo/admin privileges (--revoke to remove)
deploycraft user list               # List all users with sudo privileges

# Monitoring
deploycraft monitor start           # Enable system monitoring daemon (systemd timer)
deploycraft monitor stop            # Disable system monitoring daemon
deploycraft monitor status          # Show monitoring status and current metrics
```

---

## Core Feature Specifications

### 1. Interactive Deployment Flow

```
deploycraft deploy
├── Select stack: [Django, FastAPI, Next.js, React Vite, React, Plain HTML]
├── Enter project name: my_project
├── Enter base path: /var/www/my_project (default: /var/www/<project_name>)
├── Enter GitHub URL: https://github.com/user/repo.git
├── Enter branch: main (default)
├── Enter domain name: myproject.com
├── [Auto-detect dependencies from repo files]
├── Display detected services: "Found: PostgreSQL, Redis, Celery, Celery Beat"
├── Confirm or modify detected services
├── Prompt for .env variables:
│   ├── Option A: Enter key-value pairs interactively
│   └── Option B: Provide path to existing .env file
├── Install system packages
├── Configure services (DB, Redis, process managers)
├── Create database + user with generated credentials
├── Clone repo → create release → set symlink
├── Install app dependencies (pip/npm)
├── Run migrations (if applicable)
├── Create superuser (Django: prompt or auto-generate)
├── Configure Nginx reverse proxy
├── Obtain SSL certificate via Certbot
├── Start all services
├── Run health check (HTTP request to domain)
├── Report: credentials, URLs, service status
└── Prompt: "Deploy another project? [y/N]"
```

### 2. Nginx + SSL Configuration

- Generate Nginx server block per project (reverse proxy for dynamic apps, static serving for builds)
- Domain-based routing (multiple projects on one server)
- Certbot integration for Let's Encrypt SSL (auto-renewal via systemd timer)
- HTTP → HTTPS redirect
- Security headers (X-Frame-Options, HSTS, etc.)

### 3. Environment File Management

- During deployment, prompt user for required `.env` variables
- Detect common variables from stack (e.g., `DATABASE_URL`, `SECRET_KEY`, `REDIS_URL`)
- Auto-populate database credentials and Redis URL from what was just configured
- Store `.env` in a secure location (`/etc/deploycraft/envs/<project>/.env`) with restricted permissions (600)
- Symlink into the project's active release

### 4. Versioned Deployments & Rollback

**Directory structure per project:**
```
/var/www/<project>/
├── releases/
│   ├── 20260721_140000/    # Timestamped release folders
│   ├── 20260721_160000/
│   └── 20260721_180000/
├── current -> releases/20260721_180000/   # Symlink to active release
├── shared/                 # Persistent files (uploads, logs)
└── .deploycraft.json       # Project metadata
```

**Rollback logic:**
- `deploycraft rollback <project>` → switches `current` symlink to previous release, restarts services
- `deploycraft stable <project>` → marks a release as the rollback floor (won't roll back past it)
- **Auto-stable**: If health check passes 5 minutes after deploy, automatically mark as stable
- Keep last N releases (configurable, default: 5), prune older ones

### 5. System Monitoring

**Approach**: Lightweight systemd timer (runs every 5 minutes)

**Metrics collected:**
- CPU usage (%)
- Memory usage (%)
- Disk usage (%) per mount
- Service status (all managed systemd units + PM2 processes)
- HTTP health check (GET request to each project's domain, expect 2xx)

**Alert thresholds (configurable):**
| Level | CPU | Memory | Disk |
|-------|-----|--------|------|
| Warning | >80% | >80% | >80% |
| Critical | >90% | >90% | >90% |

**Alert delivery:**
- SMTP email to configured admin address
- Cooldown: Don't re-alert for same issue within 30 minutes
- Alert includes: metric name, current value, threshold, timestamp, server hostname

**`deploycraft status` output:**
```
┌─────────────┬──────────┬─────────┬────────────┬──────────┐
│ Project     │ Stack    │ Status  │ Version    │ Health   │
├─────────────┼──────────┼─────────┼────────────┼──────────┤
│ mysite      │ Django   │ Running │ 2026-07-21 │ ✓ OK     │
│ frontend    │ Next.js  │ Running │ 2026-07-20 │ ✓ OK     │
│ landing     │ HTML     │ Running │ 2026-07-19 │ ✓ OK     │
└─────────────┴──────────┴─────────┴────────────┴──────────┘

CPU: 23%  |  Memory: 41%  |  Disk: 56%
```

### 6. SMTP / Email Configuration

Configured during `deploycraft init`:
- SMTP host, port, username, password
- From address
- Admin recipient address(es)
- Test email sent on configuration to verify

### 7. Interactive Shell Mode

Running `deploycraft` with no arguments opens a REPL:

```
$ deploycraft

╭─────────────────────────────────────────╮
│ DeployCraft v0.1.0 — Interactive Shell  │
│ ↑/↓ history | Tab completion | exit     │
╰─────────────────────────────────────────╯

deploycraft> deploy
deploycraft> status
deploycraft> ssh-key show
deploycraft> user create
deploycraft> exit
```

- Tab completion for all commands
- Command history persisted to `~/.config/deploycraft/.shell_history`
- Ctrl+C warns once, second Ctrl+C or `exit` quits
- All CLI commands work identically inside the shell

### 8. SSH Key Management

Server needs an SSH deploy key to clone private git repositories.

- **Auto-generate**: Ed25519 keypair stored in `~/.ssh/deploycraft_deploy`
- **Display**: Shows public key with exact instructions for GitHub/GitLab/Bitbucket
- **Test**: Verifies SSH auth against the remote before cloning
- **Integrated into deploy wizard**: Automatically prompts during `deploycraft deploy` when using SSH git URLs

### 9. System User Management

Create and manage Linux system users without manual shell commands.

- Create user: name, password, optional full name, optional sudo
- Grant/revoke sudo: adds to `sudo` (Ubuntu) and `wheel` (RHEL) groups
- Delete user: with optional home directory removal
- List admins: shows all users in sudo/wheel group
- Username validation: enforces Linux naming rules

---

## Project File Structure

```
deploycraft/
├── deploycraft/
│   ├── __init__.py
│   ├── cli.py                  # Typer app, all command definitions
│   ├── shell.py                # Interactive REPL shell mode
│   ├── config.py               # Global config read/write (/etc/deploycraft/config.json)
│   ├── os_detect.py            # OS detection, package manager abstraction
│   ├── utils.py                # Shell execution, logging, credential generation
│   ├── stacks/
│   │   ├── __init__.py         # Auto-registers all stacks on import
│   │   ├── base.py             # Abstract base class + stack registry
│   │   ├── django.py           # Django (Gunicorn + systemd)
│   │   ├── fastapi.py          # FastAPI (Uvicorn + systemd)
│   │   ├── nextjs.py           # Next.js (PM2)
│   │   ├── react_vite.py       # React Vite (Nginx static)
│   │   ├── react.py            # React CRA (Nginx static)
│   │   └── html.py             # Plain HTML (Nginx static)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── nginx.py            # Nginx config generation & management
│   │   ├── ssl.py              # Certbot / Let's Encrypt automation
│   │   ├── postgres.py         # PostgreSQL install, DB/user creation
│   │   ├── redis.py            # Redis install & configuration
│   │   ├── systemd.py          # Systemd unit file generation & control
│   │   ├── pm2.py              # PM2 install & process management
│   │   ├── git.py              # Clone, fetch, checkout operations
│   │   ├── node.py             # Node.js/npm installation
│   │   ├── ssh.py              # SSH keypair generation & deploy key management
│   │   └── users.py            # Linux user creation & sudo management
│   ├── deploy/
│   │   ├── __init__.py
│   │   ├── deployer.py         # Orchestrator: full deploy pipeline + redeploy
│   │   ├── rollback.py         # Release version management, symlink switching
│   │   ├── env_manager.py      # .env creation, secure storage, symlink
│   │   └── health_check.py     # HTTP health checks + status dashboard
│   └── monitor/
│       ├── __init__.py
│       ├── checker.py          # CPU, memory, disk, service metrics
│       ├── alerter.py          # SMTP email alerts with cooldown
│       └── scheduler.py        # Systemd timer management
├── templates/
│   ├── nginx/
│   │   ├── reverse_proxy.conf.j2
│   │   └── static_site.conf.j2
│   ├── systemd/
│   │   ├── gunicorn.service.j2
│   │   ├── uvicorn.service.j2
│   │   ├── celery_worker.service.j2
│   │   └── celery_beat.service.j2
│   └── monitor/
│       ├── deploycraft-monitor.timer.j2
│       └── deploycraft-monitor.service.j2
├── tests/
│   ├── test_config.py
│   ├── test_os_detect.py
│   ├── test_utils.py
│   ├── test_rollback.py
│   ├── test_stacks.py
│   └── test_ssh_users.py
├── pyproject.toml
├── README.md
├── AGENT.md                    # This file
└── .gitignore
```

---

## Configuration File Locations

| Path | Purpose |
|------|---------|
| `/etc/deploycraft/config.json` | Global config (SMTP, admin email, preferences) |
| `/etc/deploycraft/projects/<name>.json` | Per-project metadata (stack, paths, versions, services) |
| `/etc/deploycraft/envs/<name>/.env` | Project environment files (mode 600) |
| `/var/www/<name>/` | Project deployment directory |
| `/var/log/deploycraft/` | Tool logs |

---

## Key Design Principles

1. **Idempotent**: Running deploy twice should not break things. Detect existing installations.
2. **Non-destructive by default**: Never delete data without explicit confirmation.
3. **Fail-safe**: If any step fails, stop, report clearly, and leave system in a recoverable state.
4. **Credential security**: Generate strong passwords, never log them to files, display once to user.
5. **Extensible**: Adding a new stack = creating one new file in `stacks/` implementing the base interface.
6. **Minimal assumptions**: Don't assume anything is pre-installed. Install what's needed.

---

## Dependencies (Python packages)

```
typer>=0.9.0
rich>=13.0.0
jinja2>=3.1.0        # Template rendering for configs
pyyaml>=6.0          # Config file parsing
psutil>=5.9.0        # System metrics collection
paramiko>=3.0.0      # Future: remote deployment over SSH
```

---

## Future Roadmap (Not in v1)

- Laravel, Golang, Express.js stack support
- Web dashboard for monitoring
- Multi-server deployment (deploy to remote servers via SSH)
- Docker-based deployment option
- Webhook-based auto-deploy on git push
- Slack/Telegram alert channels
- Backup scheduling (database dumps)

---

## Project Name

**DeployCraft**
