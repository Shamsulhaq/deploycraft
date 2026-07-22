"""Git-based version management and rollback.

Uses a single project directory with git. Rollback = git checkout <previous_commit>.
No duplicate release directories — just track commit IDs.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm

from deploycraft.config import load_project_config, save_project_config
from deploycraft.stacks.base import StackType
from deploycraft.utils import error, header, run_cmd, step, success, warning

console = Console()


def get_project_path(base_path: str) -> Path:
    """Get the project source directory.

    Single directory — no releases/ structure.

    Args:
        base_path: Project base path (e.g., /var/www/myproject).

    Returns:
        Path to the project source.
    """
    return Path(base_path)


def get_current_commit(project_path: Path) -> Optional[str]:
    """Get the current commit hash of the project.

    Args:
        project_path: Path to the git repository.

    Returns:
        Full commit hash, or None if not a git repo.
    """
    result = run_cmd(["git", "rev-parse", "HEAD"], cwd=project_path)
    if result.success:
        return result.stdout.strip()
    return None


def get_current_commit_short(project_path: Path) -> Optional[str]:
    """Get the short commit hash.

    Args:
        project_path: Path to the git repository.

    Returns:
        Short commit hash (7 chars), or None.
    """
    result = run_cmd(["git", "rev-parse", "--short", "HEAD"], cwd=project_path)
    if result.success:
        return result.stdout.strip()
    return None


def get_commit_log(project_path: Path, count: int = 10) -> list[dict[str, str]]:
    """Get recent commit log.

    Args:
        project_path: Path to the git repository.
        count: Number of commits to show.

    Returns:
        List of dicts with 'hash', 'short_hash', 'message', 'date'.
    """
    result = run_cmd(
        ["git", "log", f"--max-count={count}", "--format=%H|%h|%s|%ci"],
        cwd=project_path,
    )
    if not result.success:
        return []

    commits = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "short_hash": parts[1],
                "message": parts[2],
                "date": parts[3],
            })
    return commits


def checkout_commit(project_path: Path, commit_hash: str) -> bool:
    """Checkout a specific commit.

    Args:
        project_path: Path to the git repository.
        commit_hash: Commit hash to checkout.

    Returns:
        True if checkout was successful.
    """
    result = run_cmd(["git", "checkout", commit_hash], cwd=project_path)
    if result.success:
        success(f"Checked out commit: {commit_hash[:7]}")
        return True
    else:
        error(f"Failed to checkout {commit_hash[:7]}: {result.stderr.strip()[:200]}")
        return False


def run_rollback(project_name: str) -> None:
    """Rollback a project to the previous commit.

    Args:
        project_name: Name of the project to rollback.
    """
    from deploycraft.services import pm2, systemd

    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    header(f"Rolling back: {project_name}")

    project_path = Path(project.base_path)

    # Get current and previous commits
    current = get_current_commit(project_path)
    if not current:
        error("Cannot determine current commit. Is this a git repository?")
        return

    # Get commit history
    commits = get_commit_log(project_path, count=10)
    if len(commits) < 2:
        error("No previous commit to rollback to.")
        return

    # Previous commit is the second one in the list
    previous = commits[1]

    # Check stable floor
    if project.stable_release and project.stable_release == previous["hash"]:
        warning("Rolling back to the stable release.")

    console.print(f"  Current:  [yellow]{commits[0]['short_hash']}[/yellow] — {commits[0]['message']}")
    console.print(f"  Rollback: [green]{previous['short_hash']}[/green] — {previous['message']}")

    if not Confirm.ask("\nProceed with rollback?", default=True):
        return

    # Checkout previous commit
    if not checkout_commit(project_path, previous["hash"]):
        error("Rollback failed.")
        return

    # Restart services
    step("Restarting services...")
    stack_type = StackType(project.stack)

    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_name = (
            f"{project_name}-gunicorn"
            if stack_type == StackType.DJANGO
            else f"{project_name}-uvicorn"
        )
        systemd.restart_service(service_name)
        if "celery" in project.services:
            systemd.restart_service(f"{project_name}-celery-worker")
        if "celery-beat" in project.services:
            systemd.restart_service(f"{project_name}-celery-beat")
    elif stack_type == StackType.NEXTJS:
        pm2.restart_app(project_name)

    # Update config
    project.current_release = previous["hash"]
    save_project_config(project)

    success(f"Rolled back to: {previous['short_hash']} — {previous['message']}")


def mark_stable(project_name: str) -> None:
    """Mark the current commit as stable (rollback floor).

    Args:
        project_name: Name of the project.
    """
    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    project_path = Path(project.base_path)
    current = get_current_commit(project_path)
    if not current:
        error("Cannot determine current commit.")
        return

    project.stable_release = current
    save_project_config(project)

    short = get_current_commit_short(project_path) or current[:7]
    success(f"Commit '{short}' marked as stable for '{project_name}'")
    console.print("[dim]This commit is now the rollback floor.[/dim]")
