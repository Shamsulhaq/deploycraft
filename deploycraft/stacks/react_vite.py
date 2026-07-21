"""React Vite stack implementation.

Handles React + Vite deployment: npm install, vite build, Nginx static serving.
"""

from pathlib import Path

from rich.console import Console

from deploycraft.stacks.base import (
    BaseStack,
    DetectedServices,
    StackType,
    register,
)
from deploycraft.utils import error, run_cmd, step, success

console = Console()


@register(StackType.REACT_VITE)
class ReactViteStack(BaseStack):
    """React Vite deployment stack.

    Handles:
    - Node.js dependency installation
    - Vite production build (outputs to dist/)
    - Nginx static file serving
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.REACT_VITE

    @property
    def display_name(self) -> str:
        return "React (Vite)"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Detect React Vite project dependencies."""
        detected = DetectedServices()
        detected.needs_nodejs = True
        detected.needs_nginx = True
        # Static sites don't need PM2, PostgreSQL, or Redis typically
        return detected

    def install_dependencies(self) -> bool:
        """Install Node.js dependencies."""
        step("Installing Node.js dependencies...")

        pkg_manager = self._detect_package_manager()

        if pkg_manager == "yarn":
            cmd = ["yarn", "install", "--frozen-lockfile"]
        elif pkg_manager == "pnpm":
            cmd = ["pnpm", "install", "--frozen-lockfile"]
        else:
            cmd = ["npm", "ci"]
            if not (self.release_path / "package-lock.json").exists():
                cmd = ["npm", "install"]

        result = run_cmd(cmd, cwd=self.release_path, timeout=300)
        if not result.success:
            error(f"Dependency installation failed: {result.stderr.strip()[:300]}")
            return False

        success("Dependencies installed")
        return True

    def build(self) -> bool:
        """Run vite build for production."""
        step("Building React Vite application...")

        pkg_manager = self._detect_package_manager()

        if pkg_manager == "yarn":
            cmd = ["yarn", "build"]
        elif pkg_manager == "pnpm":
            cmd = ["pnpm", "run", "build"]
        else:
            cmd = ["npm", "run", "build"]

        result = run_cmd(cmd, cwd=self.release_path, timeout=300)
        if not result.success:
            error(f"Build failed: {result.stderr.strip()[:300]}")
            return False

        # Verify dist directory was created
        dist_dir = self.release_path / "dist"
        if not dist_dir.exists():
            error("Build completed but dist/ directory not found")
            return False

        success(f"Build complete → {dist_dir}")
        return True

    def get_process_command(self) -> list[str]:
        """Static sites don't have a process command."""
        return []

    def get_service_name(self) -> str:
        """Static sites are served by Nginx, no separate service."""
        return f"{self.project.name}-nginx"

    def get_health_check_url(self) -> str:
        return "http://localhost/"

    def get_working_directory(self) -> Path:
        """The built output directory."""
        return self.release_path / "dist"

    def get_log_paths(self) -> list[Path]:
        return [
            Path(f"/var/log/nginx/{self.project.name}-access.log"),
            Path(f"/var/log/nginx/{self.project.name}-error.log"),
        ]

    # --- Private helpers ---

    def _detect_package_manager(self) -> str:
        """Detect which package manager the project uses."""
        if (self.release_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (self.release_path / "yarn.lock").exists():
            return "yarn"
        return "npm"
