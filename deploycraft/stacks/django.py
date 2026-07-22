"""Django stack implementation.

Handles Django-specific deployment: virtualenv, pip install, collectstatic,
migrations, superuser creation, Gunicorn service configuration, and
dependency detection (Celery, Redis, PostgreSQL).
"""

import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt

from deploycraft.services import systemd
from deploycraft.stacks.base import (
    BaseStack,
    DetectedServices,
    StackType,
    register,
)
from deploycraft.utils import (
    error,
    generate_password,
    run_cmd,
    step,
    success,
    warning,
)

console = Console()


@register(StackType.DJANGO)
class DjangoStack(BaseStack):
    """Django deployment stack.

    Handles:
    - Python virtualenv creation
    - pip install from requirements.txt or pyproject.toml
    - collectstatic
    - Django migrations
    - Superuser creation
    - Gunicorn systemd service
    - Celery/Redis detection
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.DJANGO

    @property
    def display_name(self) -> str:
        return "Django"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Detect Django project dependencies.

        Reads requirements.txt and/or pyproject.toml to determine what
        services are needed (PostgreSQL, Redis, Celery, etc.).
        """
        detected = DetectedServices()
        requirements_content = ""

        # Read requirements.txt
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            requirements_content = req_file.read_text().lower()

        # Also check pyproject.toml dependencies
        pyproject_file = project_path / "pyproject.toml"
        if pyproject_file.exists():
            requirements_content += "\n" + pyproject_file.read_text().lower()

        # Check for Pipfile
        pipfile = project_path / "Pipfile"
        if pipfile.exists():
            requirements_content += "\n" + pipfile.read_text().lower()

        # Detect PostgreSQL
        pg_indicators = ["psycopg2", "psycopg", "django.db.backends.postgresql", "dj-database-url"]
        if any(indicator in requirements_content for indicator in pg_indicators):
            detected.needs_postgresql = True

        # Detect Redis
        redis_indicators = ["redis", "django-redis", "celery[redis]"]
        if any(indicator in requirements_content for indicator in redis_indicators):
            detected.needs_redis = True

        # Detect Celery
        if "celery" in requirements_content:
            detected.needs_celery = True
            # Celery implies Redis if not already detected
            if not detected.needs_redis:
                detected.needs_redis = True

        # Detect Celery Beat
        beat_indicators = ["django-celery-beat", "celery-beat", "periodic_task"]
        if any(indicator in requirements_content for indicator in beat_indicators):
            detected.needs_celery_beat = True

        # Check Django settings for additional clues
        settings_content = self._read_settings(project_path)
        if settings_content:
            if "postgresql" in settings_content.lower():
                detected.needs_postgresql = True
            if "redis" in settings_content.lower() or "CACHES" in settings_content:
                detected.needs_redis = True
            if "CELERY" in settings_content:
                detected.needs_celery = True

        detected.needs_nginx = True
        return detected

    def install_dependencies(self) -> bool:
        """Create virtualenv and install Python dependencies."""
        step("Creating Python virtual environment...")

        venv_path = self.project_path / "venv"

        # Create virtualenv
        result = run_cmd(["python3", "-m", "venv", str(venv_path)])
        if not result.success:
            error(f"Failed to create virtualenv: {result.stderr.strip()[:200]}")
            return False

        pip = str(venv_path / "bin" / "pip")

        # Upgrade pip
        run_cmd([pip, "install", "--upgrade", "pip", "setuptools", "wheel"])

        # Install from requirements.txt
        req_file = self.project_path / "requirements.txt"
        if req_file.exists():
            step("Installing from requirements.txt...")
            result = run_cmd([pip, "install", "-r", str(req_file)], timeout=300)
            if not result.success:
                error(f"pip install failed: {result.stderr.strip()[:300]}")
                return False
        elif (self.project_path / "pyproject.toml").exists():
            step("Installing from pyproject.toml...")
            result = run_cmd([pip, "install", "."], cwd=self.project_path, timeout=300)
            if not result.success:
                error(f"pip install failed: {result.stderr.strip()[:300]}")
                return False
        else:
            warning("No requirements.txt or pyproject.toml found")
            return False

        # Always install gunicorn
        run_cmd([pip, "install", "gunicorn"])

        success("Dependencies installed")
        return True

    def build(self) -> bool:
        """Run collectstatic for Django."""
        step("Running collectstatic...")

        python = str(self.project_path / "venv" / "bin" / "python")
        manage_py = self._find_manage_py()

        if not manage_py:
            warning("manage.py not found, skipping collectstatic")
            return True

        result = run_cmd(
            [python, str(manage_py), "collectstatic", "--noinput"],
            cwd=self.project_path,
            env={"DJANGO_SETTINGS_MODULE": self._detect_settings_module()},
        )

        if result.success:
            success("Static files collected")
        else:
            warning(f"collectstatic had issues: {result.stderr.strip()[:200]}")
            # Don't fail the whole deploy for collectstatic issues

        return True

    def run_migrations(self) -> bool:
        """Run Django database migrations."""
        step("Running migrations...")

        python = str(self.project_path / "venv" / "bin" / "python")
        manage_py = self._find_manage_py()

        if not manage_py:
            warning("manage.py not found, skipping migrations")
            return True

        result = run_cmd(
            [python, str(manage_py), "migrate", "--noinput"],
            cwd=self.project_path,
        )

        if result.success:
            success("Migrations applied")
            return True
        else:
            error(f"Migration failed: {result.stderr.strip()[:300]}")
            return False

    def create_superuser(self) -> Optional[dict[str, str]]:
        """Create a Django superuser."""
        if not Confirm.ask("Create Django superuser?", default=True):
            return None

        python = str(self.project_path / "venv" / "bin" / "python")
        manage_py = self._find_manage_py()

        if not manage_py:
            warning("manage.py not found, cannot create superuser")
            return None

        username = Prompt.ask("Superuser username", default="admin")
        email = Prompt.ask("Superuser email", default=f"{username}@{self.context.domain}")
        password = generate_password(16)

        # Create superuser non-interactively
        result = run_cmd(
            [python, str(manage_py), "createsuperuser", "--noinput",
             "--username", username, "--email", email],
            cwd=self.project_path,
            env={
                "DJANGO_SUPERUSER_PASSWORD": password,
            },
        )

        if result.success:
            success(f"Superuser created: {username}")
            return {
                "username": username,
                "email": email,
                "password": password,
            }
        else:
            if "already exists" in result.stderr.lower() or "already taken" in result.stderr.lower():
                warning(f"Superuser '{username}' already exists")
            else:
                error(f"Superuser creation failed: {result.stderr.strip()[:200]}")
            return None

    def get_process_command(self) -> list[str]:
        """Get the Gunicorn command for this Django project."""
        venv_path = self.project_path / "venv"
        wsgi_app = self._detect_wsgi_app()
        port = self.context.port or self.project.port or 8000
        return [
            str(venv_path / "bin" / "gunicorn"),
            wsgi_app,
            "--workers", "3",
            "--bind", f"127.0.0.1:{port}",
        ]

    def get_service_name(self) -> str:
        """Get the systemd service name."""
        service_name = f"{self.project.name}-gunicorn"

        # Create the service file
        venv_path = self.project_path / "venv"
        wsgi_app = self._detect_wsgi_app()

        systemd.create_gunicorn_service(
            project_name=self.project.name,
            working_dir=self.project_path,
            venv_path=venv_path,
            wsgi_app=wsgi_app,
            env_file=self.context.env_file_path,
            workers=self._calculate_workers(),
            port=self.context.port or self.project.port or 8000,
        )

        return service_name

    def get_health_check_url(self) -> str:
        """Get the health check URL."""
        return f"http://localhost:{self.context.port}/"

    def get_log_paths(self) -> list[Path]:
        """Get Django/Gunicorn log paths."""
        shared_logs = self.context.shared_path / "logs"
        return [
            shared_logs / "gunicorn-access.log",
            shared_logs / "gunicorn-error.log",
            shared_logs / "celery-worker.log",
            shared_logs / "celery-beat.log",
        ]

    # --- Private helpers ---

    def _find_manage_py(self) -> Optional[Path]:
        """Find manage.py in the project."""
        # Direct in release root
        manage = self.project_path / "manage.py"
        if manage.exists():
            return manage

        # One level deep
        for child in self.project_path.iterdir():
            if child.is_dir():
                manage = child / "manage.py"
                if manage.exists():
                    return manage

        return None

    def _detect_wsgi_app(self) -> str:
        """Detect the WSGI application module.

        Looks for wsgi.py in the project to determine the module path.
        """
        # Look for wsgi.py
        for dirpath in self.project_path.rglob("wsgi.py"):
            # Get the parent directory name (the Django project module)
            module_name = dirpath.parent.name
            return f"{module_name}.wsgi:application"

        # Fallback: use project name
        return f"{self.project.name}.wsgi:application"

    def _detect_settings_module(self) -> str:
        """Detect the Django settings module."""
        # Look for settings.py
        for dirpath in self.project_path.rglob("settings.py"):
            module_name = dirpath.parent.name
            return f"{module_name}.settings"

        # Check for settings directory
        for dirpath in self.project_path.rglob("settings"):
            if dirpath.is_dir() and (dirpath / "__init__.py").exists():
                module_name = dirpath.parent.name
                return f"{module_name}.settings"

        return f"{self.project.name}.settings"

    def _read_settings(self, project_path: Path) -> str:
        """Try to read Django settings file content."""
        for settings_file in project_path.rglob("settings.py"):
            try:
                return settings_file.read_text()
            except (PermissionError, OSError):
                continue

        # Check settings directory
        for settings_dir in project_path.rglob("settings"):
            if settings_dir.is_dir():
                base_file = settings_dir / "base.py"
                if base_file.exists():
                    try:
                        return base_file.read_text()
                    except (PermissionError, OSError):
                        continue
        return ""

    def _calculate_workers(self) -> int:
        """Calculate recommended Gunicorn worker count.

        Formula: (2 * CPU cores) + 1, capped at 9.
        """
        try:
            cpu_count = os.cpu_count() or 2
            return min(2 * cpu_count + 1, 9)
        except Exception:
            return 3
