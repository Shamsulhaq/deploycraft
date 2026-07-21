"""Release version management and rollback.

Manages the release directory structure, symlinks, and rollback operations.
"""

import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm

from deploycraft.config import load_project_config, save_project_config
from deploycraft.stacks.base import StackType
from deploycraft.utils import ensure_dir, error, header, step, success, warning

console = Console()


def create_release_dir(base_path: str, release_timestamp: str) -> Path:
    """Create a new release directory.

    Args:
        base_path: Project base path (e.g., /var/www/myproject).
        release_timestamp: Timestamp string for the release (e.g., 20260721_140000).

    Returns:
        Path to the newly created release directory.
    """
    releases_dir = Path(base_path) / "releases"
    release_path = releases_dir / release_timestamp
    ensure_dir(release_path)
    return release_path


def set_current_symlink(base_path: str, release_timestamp: str) -> bool:
    """Set the 'current' symlink to point to a specific release.

    Args:
        base_path: Project base path.
        release_timestamp: Release to point to.

    Returns:
        True if symlink was set successfully.
    """
    current_link = Path(base_path) / "current"
    target = Path(base_path) / "releases" / release_timestamp

    if not target.exists():
        error(f"Release directory not found: {target}")
        return False

    # Remove existing symlink
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()

    current_link.symlink_to(target)
    success(f"Active release: {release_timestamp}")
    return True


def get_current_release(base_path: str) -> Optional[str]:
    """Get the currently active release timestamp.

    Args:
        base_path: Project base path.

    Returns:
        Release timestamp string, or None if no current release.
    """
    current_link = Path(base_path) / "current"
    if current_link.is_symlink():
        target = current_link.resolve()
        return target.name
    return None


def get_previous_release(base_path: str) -> Optional[str]:
    """Get the release before the current one.

    Args:
        base_path: Project base path.

    Returns:
        Previous release timestamp, or None if there's no previous release.
    """
    releases = list_releases(base_path)
    current = get_current_release(base_path)

    if not current or len(releases) < 2:
        return None

    try:
        current_idx = releases.index(current)
        if current_idx > 0:
            return releases[current_idx - 1]
    except ValueError:
        pass

    return None


def list_releases(base_path: str) -> list[str]:
    """List all releases in chronological order.

    Args:
        base_path: Project base path.

    Returns:
        List of release timestamp strings, oldest first.
    """
    releases_dir = Path(base_path) / "releases"
    if not releases_dir.exists():
        return []

    releases = sorted([
        d.name for d in releases_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])
    return releases


def run_rollback(project_name: str) -> None:
    """Rollback a project to the previous release.

    Args:
        project_name: Name of the project to rollback.
    """
    from deploycraft.services import pm2, systemd

    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    header(f"Rolling back: {project_name}")

    current = get_current_release(project.base_path)
    previous = get_previous_release(project.base_path)

    if not previous:
        error("No previous release to rollback to.")
        return

    # Check if previous release is below the stable floor
    if project.stable_release:
        releases = list_releases(project.base_path)
        try:
            stable_idx = releases.index(project.stable_release)
            prev_idx = releases.index(previous)
            if prev_idx < stable_idx:
                error(
                    f"Cannot rollback past stable release: {project.stable_release}\n"
                    f"Use 'deploycraft stable {project_name}' to update the stable marker."
                )
                return
        except ValueError:
            pass

    console.print(f"  Current release: [yellow]{current}[/yellow]")
    console.print(f"  Rolling back to: [green]{previous}[/green]")

    if not Confirm.ask("Proceed with rollback?", default=True):
        return

    # Switch symlink
    if not set_current_symlink(project.base_path, previous):
        error("Failed to switch release symlink")
        return

    # Restart services
    step("Restarting services...")
    stack_type = StackType(project.stack)

    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_name = f"{project_name}-gunicorn" if stack_type == StackType.DJANGO else f"{project_name}-uvicorn"
        systemd.restart_service(service_name)
        if "celery" in project.services:
            systemd.restart_service(f"{project_name}-celery-worker")
        if "celery-beat" in project.services:
            systemd.restart_service(f"{project_name}-celery-beat")
    elif stack_type == StackType.NEXTJS:
        pm2.restart_app(project_name)

    # Update config
    project.current_release = previous
    save_project_config(project)

    success(f"Rolled back to release: {previous}")


def mark_stable(project_name: str) -> None:
    """Mark the current release as stable (rollback floor).

    Args:
        project_name: Name of the project.
    """
    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    current = get_current_release(project.base_path)
    if not current:
        error("No active release found.")
        return

    project.stable_release = current
    save_project_config(project)

    success(f"Release '{current}' marked as stable for '{project_name}'")
    console.print("[dim]Rollback will not go past this release.[/dim]")


def prune_old_releases(base_path: str, max_releases: int = 5) -> None:
    """Remove old releases beyond the max limit.

    Keeps the most recent N releases. Never removes the stable release.

    Args:
        base_path: Project base path.
        max_releases: Maximum number of releases to keep.
    """
    releases = list_releases(base_path)
    if len(releases) <= max_releases:
        return

    current = get_current_release(base_path)
    to_remove = releases[:-max_releases]

    for release in to_remove:
        # Never remove current or stable
        if release == current:
            continue
        release_path = Path(base_path) / "releases" / release
        try:
            shutil.rmtree(release_path)
            step(f"Pruned old release: {release}")
        except OSError as e:
            warning(f"Could not remove {release}: {e}")
