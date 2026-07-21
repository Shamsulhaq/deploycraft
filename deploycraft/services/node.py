"""Node.js installation and management.

Installs Node.js via NodeSource repository for the target platform.
"""

from rich.console import Console

from deploycraft.os_detect import PackageManager
from deploycraft.utils import error, run_cmd, step, success

console = Console()

# NodeSource setup script URLs
NODESOURCE_SETUP_URL = "https://deb.nodesource.com/setup_lts.x"
NODESOURCE_RPM_URL = "https://rpm.nodesource.com/setup_lts.x"


def install_nodejs(pkg_manager: PackageManager, version: str = "lts") -> bool:
    """Install Node.js via NodeSource.

    Args:
        pkg_manager: Package manager instance.
        version: Node.js version to install ("lts" or specific like "20").

    Returns:
        True if installation was successful.
    """
    # Check if already installed
    result = run_cmd(["node", "--version"])
    if result.success:
        current_version = result.stdout.strip()
        success(f"Node.js already installed: {current_version}")
        return True

    step("Installing Node.js (LTS)...")

    if pkg_manager.os_info.is_debian_based:
        return _install_nodejs_debian(pkg_manager, version)
    else:
        return _install_nodejs_rhel(pkg_manager, version)


def _install_nodejs_debian(pkg_manager: PackageManager, version: str) -> bool:
    """Install Node.js on Debian/Ubuntu via NodeSource."""
    # Install prerequisites
    run_cmd(pkg_manager.install_cmd("curl"))

    # Download and run NodeSource setup script
    result = run_cmd([
        "bash", "-c",
        f"curl -fsSL {NODESOURCE_SETUP_URL} | sudo -E bash -"
    ], timeout=60)

    if not result.success:
        error(f"NodeSource setup failed: {result.stderr.strip()[:200]}")
        return False

    # Install Node.js
    result = run_cmd(["sudo", "apt-get", "install", "-y", "nodejs"])
    if not result.success:
        error(f"Node.js installation failed: {result.stderr.strip()[:200]}")
        return False

    # Verify
    result = run_cmd(["node", "--version"])
    if result.success:
        success(f"Node.js installed: {result.stdout.strip()}")
        return True

    error("Node.js installation verification failed")
    return False


def _install_nodejs_rhel(pkg_manager: PackageManager, version: str) -> bool:
    """Install Node.js on RHEL/CentOS/Fedora via NodeSource."""
    # Install prerequisites
    run_cmd(pkg_manager.install_cmd("curl"))

    # Download and run NodeSource setup script
    result = run_cmd([
        "bash", "-c",
        f"curl -fsSL {NODESOURCE_RPM_URL} | sudo bash -"
    ], timeout=60)

    if not result.success:
        error(f"NodeSource setup failed: {result.stderr.strip()[:200]}")
        return False

    # Install Node.js
    cmd = pkg_manager.install_cmd("nodejs")
    # Replace canonical name with actual package name for NodeSource
    cmd = ["sudo", pkg_manager._get_pkg_cmd(), "install", "-y", "nodejs"]
    result = run_cmd(cmd)

    if not result.success:
        error(f"Node.js installation failed: {result.stderr.strip()[:200]}")
        return False

    # Verify
    result = run_cmd(["node", "--version"])
    if result.success:
        success(f"Node.js installed: {result.stdout.strip()}")
        return True

    error("Node.js installation verification failed")
    return False


def is_nodejs_installed() -> bool:
    """Check if Node.js is installed.

    Returns:
        True if node command is available.
    """
    result = run_cmd(["node", "--version"])
    return result.success


def is_npm_installed() -> bool:
    """Check if npm is installed.

    Returns:
        True if npm command is available.
    """
    result = run_cmd(["npm", "--version"])
    return result.success


def get_node_version() -> str:
    """Get the installed Node.js version.

    Returns:
        Version string (e.g., "v20.10.0") or "not installed".
    """
    result = run_cmd(["node", "--version"])
    if result.success:
        return result.stdout.strip()
    return "not installed"


def get_npm_version() -> str:
    """Get the installed npm version.

    Returns:
        Version string or "not installed".
    """
    result = run_cmd(["npm", "--version"])
    if result.success:
        return result.stdout.strip()
    return "not installed"
