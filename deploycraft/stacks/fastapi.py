"""FastAPI stack implementation.

Handles FastAPI deployment: virtualenv, pip install, Uvicorn service configuration,
and dependency detection (PostgreSQL, Redis, Celery).
"""

import os
from pathlib import Path

from rich.console import Console

from deploycraft.services import systemd
from deploycraft.stacks.base import (
    BaseStack,
    DetectedServices,
    StackType,
    register,
)
from deploycraft.utils import (
    error,
    run_cmd,
    step,
    success,
    warning,
)

console = Console()


@register(StackType.FASTAPI)
class FastAPIStack(BaseStack):
    """FastAPI deployment stack.

    Handles:
    - Python virtualenv creation
    - pip install from requirements.txt or pyproject.toml
    - Uvicorn systemd service
    - PostgreSQL/Redis/Celery detection
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.FASTAPI

    @property
    def display_name(self) -> str:
        return "FastAPI"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Detect FastAPI project dependencies."""
        detected = DetectedServices()
        requirements_content = ""

        # Read requirements.txt
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            requirements_content = req_file.read_text().lower()

        # Also check pyproject.toml
        pyproject_file = project_path / "pyproject.toml"
        if pyproject_file.exists():
            requirements_content += "\n" + pyproject_file.read_text().lower()

        # Detect PostgreSQL
        pg_indicators = [
            "psycopg2", "psycopg", "asyncpg", "sqlalchemy",
            "databases", "tortoise-orm", "sqlmodel",
        ]
        if any(indicator in requirements_content for indicator in pg_indicators):
            detected.needs_postgresql = True

        # Detect Redis
        redis_indicators = ["redis", "aioredis", "celery[redis]", "arq"]
        if any(indicator in requirements_content for indicator in redis_indicators):
            detected.needs_redis = True

        # Detect Celery
        if "celery" in requirements_content:
            detected.needs_celery = True
            if not detected.needs_redis:
                detected.needs_redis = True

        # Detect Celery Beat
        if "celery-beat" in requirements_content or "celery[beat]" in requirements_content:
            detected.needs_celery_beat = True

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

        # Always install uvicorn
        run_cmd([pip, "install", "uvicorn[standard]"])

        success("Dependencies installed")
        return True

    def build(self) -> bool:
        """FastAPI typically doesn't need a build step."""
        step("No build step needed for FastAPI")
        success("Ready")
        return True

    def run_migrations(self) -> bool:
        """Run Alembic migrations if present."""
        alembic_ini = self.project_path / "alembic.ini"
        if not alembic_ini.exists():
            step("No Alembic migrations found, skipping")
            return True

        step("Running Alembic migrations...")
        str(self.project_path / "venv" / "bin" / "python")
        alembic = str(self.project_path / "venv" / "bin" / "alembic")

        result = run_cmd(
            [alembic, "upgrade", "head"],
            cwd=self.project_path,
        )

        if result.success:
            success("Migrations applied")
            return True
        else:
            error(f"Migration failed: {result.stderr.strip()[:300]}")
            return False

    def get_process_command(self) -> list[str]:
        """Get the Uvicorn command."""
        venv_path = self.project_path / "venv"
        asgi_app = self._detect_asgi_app()
        return [
            str(venv_path / "bin" / "uvicorn"),
            asgi_app,
            "--host", "0.0.0.0",
            "--port", str(self.context.port),
            "--workers", str(self._calculate_workers()),
        ]

    def get_service_name(self) -> str:
        """Get the systemd service name and create the service file."""
        service_name = f"{self.project.name}-uvicorn"

        venv_path = self.project_path / "venv"
        asgi_app = self._detect_asgi_app()

        systemd.create_uvicorn_service(
            project_name=self.project.name,
            working_dir=self.project_path,
            venv_path=venv_path,
            asgi_app=asgi_app,
            env_file=self.context.env_file_path,
            port=self.context.port,
            workers=self._calculate_workers(),
        )

        return service_name

    def get_health_check_url(self) -> str:
        return f"http://localhost:{self.context.port}/"

    def get_log_paths(self) -> list[Path]:
        shared_logs = self.context.shared_path / "logs"
        return [
            shared_logs / "uvicorn-access.log",
            shared_logs / "uvicorn-error.log",
        ]

    # --- Private helpers ---

    def _detect_asgi_app(self) -> str:
        """Detect the ASGI application entry point.

        Looks for common FastAPI patterns: main:app, app.main:app, src.main:app
        """
        # Check common patterns
        candidates = [
            ("main.py", "main:app"),
            ("app/main.py", "app.main:app"),
            ("src/main.py", "src.main:app"),
            ("app.py", "app:app"),
            ("api/main.py", "api.main:app"),
        ]

        for file_path, module_path in candidates:
            if (self.project_path / file_path).exists():
                # Verify it actually contains a FastAPI app
                content = (self.project_path / file_path).read_text()
                if "FastAPI" in content or "fastapi" in content:
                    return module_path

        # Search for FastAPI() instantiation
        for py_file in self.project_path.rglob("*.py"):
            try:
                content = py_file.read_text()
                if "FastAPI()" in content or "= FastAPI(" in content:
                    # Convert file path to module path
                    rel = py_file.relative_to(self.project_path)
                    module = str(rel).replace("/", ".").replace(".py", "")
                    return f"{module}:app"
            except (PermissionError, OSError):
                continue

        # Fallback
        return "main:app"

    def _calculate_workers(self) -> int:
        """Calculate recommended Uvicorn worker count."""
        try:
            cpu_count = os.cpu_count() or 2
            return min(2 * cpu_count + 1, 9)
        except Exception:
            return 3
