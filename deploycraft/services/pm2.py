"""PM2 process management for Node.js applications.

Handles PM2 installation, process management, and monitoring.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console

from deploycraft.utils import error, run_cmd, step, success

console = Console()


def install_pm2() -> bool:
    """Install PM2 globally via npm.

    Returns:
        True if PM2 is installed successfully.
    """
    step("Installing PM2...")

    # Check if already installed
    result = run_cmd(["pm2", "--version"])
    if result.success:
        success(f"PM2 already installed: v{result.stdout.strip()}")
        return True

    result = run_cmd(["sudo", "npm", "install", "-g", "pm2"])
    if not result.success:
        error(f"PM2 installation failed: {result.stderr.strip()[:200]}")
        return False

    # Set up PM2 to start on boot
    result = run_cmd(["sudo", "pm2", "startup", "systemd"])
    if not result.success:
        # Try without sudo
        run_cmd(["pm2", "startup", "systemd"])

    success("PM2 installed globally")
    return True


def start_app(
    project_name: str,
    working_dir: Path,
    script: str = "npm",
    args: str = "start",
    interpreter: Optional[str] = None,
    env_file: Optional[Path] = None,
    port: Optional[int] = None,
    instances: int = 1,
) -> bool:
    """Start a Node.js application with PM2.

    Args:
        project_name: Name for the PM2 process.
        working_dir: Application directory.
        script: Script to run (default: "npm").
        args: Arguments for the script (default: "start").
        interpreter: Interpreter path (e.g., node path).
        env_file: Path to .env file to load.
        port: Port number to pass as PORT env var.
        instances: Number of instances (use 0 for max CPUs).

    Returns:
        True if the app was started successfully.
    """
    step(f"Starting {project_name} with PM2")

    # Delete existing process if any
    run_cmd(["pm2", "delete", project_name], timeout=10)

    cmd = [
        "pm2", "start", script,
        "--name", project_name,
        "--cwd", str(working_dir),
    ]

    if args:
        cmd.extend(["--", args])

    if interpreter:
        cmd.extend(["--interpreter", interpreter])

    if instances > 1 or instances == 0:
        cmd.extend(["-i", str(instances)])

    # Build environment variables
    env_vars = {}
    if port:
        env_vars["PORT"] = str(port)
    if env_file and env_file.exists():
        # PM2 can load .env files directly with ecosystem file,
        # but for simplicity we'll pass NODE_ENV and PORT
        env_vars["NODE_ENV"] = "production"

    # Add env vars to command
    for key, value in env_vars.items():
        cmd = ["env", f"{key}={value}"] + cmd

    result = run_cmd(cmd, cwd=working_dir, timeout=30)
    if result.success:
        # Save PM2 process list so it restarts on reboot
        run_cmd(["pm2", "save"])
        success(f"PM2 process '{project_name}' started")
        return True
    else:
        error(f"PM2 start failed: {result.stderr.strip()[:200]}")
        return False


def stop_app(project_name: str) -> bool:
    """Stop a PM2 process.

    Args:
        project_name: Name of the PM2 process.

    Returns:
        True if stopped successfully.
    """
    result = run_cmd(["pm2", "stop", project_name], timeout=10)
    if result.success:
        success(f"PM2 process '{project_name}' stopped")
    return result.success


def restart_app(project_name: str) -> bool:
    """Restart a PM2 process.

    Args:
        project_name: Name of the PM2 process.

    Returns:
        True if restarted successfully.
    """
    result = run_cmd(["pm2", "restart", project_name], timeout=30)
    if result.success:
        success(f"PM2 process '{project_name}' restarted")
    return result.success


def delete_app(project_name: str) -> bool:
    """Delete a PM2 process.

    Args:
        project_name: Name of the PM2 process.

    Returns:
        True if deleted.
    """
    result = run_cmd(["pm2", "delete", project_name], timeout=10)
    run_cmd(["pm2", "save"])
    return result.success


def is_running(project_name: str) -> bool:
    """Check if a PM2 process is running.

    Args:
        project_name: Name of the PM2 process.

    Returns:
        True if the process is online.
    """
    result = run_cmd(["pm2", "show", project_name])
    if result.success:
        return "online" in result.stdout.lower()
    return False


def get_process_info(project_name: str) -> Optional[dict]:
    """Get information about a PM2 process.

    Args:
        project_name: Name of the PM2 process.

    Returns:
        Dict with process info or None.
    """
    result = run_cmd(["pm2", "jlist"])
    if not result.success:
        return None

    import json

    try:
        processes = json.loads(result.stdout)
        for proc in processes:
            if proc.get("name") == project_name:
                return {
                    "name": proc["name"],
                    "status": proc.get("pm2_env", {}).get("status", "unknown"),
                    "pid": proc.get("pid", 0),
                    "memory": proc.get("monit", {}).get("memory", 0),
                    "cpu": proc.get("monit", {}).get("cpu", 0),
                    "uptime": proc.get("pm2_env", {}).get("pm_uptime", 0),
                }
    except (json.JSONDecodeError, KeyError):
        pass

    return None
