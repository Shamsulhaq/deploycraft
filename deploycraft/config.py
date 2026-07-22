"""Global configuration management for DeployCraft.

Handles reading/writing the global config file and per-project configs.
Config is stored in /etc/deploycraft/ (production) or ~/.config/deploycraft/ (dev/non-root).
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

# Config directories
_SYSTEM_CONFIG_DIR = Path("/etc/deploycraft")
_USER_CONFIG_DIR = Path.home() / ".config" / "deploycraft"


def get_config_dir() -> Path:
    """Get the appropriate config directory.

    Uses /etc/deploycraft/ if running as root, otherwise ~/.config/deploycraft/.
    """
    if os.geteuid() == 0:
        config_dir = _SYSTEM_CONFIG_DIR
    else:
        config_dir = _USER_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_projects_dir() -> Path:
    """Get the directory where project configs are stored."""
    projects_dir = get_config_dir() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir


def get_envs_dir() -> Path:
    """Get the directory where project .env files are stored securely."""
    envs_dir = get_config_dir() / "envs"
    envs_dir.mkdir(parents=True, exist_ok=True)
    return envs_dir


@dataclass
class SMTPConfig:
    """SMTP configuration for email alerts."""

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = ""
    use_tls: bool = True


@dataclass
class GlobalConfig:
    """Global DeployCraft configuration."""

    admin_email: str = ""
    smtp: SMTPConfig = field(default_factory=SMTPConfig)
    default_base_path: str = "/var/www"
    max_releases: int = 5
    monitor_interval_minutes: int = 5
    cpu_warning_threshold: int = 80
    cpu_critical_threshold: int = 90
    memory_warning_threshold: int = 80
    memory_critical_threshold: int = 90
    disk_warning_threshold: int = 80
    disk_critical_threshold: int = 90
    alert_cooldown_minutes: int = 30
    initialized: bool = False


@dataclass
class ProjectConfig:
    """Per-project configuration."""

    name: str
    stack: str  # django, fastapi, nextjs, react_vite, react, html
    base_path: str
    git_url: str
    branch: str = "main"
    domain: str = ""
    current_release: str = ""
    stable_release: str = ""
    releases: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)  # e.g., ["postgresql", "redis", "celery"]
    env_vars: dict[str, str] = field(default_factory=dict)
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    python_version: str = "3"
    node_version: str = "lts"
    created_at: str = ""
    last_deployed: str = ""
    port: int = 0  # Auto-assigned TCP port for gunicorn/uvicorn (8000, 8001, ...)


def load_global_config() -> GlobalConfig:
    """Load global config from disk, or return defaults if not found."""
    config_file = get_config_dir() / "config.json"
    if not config_file.exists():
        return GlobalConfig()

    try:
        data = json.loads(config_file.read_text())
        smtp_data = data.pop("smtp", {})
        smtp = SMTPConfig(**smtp_data) if smtp_data else SMTPConfig()
        return GlobalConfig(smtp=smtp, **data)
    except (json.JSONDecodeError, TypeError) as e:
        console.print(f"[yellow]Warning:[/yellow] Could not parse config file: {e}")
        return GlobalConfig()


def save_global_config(config: GlobalConfig) -> None:
    """Save global config to disk."""
    config_file = get_config_dir() / "config.json"
    data = asdict(config)
    config_file.write_text(json.dumps(data, indent=2))
    # Restrict permissions
    config_file.chmod(0o600)


def load_project_config(project_name: str) -> Optional[ProjectConfig]:
    """Load a project's configuration.

    Args:
        project_name: Name of the project.

    Returns:
        ProjectConfig if found, None otherwise.
    """
    project_file = get_projects_dir() / f"{project_name}.json"
    if not project_file.exists():
        return None

    try:
        data = json.loads(project_file.read_text())
        return ProjectConfig(**data)
    except (json.JSONDecodeError, TypeError) as e:
        console.print(f"[yellow]Warning:[/yellow] Could not parse project config: {e}")
        return None


def save_project_config(config: ProjectConfig) -> None:
    """Save a project's configuration to disk."""
    project_file = get_projects_dir() / f"{config.name}.json"
    data = asdict(config)
    project_file.write_text(json.dumps(data, indent=2))
    project_file.chmod(0o600)


def delete_project_config(project_name: str) -> bool:
    """Delete a project's configuration file.

    Returns:
        True if deleted, False if not found.
    """
    project_file = get_projects_dir() / f"{project_name}.json"
    if project_file.exists():
        project_file.unlink()
        return True
    return False


