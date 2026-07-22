"""React (Create React App) stack implementation.

Handles React CRA deployment: npm install, react-scripts build, Nginx static serving.
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


@register(StackType.REACT)
class ReactCRAStack(BaseStack):
    """React Create React App deployment stack.

    Handles:
    - Node.js dependency installation
    - react-scripts build (outputs to build/)
    - Nginx static file serving
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.REACT

    @property
    def display_name(self) -> str:
        return "React (CRA)"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Detect React CRA project dependencies."""
        detected = DetectedServices()
        detected.needs_nodejs = True
        detected.needs_nginx = True
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
            if not (self.project_path / "package-lock.json").exists():
                cmd = ["npm", "install"]

        result = run_cmd(cmd, cwd=self.project_path, timeout=300)
        if not result.success:
            error(f"Dependency installation failed: {result.stderr.strip()[:300]}")
            return False

        success("Dependencies installed")
        return True

    def build(self) -> bool:
        """Run react-scripts build for production."""
        step("Building React application...")

        pkg_manager = self._detect_package_manager()

        if pkg_manager == "yarn":
            cmd = ["yarn", "build"]
        elif pkg_manager == "pnpm":
            cmd = ["pnpm", "run", "build"]
        else:
            cmd = ["npm", "run", "build"]

        # CRA needs CI=true to not treat warnings as errors in some setups
        result = run_cmd(
            cmd,
            cwd=self.project_path,
            timeout=300,
            env={"CI": "true"},
        )
        if not result.success:
            error(f"Build failed: {result.stderr.strip()[:300]}")
            return False

        # Verify build directory was created
        build_dir = self.project_path / "build"
        if not build_dir.exists():
            error("Build completed but build/ directory not found")
            return False

        success(f"Build complete → {build_dir}")
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
        """The built output directory."""
        return self.project_path / "build"

    def get_log_paths(self) -> list[Path]:
        return [
            Path(f"/var/log/nginx/{self.project.name}-access.log"),
            Path(f"/var/log/nginx/{self.project.name}-error.log"),
        ]

    # --- Private helpers ---

    def _detect_package_manager(self) -> str:
        """Detect which package manager the project uses."""
        if (self.project_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (self.project_path / "yarn.lock").exists():
            return "yarn"
        return "npm"
