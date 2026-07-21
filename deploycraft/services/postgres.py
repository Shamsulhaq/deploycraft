"""PostgreSQL service management.

Handles installation, database creation, user creation, and configuration.
"""

from typing import Optional

from rich.console import Console

from deploycraft.os_detect import PackageManager
from deploycraft.utils import (
    error,
    generate_db_name,
    generate_db_user,
    generate_password,
    run_cmd,
    step,
    success,
    warning,
)

console = Console()


def install_postgresql(pkg_manager: PackageManager) -> bool:
    """Install PostgreSQL server.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        True if installation was successful.
    """
    step("Installing PostgreSQL...")

    # Update package repos
    result = run_cmd(pkg_manager.update_cmd())
    if not result.success:
        warning("Package update failed, attempting install anyway...")

    # Install
    result = run_cmd(pkg_manager.install_cmd("postgresql"))
    if not result.success:
        error(f"PostgreSQL installation failed: {result.stderr.strip()[:200]}")
        return False

    # For RHEL-based: need to init db and enable service
    if pkg_manager.os_info.is_rhel_based:
        # Initialize database cluster
        init_result = run_cmd(["sudo", "postgresql-setup", "--initdb"])
        if not init_result.success:
            # Try alternative init method
            run_cmd(["sudo", "/usr/bin/postgresql-setup", "initdb"])

    # Enable and start service
    service_name = "postgresql"
    result = run_cmd(pkg_manager.enable_service_cmd(service_name))
    if not result.success:
        error(f"Failed to start PostgreSQL service: {result.stderr.strip()[:200]}")
        return False

    success("PostgreSQL installed and running")
    return True


def is_postgresql_running() -> bool:
    """Check if PostgreSQL is running.

    Returns:
        True if PostgreSQL service is active.
    """
    result = run_cmd(["sudo", "systemctl", "is-active", "postgresql"])
    return result.success and result.stdout.strip() == "active"


def create_database(
    project_name: str,
    db_name: Optional[str] = None,
    db_user: Optional[str] = None,
    db_password: Optional[str] = None,
) -> dict[str, str]:
    """Create a PostgreSQL database and user for a project.

    Args:
        project_name: Name of the project (used to generate defaults).
        db_name: Custom database name (generated from project_name if None).
        db_user: Custom username (generated from project_name if None).
        db_password: Custom password (generated if None).

    Returns:
        Dict with keys: db_name, db_user, db_password, db_host, db_port.
    """
    db_name = db_name or generate_db_name(project_name)
    db_user = db_user or generate_db_user(project_name)
    db_password = db_password or generate_password(20)

    step(f"Creating database: {db_name}")

    # Check if user already exists
    user_exists = _pg_user_exists(db_user)
    if not user_exists:
        # Create user
        result = run_cmd([
            "sudo", "-u", "postgres", "psql", "-c",
            f"CREATE USER {db_user} WITH PASSWORD '{db_password}';"
        ])
        if not result.success:
            error(f"Failed to create PostgreSQL user: {result.stderr.strip()[:200]}")
            return {}
        success(f"Created PostgreSQL user: {db_user}")
    else:
        # Update password for existing user
        run_cmd([
            "sudo", "-u", "postgres", "psql", "-c",
            f"ALTER USER {db_user} WITH PASSWORD '{db_password}';"
        ])
        warning(f"User {db_user} already exists, updated password")

    # Check if database already exists
    db_exists = _pg_database_exists(db_name)
    if not db_exists:
        # Create database
        result = run_cmd([
            "sudo", "-u", "postgres", "psql", "-c",
            f"CREATE DATABASE {db_name} OWNER {db_user};"
        ])
        if not result.success:
            error(f"Failed to create database: {result.stderr.strip()[:200]}")
            return {}
        success(f"Created database: {db_name}")
    else:
        warning(f"Database {db_name} already exists")

    # Grant privileges
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c",
        f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"
    ])

    return {
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "db_host": "localhost",
        "db_port": "5432",
    }


def drop_database(db_name: str, db_user: str) -> bool:
    """Drop a PostgreSQL database and user.

    Args:
        db_name: Database name to drop.
        db_user: User to drop.

    Returns:
        True if successful.
    """
    step(f"Dropping database: {db_name}")

    # Drop database
    result = run_cmd([
        "sudo", "-u", "postgres", "psql", "-c",
        f"DROP DATABASE IF EXISTS {db_name};"
    ])
    if not result.success:
        error(f"Failed to drop database: {result.stderr.strip()[:200]}")
        return False

    # Drop user
    run_cmd([
        "sudo", "-u", "postgres", "psql", "-c",
        f"DROP USER IF EXISTS {db_user};"
    ])

    success(f"Dropped database {db_name} and user {db_user}")
    return True


def get_connection_url(db_info: dict[str, str]) -> str:
    """Build a PostgreSQL connection URL from db info dict.

    Args:
        db_info: Dict with db_name, db_user, db_password, db_host, db_port.

    Returns:
        PostgreSQL connection URL string.
    """
    return (
        f"postgresql://{db_info['db_user']}:{db_info['db_password']}"
        f"@{db_info['db_host']}:{db_info['db_port']}/{db_info['db_name']}"
    )


def _pg_user_exists(username: str) -> bool:
    """Check if a PostgreSQL user exists."""
    result = run_cmd([
        "sudo", "-u", "postgres", "psql", "-tAc",
        f"SELECT 1 FROM pg_roles WHERE rolname='{username}';"
    ])
    return result.success and result.stdout.strip() == "1"


def _pg_database_exists(db_name: str) -> bool:
    """Check if a PostgreSQL database exists."""
    result = run_cmd([
        "sudo", "-u", "postgres", "psql", "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname='{db_name}';"
    ])
    return result.success and result.stdout.strip() == "1"
