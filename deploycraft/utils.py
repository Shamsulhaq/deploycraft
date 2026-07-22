"""Utility functions for DeployCraft.

Shell command execution, logging, password generation, and common helpers.
"""

import logging
import secrets
import string
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

console = Console()

# --- Logging setup ---

LOG_DIR = Path("/var/log/deploycraft")


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure logging with rich handler.

    Args:
        verbose: If True, set level to DEBUG.

    Returns:
        Configured logger instance.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Determine log file location - try system dir first, fall back to user dir
    log_file = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / "deploycraft.log"
        # Test if we can actually write to it
        log_file.touch(exist_ok=True)
    except (PermissionError, OSError):
        log_file = None

    if log_file is None:
        log_dir = Path.home() / ".local" / "share" / "deploycraft" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "deploycraft.log"

    logger = logging.getLogger("deploycraft")
    logger.setLevel(level)

    # File handler
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(file_handler)
    except (PermissionError, OSError):
        pass  # Skip file logging if we can't write anywhere

    # Rich console handler (only warnings+ to avoid clutter)
    console_handler = RichHandler(console=console, show_path=False, show_time=False)
    console_handler.setLevel(logging.WARNING if not verbose else logging.DEBUG)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


# --- Shell execution ---


@dataclass
class CommandResult:
    """Result of a shell command execution."""

    returncode: int
    stdout: str
    stderr: str
    command: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def run_cmd(
    cmd: list[str],
    *,
    cwd: Optional[str | Path] = None,
    env: Optional[dict[str, str]] = None,
    capture: bool = True,
    check: bool = False,
    show_output: bool = False,
    timeout: Optional[int] = None,
) -> CommandResult:
    """Execute a shell command safely.

    Args:
        cmd: Command as a list of strings (no shell=True for safety).
        cwd: Working directory for the command.
        env: Additional environment variables (merged with current env).
        capture: Whether to capture stdout/stderr.
        check: If True, raise on non-zero exit code.
        show_output: If True, stream output to console in real-time.
        timeout: Timeout in seconds.

    Returns:
        CommandResult with returncode, stdout, stderr.

    Raises:
        subprocess.CalledProcessError: If check=True and command fails.
        subprocess.TimeoutExpired: If timeout is exceeded.
    """
    import os

    cmd_str = " ".join(cmd)
    logger.debug(f"Running: {cmd_str}")

    full_env = None
    if env:
        full_env = {**os.environ, **env}

    try:
        if show_output and not capture:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=full_env,
                timeout=timeout,
            )
            return CommandResult(
                returncode=result.returncode,
                stdout="",
                stderr="",
                command=cmd_str,
            )

        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if show_output and result.stdout:
            console.print(result.stdout, end="")

        if result.returncode != 0:
            logger.debug(f"Command failed (exit {result.returncode}): {result.stderr.strip()}")

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=cmd_str,
        )

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout}s: {cmd_str}")
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
            command=cmd_str,
        )
    except FileNotFoundError:
        logger.error(f"Command not found: {cmd[0]}")
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=f"Command not found: {cmd[0]}",
            command=cmd_str,
        )


def run_cmd_or_fail(
    cmd: list[str],
    *,
    error_msg: str = "",
    cwd: Optional[str | Path] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[int] = None,
) -> CommandResult:
    """Run a command and exit with error message if it fails.

    Args:
        cmd: Command as a list of strings.
        error_msg: Custom error message to display on failure.
        cwd: Working directory.
        env: Additional environment variables.
        timeout: Timeout in seconds.

    Returns:
        CommandResult (only on success).
    """
    result = run_cmd(cmd, cwd=cwd, env=env, timeout=timeout)
    if not result.success:
        msg = error_msg or f"Command failed: {result.command}"
        console.print(f"[red]✗ {msg}[/red]")
        if result.stderr:
            console.print(f"  [dim]{result.stderr.strip()[:200]}[/dim]")
        raise SystemExit(1)
    return result


# --- Password and credential generation ---


def generate_password(length: int = 24) -> str:
    """Generate a secure random password.

    Args:
        length: Length of the password.

    Returns:
        Random password string (alphanumeric + some symbols).
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    # Ensure at least one of each category
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%&*"),
    ]
    password.extend(secrets.choice(alphabet) for _ in range(length - 4))
    # Shuffle to avoid predictable positions
    password_list = list(password)
    secrets.SystemRandom().shuffle(password_list)
    return "".join(password_list)


def generate_db_name(project_name: str) -> str:
    """Generate a database name from a project name.

    Convention: project_name + _db suffix (e.g., backend_db)

    Args:
        project_name: The project name.

    Returns:
        Sanitized database name (lowercase, underscores, max 63 chars).
    """
    name = project_name.lower().replace("-", "_").replace(" ", "_")
    # Remove non-alphanumeric/underscore chars
    name = "".join(c for c in name if c.isalnum() or c == "_")
    # Ensure it starts with a letter
    if name and not name[0].isalpha():
        name = "db_" + name
    # Add _db suffix
    if not name:
        return "deploycraft_db"
    name = f"{name}_db"
    return name[:63]


def generate_db_user(project_name: str) -> str:
    """Generate a database username from a project name.

    Convention: project_name + _user suffix (e.g., backend_user)

    Args:
        project_name: The project name.

    Returns:
        Sanitized database username.
    """
    user = project_name.lower().replace("-", "_").replace(" ", "_")
    user = "".join(c for c in user if c.isalnum() or c == "_")
    if user and not user[0].isalpha():
        user = "u_" + user
    user = f"{user}_user"
    return user[:63] or "deploycraft_user"


def generate_secret_key(length: int = 50) -> str:
    """Generate a Django-style secret key.

    Returns:
        Random string suitable for Django SECRET_KEY.
    """
    chars = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
    return "".join(secrets.choice(chars) for _ in range(length))


# --- Timestamp helpers ---


def timestamp() -> str:
    """Get current timestamp in YYYYMMDD_HHMMSS format for release directories."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def human_timestamp() -> str:
    """Get current timestamp in human-readable format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --- Display helpers ---


def step(message: str) -> None:
    """Display a step message with a bullet point."""
    console.print(f"  [blue]→[/blue] {message}")


def success(message: str) -> None:
    """Display a success message with a checkmark."""
    console.print(f"  [green]✓[/green] {message}")


def error(message: str) -> None:
    """Display an error message with an X."""
    console.print(f"  [red]✗[/red] {message}")


def warning(message: str) -> None:
    """Display a warning message."""
    console.print(f"  [yellow]⚠[/yellow] {message}")


def header(message: str) -> None:
    """Display a section header."""
    console.print(f"\n[bold cyan]{message}[/bold cyan]")
    console.print("[dim]" + "─" * len(message) + "[/dim]")


# --- File helpers ---


def ensure_dir(path: Path, mode: int = 0o755) -> Path:
    """Create a directory if it doesn't exist.

    Args:
        path: Directory path.
        mode: Directory permissions.

    Returns:
        The path (for chaining).
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(mode)
    except PermissionError:
        pass
    return path


def write_file_secure(path: Path, content: str, mode: int = 0o600) -> None:
    """Write content to a file with restricted permissions.

    Args:
        path: File path.
        content: File content.
        mode: File permissions (default: owner read/write only).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
