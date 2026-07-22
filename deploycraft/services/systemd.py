"""Systemd service management.

Generates systemd unit files from templates and manages service lifecycle.
"""

from pathlib import Path
from typing import Optional

from jinja2 import BaseLoader, Environment
from rich.console import Console

from deploycraft.utils import error, run_cmd, step, success

console = Console()

SYSTEMD_DIR = Path("/etc/systemd/system")

# Inline templates (used if template files don't exist)
GUNICORN_SERVICE_TEMPLATE = """\
[Unit]
Description=Gunicorn daemon for {{ project_name }}
After=network.target

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ working_dir }}
Environment="PATH={{ venv_path }}/bin:/usr/local/bin:/usr/bin"
EnvironmentFile={{ env_file }}
ExecStart={{ venv_path }}/bin/gunicorn {{ wsgi_app }} \\
    --workers {{ workers }} \\
    --bind unix:{{ socket_path }} \\
    --access-logfile {{ log_dir }}/gunicorn-access.log \\
    --error-logfile {{ log_dir }}/gunicorn-error.log \\
    --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

UVICORN_SERVICE_TEMPLATE = """\
[Unit]
Description=Uvicorn daemon for {{ project_name }}
After=network.target

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ working_dir }}
Environment="PATH={{ venv_path }}/bin:/usr/local/bin:/usr/bin"
EnvironmentFile={{ env_file }}
ExecStart={{ venv_path }}/bin/uvicorn {{ asgi_app }} \\
    --host 0.0.0.0 \\
    --port {{ port }} \\
    --workers {{ workers }} \\
    --access-log \\
    --log-level info
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

CELERY_WORKER_TEMPLATE = """\
[Unit]
Description=Celery Worker for {{ project_name }}
After=network.target redis.service

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ working_dir }}
Environment="PATH={{ venv_path }}/bin:/usr/local/bin:/usr/bin"
EnvironmentFile={{ env_file }}
ExecStart={{ venv_path }}/bin/celery -A {{ celery_app }} worker \\
    --loglevel=info \\
    --concurrency={{ concurrency }} \\
    --logfile={{ log_dir }}/celery-worker.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

CELERY_BEAT_TEMPLATE = """\
[Unit]
Description=Celery Beat for {{ project_name }}
After=network.target redis.service

