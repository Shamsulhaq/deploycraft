"""Redis service management.

Handles installation, configuration, and status checking.
"""

from rich.console import Console

from deploycraft.os_detect import PackageManager
from deploycraft.utils import error, run_cmd, step, success

console = Console()


def install_redis(pkg_manager: PackageManager) -> bool:
    """Install and start Redis server.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        True if installation was successful.
    """
    step("Installing Redis...")

    # Update repos
    run_cmd(pkg_manager.update_cmd())

    # Install
    result = run_cmd(pkg_manager.install_cmd("redis"))
    if not result.success:
        error(f"Redis installation failed: {result.stderr.strip()[:200]}")
        return False

    # Determine service name (redis-server on Debian, redis on RHEL)
    service_name = get_service_name(pkg_manager)

    # Enable and start
    result = run_cmd(pkg_manager.enable_service_cmd(service_name))
    if not result.success:
        error(f"Failed to start Redis: {result.stderr.strip()[:200]}")
        return False

    success("Redis installed and running")
    return True


def is_redis_running(pkg_manager: PackageManager) -> bool:
    """Check if Redis is running.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        True if Redis service is active.
    """
    service_name = get_service_name(pkg_manager)
    result = run_cmd(["sudo", "systemctl", "is-active", service_name])
    return result.success and result.stdout.strip() == "active"


def get_service_name(pkg_manager: PackageManager) -> str:
    """Get the Redis service name for the current OS.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        Service name string.
    """
    if pkg_manager.os_info.is_debian_based:
        return "redis-server"
    return "redis"


def get_redis_url(host: str = "localhost", port: int = 6379, db: int = 0) -> str:
    """Build a Redis connection URL.

    Args:
        host: Redis host.
        port: Redis port.
        db: Redis database number.

    Returns:
        Redis URL string.
    """
    return f"redis://{host}:{port}/{db}"


def test_redis_connection() -> bool:
    """Test if Redis is responding to commands.

    Returns:
        True if Redis responds to PING with PONG.
    """
    result = run_cmd(["redis-cli", "ping"])
    return result.success and "PONG" in result.stdout
