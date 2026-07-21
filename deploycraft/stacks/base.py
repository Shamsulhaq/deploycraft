"""Abstract base class for all deployment stacks.

Every stack (Django, FastAPI, Next.js, etc.) must inherit from BaseStack
and implement the required methods. This defines the contract that the
deployment orchestrator uses.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from deploycraft.config import ProjectConfig
from deploycraft.os_detect import OSInfo, PackageManager


class StackType(Enum):
    """Available stack types."""

    DJANGO = "django"
    FASTAPI = "fastapi"
    NEXTJS = "nextjs"
    REACT_VITE = "react_vite"
    REACT = "react"
    HTML = "html"


@dataclass
class DetectedServices:
    """Services detected from project dependency files."""

    needs_postgresql: bool = False
    needs_redis: bool = False
    needs_celery: bool = False
    needs_celery_beat: bool = False
    needs_nodejs: bool = False
    needs_pm2: bool = False
    needs_nginx: bool = True  # Almost always needed
    python_packages: list[str] = field(default_factory=list)
    node_packages: list[str] = field(default_factory=list)
    extra_system_packages: list[str] = field(default_factory=list)

    def summary(self) -> list[str]:
        """Return a human-readable list of detected services."""
        services = []
        if self.needs_postgresql:
            services.append("PostgreSQL")
        if self.needs_redis:
            services.append("Redis")
        if self.needs_celery:
            services.append("Celery Worker")
        if self.needs_celery_beat:
            services.append("Celery Beat")
        if self.needs_nodejs:
            services.append("Node.js")
        if self.needs_pm2:
            services.append("PM2")
        if self.needs_nginx:
            services.append("Nginx")
        return services


@dataclass
class StackContext:
    """Context passed to stack operations during deployment."""

    project_config: ProjectConfig
    os_info: OSInfo
    package_manager: PackageManager
    release_path: Path  # Path to current release directory
    shared_path: Path  # Path to shared directory (uploads, logs)
    env_file_path: Path  # Path to the .env file
    domain: str = ""
    port: int = 8000  # Default app port


class BaseStack(ABC):
    """Abstract base class for deployment stacks.

    Each stack implements methods for:
    - Detecting required services from project files
    - Installing application dependencies
    - Building the project (if needed)
    - Starting/stopping the application
    - Running migrations (if applicable)
    - Health checking
    """

    def __init__(self, context: StackContext) -> None:
        self.context = context
        self.project = context.project_config
        self.os_info = context.os_info
        self.pkg = context.package_manager
        self.release_path = context.release_path

    @property
    @abstractmethod
    def stack_type(self) -> StackType:
        """Return the stack type enum value."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for this stack."""
        ...

    @abstractmethod
    def detect_services(self, project_path: Path) -> DetectedServices:
        """Analyze project files to detect required services.

        Args:
            project_path: Path to the cloned project source.

        Returns:
            DetectedServices with flags for what needs to be installed.
        """
        ...

    @abstractmethod
    def install_dependencies(self) -> bool:
        """Install application-level dependencies (pip install, npm install, etc.).

        Returns:
            True if successful, False otherwise.
        """
        ...

    @abstractmethod
    def build(self) -> bool:
        """Build the project (collectstatic, npm build, etc.).

        Returns:
            True if successful, False otherwise.
        """
        ...

    @abstractmethod
    def get_process_command(self) -> list[str]:
        """Get the command to start the application process.

        Returns:
            Command as a list of strings (e.g., ["gunicorn", "myapp.wsgi:application"]).
        """
        ...

    @abstractmethod
    def get_service_name(self) -> str:
        """Get the systemd service name for this application.

        Returns:
            Service name (e.g., "myproject-gunicorn").
        """
        ...

    def run_migrations(self) -> bool:
        """Run database migrations if applicable.

        Default implementation does nothing. Override for Django/FastAPI.

        Returns:
            True if successful (or not applicable), False on failure.
        """
        return True

    def create_superuser(self) -> Optional[dict[str, str]]:
        """Create an admin/superuser if applicable.

        Default implementation returns None. Override for Django.

        Returns:
            Dict with credentials (e.g., {"username": ..., "password": ...}) or None.
        """
        return None

    def post_deploy_hook(self) -> bool:
        """Run any post-deployment actions specific to this stack.

        Default implementation does nothing.

        Returns:
            True if successful.
        """
        return True

    def get_health_check_url(self) -> str:
        """Get the URL to check for application health.

        Returns:
            URL string (e.g., "http://localhost:8000/health/").
        """
        return f"http://localhost:{self.context.port}/"

    def get_log_paths(self) -> list[Path]:
        """Get paths to relevant log files for this stack.

        Returns:
            List of log file paths.
        """
        return [
            self.context.shared_path / "logs" / "app.log",
        ]

    def get_working_directory(self) -> Path:
        """Get the working directory for the application process.

        Returns:
            Path to the directory where the app should run from.
        """
        return self.release_path

    def get_environment_variables(self) -> dict[str, str]:
        """Get additional environment variables needed by this stack.

        Returns:
            Dict of env var name → value.
        """
        return {}


# --- Stack registry ---

_STACK_REGISTRY: dict[StackType, type[BaseStack]] = {}


def register_stack(stack_class: type[BaseStack]) -> type[BaseStack]:
    """Decorator to register a stack implementation.

    Usage:
        @register_stack
        class DjangoStack(BaseStack):
            ...
    """
    # We need to instantiate temporarily to get stack_type,
    # so instead we use a class variable approach
    stack_type = stack_class.__dict__.get("_stack_type")
    if stack_type is None:
        # Try to get from property - create a minimal check
        for attr_name in dir(stack_class):
            if attr_name == "stack_type":
                # For abstract property, we check if it's overridden
                break
    _STACK_REGISTRY[stack_type] = stack_class
    return stack_class


def register(stack_type: StackType):
    """Decorator to register a stack class with a given stack type.

    Usage:
        @register(StackType.DJANGO)
        class DjangoStack(BaseStack):
            ...
    """

    def decorator(cls: type[BaseStack]) -> type[BaseStack]:
        _STACK_REGISTRY[stack_type] = cls
        return cls

    return decorator


def get_stack_class(stack_type: StackType) -> Optional[type[BaseStack]]:
    """Get the stack class for a given stack type.

    Args:
        stack_type: The StackType enum value.

    Returns:
        The stack class, or None if not registered.
    """
    return _STACK_REGISTRY.get(stack_type)


def get_available_stacks() -> dict[StackType, type[BaseStack]]:
    """Get all registered stack implementations.

    Returns:
        Dictionary mapping StackType to stack class.
    """
    return dict(_STACK_REGISTRY)


# Stack display info for the interactive chooser
STACK_CHOICES = [
    (StackType.DJANGO, "Django", "Python web framework (Gunicorn + systemd)"),
    (StackType.FASTAPI, "FastAPI", "Python async framework (Uvicorn + systemd)"),
    (StackType.NEXTJS, "Next.js", "React framework with SSR (PM2)"),
    (StackType.REACT_VITE, "React (Vite)", "React SPA with Vite build (Nginx static)"),
    (StackType.REACT, "React (CRA)", "React SPA with Create React App (Nginx static)"),
    (StackType.HTML, "Plain HTML", "Static HTML/CSS/JS files (Nginx static)"),
]
