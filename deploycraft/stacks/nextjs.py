"""Next.js stack implementation.

Handles Next.js deployment: npm install, npm build, PM2 process management,
and Nginx reverse proxy configuration.
"""

from pathlib import Path

from rich.console import Console

from deploycraft.services import pm2
from deploycraft.stacks.base import (
    BaseStack,
    DetectedServices,
    StackType,
    register,
)
from deploycraft.utils import error, run_cmd, step, success

console = Console()


@register(StackType.NEXTJS)
class NextJSStack(BaseStack):
    """Next.js deployment stack.

    Handles:
    - Node.js dependency installation (npm/yarn/pnpm)
    - next build (production build)
    - PM2 process management
    - Nginx reverse proxy
    """

    @property
    def stack_type(self) -> StackType:
        return StackType.NEXTJS

    @property
    def display_name(self) -> str:
        return "Next.js"

    def detect_services(self, project_path: Path) -> DetectedServices:
        """Detect Next.js project dependencies."""
        detected = DetectedServices()
        detected.needs_nodejs = True
        detected.needs_pm2 = True
        detected.needs_nginx = True

        # Read package.json for additional services
        package_json = project_path / "package.json"
        if package_json.exists():
            import json

            try:
                pkg = json.loads(package_json.read_text())
                all_deps = {
                    **pkg.get("dependencies", {}),
                    **pkg.get("devDependencies", {}),
                }

                # Detect PostgreSQL
                pg_indicators = ["pg", "prisma", "typeorm", "sequelize", "knex", "@prisma/client"]
                if any(dep in all_deps for dep in pg_indicators):
                    detected.needs_postgresql = True

                # Detect Redis
                redis_indicators = ["redis", "ioredis", "bull", "bullmq"]
                if any(dep in all_deps for dep in redis_indicators):
                    detected.needs_redis = True

            except (json.JSONDecodeError, OSError):
                pass

        return detected

    def install_dependencies(self) -> bool:
        """Install Node.js dependencies."""
        step("Installing Node.js dependencies...")

        pkg_manager = self._detect_package_manager()

        if pkg_manager == "yarn":
            cmd = ["yarn", "install", "--frozen-lockfile", "--production=false"]
        elif pkg_manager == "pnpm":
            cmd = ["pnpm", "install", "--frozen-lockfile"]
        else:
            cmd = ["npm", "ci"]
            # Fallback to npm install if no lockfile
            if not (self.release_path / "package-lock.json").exists():
                cmd = ["npm", "install"]

        result = run_cmd(cmd, cwd=self.release_path, timeout=300)
        if not result.success:
            error(f"Dependency installation failed: {result.stderr.strip()[:300]}")
            return False

        success("Dependencies installed")
        return True

    def build(self) -> bool:
        """Run next build for production."""
        step("Building Next.js application...")

        pkg_manager = self._detect_package_manager()

        if pkg_manager == "yarn":
            cmd = ["yarn", "build"]
        elif pkg_manager == "pnpm":
            cmd = ["pnpm", "run", "build"]
        else:
            cmd = ["npm", "run", "build"]

        result = run_cmd(cmd, cwd=self.release_path, timeout=600)
        if not result.success:
            error(f"Build failed: {result.stderr.strip()[:300]}")
            return False

        # Verify .next directory was created
        next_dir = self.release_path / ".next"
        if not next_dir.exists():
            error("Build completed but .next directory not found")
            return False

        success("Build complete")
        return True

    def get_process_command(self) -> list[str]:
        """Get the Next.js start command."""
        return ["npm", "start"]

    def get_service_name(self) -> str:
        """PM2 manages the process, return the PM2 app name."""
        return f"{self.project.name}-nextjs"

    def get_health_check_url(self) -> str:
        return f"http://localhost:{self.context.port or 3000}/"

    def get_log_paths(self) -> list[Path]:
        return [
            Path.home() / ".pm2" / "logs" / f"{self.project.name}-out.log",
            Path.home() / ".pm2" / "logs" / f"{self.project.name}-error.log",
        ]

    def post_deploy_hook(self) -> bool:
        """Start or restart the PM2 process after deployment."""
        port = self.context.port or 3000

        # Check if process already running
        if pm2.is_running(self.project.name):
            return pm2.restart_app(self.project.name)

        return pm2.start_app(
            project_name=self.project.name,
            working_dir=self.release_path,
            script="npm",
            args="start",
            port=port,
        )

    # --- Private helpers ---

    def _detect_package_manager(self) -> str:
        """Detect which package manager the project uses.

        Returns:
            "npm", "yarn", or "pnpm"
        """
        if (self.release_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (self.release_path / "yarn.lock").exists():
            return "yarn"
        return "npm"