[Service]
User={{ user }}
Group={{ group }}
WorkingDirectory={{ working_dir }}
Environment="PATH={{ venv_path }}/bin:/usr/local/bin:/usr/bin"
EnvironmentFile={{ env_file }}
ExecStart={{ venv_path }}/bin/celery -A {{ celery_app }} beat \\
    --loglevel=info \\
    --schedule={{ shared_dir }}/celerybeat-schedule \\
    --logfile={{ log_dir }}/celery-beat.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def create_gunicorn_service(
    project_name: str,
    working_dir: Path,
    venv_path: Path,
    wsgi_app: str,
    env_file: Path,
    user: str = "www-data",
    group: str = "www-data",
    workers: int = 3,
    log_dir: Optional[Path] = None,
) -> str:
    """Create a systemd service file for Gunicorn.

    Args:
        project_name: Name of the project.
        working_dir: Application working directory.
        venv_path: Path to Python virtualenv.
        wsgi_app: WSGI application path (e.g., "myapp.wsgi:application").
        env_file: Path to environment file.
        user: System user to run as.
        group: System group.
        workers: Number of Gunicorn workers.
        log_dir: Directory for log files.

    Returns:
        The service name.
    """
    service_name = f"{project_name}-gunicorn"
    log_dir = log_dir or (working_dir.parent / "shared" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    socket_path = f"/run/{project_name}/gunicorn.sock"

    # Ensure socket directory exists
    socket_dir = Path(f"/run/{project_name}")
    run_cmd(["sudo", "mkdir", "-p", str(socket_dir)])
    run_cmd(["sudo", "chown", f"{user}:{group}", str(socket_dir)])

    env = Environment(loader=BaseLoader())
    template = env.from_string(GUNICORN_SERVICE_TEMPLATE)
    content = template.render(
        project_name=project_name,
        working_dir=str(working_dir),
        venv_path=str(venv_path),
        wsgi_app=wsgi_app,
        env_file=str(env_file),
        user=user,
        group=group,
        workers=workers,
        socket_path=socket_path,
        log_dir=str(log_dir),
    )

    _write_service_file(service_name, content)
    return service_name


def create_uvicorn_service(
    project_name: str,
    working_dir: Path,
    venv_path: Path,
    asgi_app: str,
    env_file: Path,
    port: int = 8000,
    user: str = "www-data",
    group: str = "www-data",
    workers: int = 3,
    log_dir: Optional[Path] = None,
) -> str:
    """Create a systemd service file for Uvicorn.

    Returns:
        The service name.
    """
    service_name = f"{project_name}-uvicorn"
    log_dir = log_dir or (working_dir.parent / "shared" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=BaseLoader())
    template = env.from_string(UVICORN_SERVICE_TEMPLATE)
    content = template.render(
        project_name=project_name,
        working_dir=str(working_dir),
        venv_path=str(venv_path),
        asgi_app=asgi_app,
        env_file=str(env_file),
        port=port,
        user=user,
        group=group,
        workers=workers,
    )

    _write_service_file(service_name, content)
    return service_name


def create_celery_worker_service(
    project_name: str,
    working_dir: Path,
    venv_path: Path,
    celery_app: str,
    env_file: Path,
    user: str = "www-data",
    group: str = "www-data",
    concurrency: int = 4,
    log_dir: Optional[Path] = None,
) -> str:
    """Create a systemd service file for Celery worker.

    Returns:
        The service name.
    """
    service_name = f"{project_name}-celery-worker"
    log_dir = log_dir or (working_dir.parent / "shared" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=BaseLoader())
    template = env.from_string(CELERY_WORKER_TEMPLATE)
    content = template.render(
        project_name=project_name,
        working_dir=str(working_dir),
        venv_path=str(venv_path),
        celery_app=celery_app,
        env_file=str(env_file),
        user=user,
        group=group,
        concurrency=concurrency,
        log_dir=str(log_dir),
    )

    _write_service_file(service_name, content)
    return service_name


def create_celery_beat_service(
    project_name: str,
    working_dir: Path,
    venv_path: Path,
    celery_app: str,
    env_file: Path,
    shared_dir: Path,
    user: str = "www-data",
    group: str = "www-data",
    log_dir: Optional[Path] = None,
) -> str:
    """Create a systemd service file for Celery beat.

    Returns:
        The service name.
    """
    service_name = f"{project_name}-celery-beat"
    log_dir = log_dir or (working_dir.parent / "shared" / "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=BaseLoader())
    template = env.from_string(CELERY_BEAT_TEMPLATE)
    content = template.render(
        project_name=project_name,
        working_dir=str(working_dir),
        venv_path=str(venv_path),
        celery_app=celery_app,
        env_file=str(env_file),
        shared_dir=str(shared_dir),
        user=user,
        group=group,
        log_dir=str(log_dir),
    )

    _write_service_file(service_name, content)
    return service_name


def enable_service(service_name: str) -> bool:
    """Enable and start a systemd service.

    Runs daemon-reload first to pick up any new/changed service files.

    Args:
        service_name: Name of the service (without .service suffix).

    Returns:
        True if service was enabled and started successfully.
    """
    daemon_reload()
    step(f"Enabling service: {service_name}")
    result = run_cmd(["sudo", "systemctl", "enable", "--now", f"{service_name}.service"])
    if result.success:
        success(f"Service {service_name} is active")
        return True
    else:
        error(f"Failed to enable {service_name}: {result.stderr.strip()[:200]}")
        return False


def restart_service(service_name: str) -> bool:
    """Restart a systemd service.

    Args:
        service_name: Name of the service.

    Returns:
        True if restart was successful.
    """
    result = run_cmd(["sudo", "systemctl", "restart", f"{service_name}.service"])
    return result.success


def stop_service(service_name: str) -> bool:
    """Stop and disable a systemd service.

    Args:
        service_name: Name of the service.

    Returns:
        True if stopped successfully.
    """
    run_cmd(["sudo", "systemctl", "stop", f"{service_name}.service"])
    run_cmd(["sudo", "systemctl", "disable", f"{service_name}.service"])
    return True


def is_service_active(service_name: str) -> bool:
    """Check if a systemd service is active.

    Args:
        service_name: Name of the service.

    Returns:
        True if the service is currently active/running.
    """
    result = run_cmd(["sudo", "systemctl", "is-active", f"{service_name}.service"])
    return result.success and result.stdout.strip() == "active"


def remove_service(service_name: str) -> bool:
    """Stop, disable, and remove a systemd service file.

    Args:
        service_name: Name of the service.

    Returns:
        True if removed successfully.
    """
    stop_service(service_name)
    service_file = SYSTEMD_DIR / f"{service_name}.service"
    if service_file.exists():
        run_cmd(["sudo", "rm", str(service_file)])
    daemon_reload()
    return True


def daemon_reload() -> None:
    """Reload systemd daemon to pick up new/changed service files."""
    run_cmd(["sudo", "systemctl", "daemon-reload"])


def _write_service_file(service_name: str, content: str) -> None:
    """Write a systemd service file. Does NOT reload daemon — caller should do that once.

    Args:
        service_name: Name for the service file (without .service).
        content: The unit file content.
    """
    import tempfile

    service_path = SYSTEMD_DIR / f"{service_name}.service"
    step(f"Writing service file: {service_path}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".service", delete=False) as f:
        f.write(content)
        temp_path = f.name

    run_cmd(["sudo", "cp", temp_path, str(service_path)])
    run_cmd(["sudo", "chmod", "644", str(service_path)])
    Path(temp_path).unlink(missing_ok=True)

    success(f"Service file created: {service_name}")