def get_all_projects() -> list[ProjectConfig]:
    """Load all project configurations."""
    projects = []
    projects_dir = get_projects_dir()
    for project_file in sorted(projects_dir.glob("*.json")):
        try:
            data = json.loads(project_file.read_text())
            projects.append(ProjectConfig(**data))
        except (json.JSONDecodeError, TypeError):
            continue
    return projects


def get_next_available_port(start_port: int = 8000) -> int:
    """Get the next available port for a new project.

    Scans all existing project configs and returns the next unused port.
    Starts from 8000 (first Django project), 8001 (second), etc.

    Args:
        start_port: Starting port number.

    Returns:
        Next available port number.
    """
    projects = get_all_projects()
    used_ports = {p.port for p in projects if p.port > 0}

    port = start_port
    while port in used_ports:
        port += 1
    return port


def run_init_wizard() -> None:
    """Run the first-time setup wizard.

    Prompts for admin email, SMTP configuration, and global preferences.
    """
    config = load_global_config()

    console.print(
        Panel(
            "[bold blue]DeployCraft Initial Setup[/bold blue]\n\n"
            "Configure admin email and SMTP for monitoring alerts.",
            title="Welcome to DeployCraft",
        )
    )

    # Admin email
    config.admin_email = Prompt.ask(
        "Admin email (for alerts)",
        default=config.admin_email or "",
    )

    # SMTP config
    if Confirm.ask("Configure SMTP for email alerts?", default=True):
        config.smtp.host = Prompt.ask("SMTP host", default=config.smtp.host or "smtp.gmail.com")
        config.smtp.port = int(
            Prompt.ask("SMTP port", default=str(config.smtp.port or 587))
        )
        config.smtp.username = Prompt.ask("SMTP username", default=config.smtp.username or "")
        config.smtp.password = Prompt.ask("SMTP password (hidden)", password=True)
        config.smtp.from_address = Prompt.ask(
            "From address", default=config.smtp.from_address or config.smtp.username
        )
        config.smtp.use_tls = Confirm.ask("Use TLS?", default=True)

    # Deployment preferences
    config.default_base_path = Prompt.ask(
        "Default base path for projects",
        default=config.default_base_path,
    )
    config.max_releases = int(
        Prompt.ask("Max releases to keep per project", default=str(config.max_releases))
    )

    # Monitor thresholds
    if Confirm.ask("Configure monitoring thresholds?", default=False):
        config.monitor_interval_minutes = int(
            Prompt.ask("Monitor interval (minutes)", default=str(config.monitor_interval_minutes))
        )
        config.cpu_warning_threshold = int(
            Prompt.ask("CPU warning threshold (%)", default=str(config.cpu_warning_threshold))
        )
        config.cpu_critical_threshold = int(
            Prompt.ask("CPU critical threshold (%)", default=str(config.cpu_critical_threshold))
        )
        config.memory_warning_threshold = int(
            Prompt.ask("Memory warning threshold (%)", default=str(config.memory_warning_threshold))
        )
        config.memory_critical_threshold = int(
            Prompt.ask(
                "Memory critical threshold (%)", default=str(config.memory_critical_threshold)
            )
        )
        config.disk_warning_threshold = int(
            Prompt.ask("Disk warning threshold (%)", default=str(config.disk_warning_threshold))
        )
        config.disk_critical_threshold = int(
            Prompt.ask("Disk critical threshold (%)", default=str(config.disk_critical_threshold))
        )

    config.initialized = True
    save_global_config(config)

    console.print("\n[green]✓[/green] Configuration saved successfully!")
    console.print(f"  Config file: {get_config_dir() / 'config.json'}")


def list_all_projects() -> None:
    """Display all managed projects in a table."""
    projects = get_all_projects()

    if not projects:
        console.print("[yellow]No projects configured yet.[/yellow]")
        console.print("Run [bold]deploycraft deploy[/bold] to deploy your first project.")
        return

    table = Table(title="Managed Projects")
    table.add_column("Project", style="cyan")
    table.add_column("Stack", style="magenta")
    table.add_column("Domain", style="green")
    table.add_column("Path", style="dim")
    table.add_column("Last Deployed", style="yellow")

    for project in projects:
        table.add_row(
            project.name,
            project.stack,
            project.domain or "-",
            project.base_path,
            project.last_deployed or "Never",
        )

    console.print(table)
