# DeployCraft

Interactive CLI tool for automated web application deployment, configuration, and monitoring on Linux servers.

[![PyPI version](https://img.shields.io/pypi/v/deploycraft.svg)](https://pypi.org/project/deploycraft/)
[![Python](https://img.shields.io/pypi/pyversions/deploycraft.svg)](https://pypi.org/project/deploycraft/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Installation

### Recommended: pipx (Ubuntu 23.04+, Debian 12+)

Modern Linux distributions restrict system-wide pip installs. Use `pipx` — it installs DeployCraft in its own virtual environment but makes the command globally available:

```bash
# Install pipx (if not already installed)
sudo apt install pipx -y

# Add pipx bin directory to PATH
pipx ensurepath
source ~/.bashrc    # or: source ~/.profile / restart terminal

# Install DeployCraft
pipx install deploycraft
```

> **Troubleshooting**: If you get `deploycraft: command not found` after installing, run:
> ```bash
> pipx ensurepath
> source ~/.bashrc
> ```
> Or manually add to PATH: `export PATH="$PATH:$HOME/.local/bin"`

### Alternative: pip with --break-system-packages

If you prefer a direct install (not recommended but works):

```bash
pip install --break-system-packages deploycraft
```

### Alternative: pip in a virtual environment

```bash
python3 -m venv /opt/deploycraft-env
/opt/deploycraft-env/bin/pip install deploycraft

# Create a symlink for global access
sudo ln -s /opt/deploycraft-env/bin/deploycraft /usr/local/bin/deploycraft
```

### Verify Installation

```bash
deploycraft --version
# DeployCraft v0.1.0
```

---

## Quick Start

```bash
# 1. First-time setup (configure admin email, SMTP for alerts)
deploycraft init

# 2. Deploy your first project
deploycraft deploy

# 3. Check status
deploycraft status
```

Or use the interactive shell — just run `deploycraft` with no arguments:

```bash
$ deploycraft

╭─────────────────────────────────────────────────────╮
│ DeployCraft v0.1.0 — Interactive Shell               │
│                                                      │
│ Type commands without the 'deploycraft' prefix.      │
│ ↑/↓ for history  |  Tab for completion  |  exit      │
╰─────────────────────────────────────────────────────╯

deploycraft> deploy
deploycraft> status
deploycraft> ssh-key show
deploycraft> exit
```

---

## Supported Stacks

| Stack | App Server | Process Manager |
|-------|-----------|-----------------|
| Django | Gunicorn | systemd |
| FastAPI | Uvicorn | systemd |
| Next.js | Node.js | PM2 |
| React (Vite) | Static build | Nginx |
| React (CRA) | Static build | Nginx |
| Plain HTML | Static files | Nginx |

---

## Features

- **Interactive deployment wizard** — guided step-by-step deployment
- **Auto-detection** — reads `requirements.txt`, `package.json` to detect PostgreSQL, Redis, Celery, etc.
- **Full service setup** — PostgreSQL, Redis, Celery worker + beat (auto-configured)
- **Nginx + SSL** — reverse proxy with Let's Encrypt certificates
- **Versioned deployments** — timestamped releases with one-command rollback
- **System monitoring** — CPU, memory, disk alerts via email
- **SSH key management** — generate deploy keys for private repo access
- **User management** — create Linux users with optional sudo
- **Interactive shell** — REPL mode with tab completion and history

---

## All Commands

### Setup

| Command | Description |
|---------|-------------|
| `deploycraft` | Open interactive shell (REPL mode) |
| `deploycraft init` | First-time setup: admin email, SMTP, preferences |

### Deployment

| Command | Description |
|---------|-------------|
| `deploycraft deploy` | Interactive wizard to deploy a new project |
| `deploycraft redeploy <project>` | Pull latest code, rebuild, and restart |
| `deploycraft rollback <project>` | Revert to the previous release |
| `deploycraft stable <project>` | Mark current release as stable (rollback floor) |

### Project Management

| Command | Description |
|---------|-------------|
| `deploycraft status` | Dashboard: all projects + system health |
| `deploycraft list` | List all managed projects |
| `deploycraft remove <project>` | Remove a project from DeployCraft |
| `deploycraft logs <project>` | Tail logs for a project's services |

### SSH Key Management

| Command | Description |
|---------|-------------|
| `deploycraft ssh-key` | Full wizard: generate key + show + instructions |
| `deploycraft ssh-key show` | Display the public key for adding to GitHub/GitLab |
| `deploycraft ssh-key generate` | Generate a new Ed25519 keypair (`--force` to overwrite) |
| `deploycraft ssh-key test <url>` | Test SSH connectivity to a Git provider |

### System User Management

| Command | Description |
|---------|-------------|
| `deploycraft user create` | Interactive wizard to create a Linux user |
| `deploycraft user delete <name>` | Delete a user (`--remove-home` to wipe home dir) |
| `deploycraft user sudo <name>` | Grant sudo privileges (`--revoke` to remove) |
| `deploycraft user list` | List all users with sudo/admin access |

### Monitoring

| Command | Description |
|---------|-------------|
| `deploycraft monitor start` | Enable system monitoring (systemd timer) |
| `deploycraft monitor stop` | Disable system monitoring |
| `deploycraft monitor status` | Show monitoring status and current metrics |

---

## How It Works

1. **`deploycraft deploy`** asks you to pick a stack (Django, Next.js, etc.)
2. You provide: project name, git URL, branch, domain
3. DeployCraft auto-detects what's needed (PostgreSQL, Redis, Celery, etc.)
4. It installs everything, creates databases, configures Nginx + SSL
5. Reports back with credentials and health check status
6. Asks if you want to deploy another project

Each deployment creates a timestamped release. If something goes wrong:

```bash
deploycraft rollback myproject    # Instantly reverts to previous version
```

---

## Supported Operating Systems

- Ubuntu 22.04+ / Debian 12+
- CentOS 9+ / RHEL 9+
- Fedora 38+
- Amazon Linux 2023+

Automatically detects the OS and uses the correct package manager (apt/dnf/yum).

---

## Upgrading

```bash
# With pipx
pipx upgrade deploycraft

# With pip
pip install --upgrade deploycraft
```

---

## Development

```bash
git clone https://github.com/Shamsulhaq/deploycraft.git
cd deploycraft
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

---

## License

MIT — see [LICENSE](LICENSE)
