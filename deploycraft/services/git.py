"""Git operations for deployment.

Handles cloning repositories, fetching updates, and checking out specific branches/tags.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console

from deploycraft.utils import error, run_cmd, step, success

console = Console()


def clone_repo(
    git_url: str,
    target_path: Path,
    branch: str = "main",
    depth: Optional[int] = None,
) -> bool:
    """Clone a git repository to the target path.

    Full clone by default (no --depth) so git history is available for rollback.

    Args:
        git_url: The HTTPS or SSH URL of the repository.
        target_path: Where to clone the repository.
        branch: Branch to clone.
        depth: Shallow clone depth (None for full clone).

    Returns:
        True if clone was successful.
    """
    step(f"Cloning {git_url} (branch: {branch})")

    cmd = ["git", "clone", "--branch", branch]
    if depth is not None:
        cmd.extend(["--depth", str(depth)])
    cmd.extend([git_url, str(target_path)])

    result = run_cmd(cmd, timeout=300)
    if result.success:
        success(f"Cloned to {target_path}")
        return True
    else:
        error(f"Git clone failed: {result.stderr.strip()[:200]}")
        return False


def fetch_latest(repo_path: Path, branch: str = "main") -> bool:
    """Fetch the latest changes from remote.

    Args:
        repo_path: Path to the local repository.
        branch: Branch to fetch.

    Returns:
        True if fetch was successful.
    """
    step(f"Fetching latest changes for branch: {branch}")

    # First, fetch
    result = run_cmd(
        ["git", "fetch", "origin", branch],
        cwd=repo_path,
        timeout=120,
    )
    if not result.success:
        error(f"Git fetch failed: {result.stderr.strip()[:200]}")
        return False

    # Then reset to remote branch
    result = run_cmd(
        ["git", "reset", "--hard", f"origin/{branch}"],
        cwd=repo_path,
        timeout=30,
    )
    if result.success:
        success("Updated to latest commit")
        return True
    else:
        error(f"Git reset failed: {result.stderr.strip()[:200]}")
        return False


def checkout_branch(repo_path: Path, branch: str) -> bool:
    """Checkout a specific branch.

    Args:
        repo_path: Path to the local repository.
        branch: Branch name to checkout.

    Returns:
        True if checkout was successful.
    """
    result = run_cmd(
        ["git", "checkout", branch],
        cwd=repo_path,
        timeout=30,
    )
    if result.success:
        success(f"Checked out branch: {branch}")
        return True
    else:
        error(f"Checkout failed: {result.stderr.strip()[:200]}")
        return False


def get_current_commit(repo_path: Path) -> Optional[str]:
    """Get the current commit hash (short).

    Args:
        repo_path: Path to the local repository.

    Returns:
        Short commit hash, or None if not a git repo.
    """
    result = run_cmd(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_path,
    )
    if result.success:
        return result.stdout.strip()
    return None


def get_current_branch(repo_path: Path) -> Optional[str]:
    """Get the current branch name.

    Args:
        repo_path: Path to the local repository.

    Returns:
        Branch name, or None.
    """
    result = run_cmd(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_path,
    )
    if result.success:
        return result.stdout.strip()
    return None


def validate_git_url(url: str) -> bool:
    """Validate that a git URL looks reasonable.

    Args:
        url: The URL to validate.

    Returns:
        True if the URL appears to be a valid git URL.
    """
    if not url:
        return False
    # Accept HTTPS, SSH, and git:// URLs
    valid_prefixes = (
        "https://",
        "http://",
        "git@",
        "git://",
        "ssh://",
    )
    return any(url.startswith(prefix) for prefix in valid_prefixes)


def test_git_access(git_url: str) -> bool:
    """Test if the git URL is accessible (without cloning).

    Args:
        git_url: The repository URL.

    Returns:
        True if the repository is accessible.
    """
    result = run_cmd(
        ["git", "ls-remote", "--exit-code", git_url],
        timeout=30,
    )
    return result.success
