"""Plain HTML stack implementation.

Handles static HTML/CSS/JS deployment: just clone and serve via Nginx.
The simplest stack - no build step, no process manager.
"""

from pathlib import Path

from rich.console import Console

from deploycraft.stacks.base import (
    BaseStack,
    DetectedServices,
    StackType,
    register,
)
from deploycraft.utils import step, success

console = Console()


@register(StackType.HTML)
class HTMLStack(BaseStack):
    """Plain HTML static site deployment stack.

    Handles:
    - No dependency installation needed
    - No build step needed
    - Nginx static file serving directly from the repository
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.HTML

    @property
    def display_name(self) -> str:
        return "Plain HTML"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Plain HTML only needs Nginx."""
        detected = DetectedServices()
        detected.needs_nginx = True
        return detected

    def install_dependencies(self) -> bool:
        """No dependencies to install for plain HTML."""
        step("No dependencies needed for static HTML")
        success("Ready")
        return True

    def build(self) -> bool:
        """No build step for plain HTML."""
        step("No build step needed for static HTML")
        success("Ready")
        return True

    def get_process_command(self) -> list[str]:
        """Static sites don't have a process command."""
        return []

    def get_service_name(self) -> str:
        """Static sites are served by Nginx."""
        return f"{self.project.name}-nginx"

    def get_health_check_url(self) -> str:
        return "http://localhost/"

    def get_working_directory(self) -> Path:
        """Serve directly from the release directory.

        If there's a public/ or dist/ subdirectory, use that instead.
        """
        # Check for common subdirectories
        for subdir in ["public", "dist", "www", "html", "site"]:
            candidate = self.project_path / subdir
            if candidate.is_dir() and (candidate / "index.html").exists():
                return candidate

        return self.project_path

    def get_log_paths(self) -> list[Path]:
        return [
            Path(f"/var/log/nginx/{self.project.name}-access.log"),
            Path(f"/var/log/nginx/{self.project.name}-error.log"),
        ]
