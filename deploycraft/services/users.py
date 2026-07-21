"""System user management for DeployCraft.

Creates and manages Ubuntu/Linux system users with optional sudo (admin) access.
"""

import string
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from deploycraft.utils import error, run_cmd, step, success, warning

console = Console()


def user_exists(username: str) -> bool:
    """Check if a system user already exists.

    Args:
        username: The username to check.

    Returns:
        True if the user exists.
    """
    result = run_cmd(["id", username])
    return result.success


def create_user(
    username: str,
    password: str,
    full_name: str = "",
    is_admin: bool = False,
    create_home: bool = True,
    shell: str = "/bin/bash",
) -> bool:
    """Create a new Ubuntu system user.

    Args:
        username: Login username (alphanumeric, hyphens, underscores).
        password: Plain-text password (will be hashed before setting).
        full_name: Optional GECOS full name field.
        is_admin: If True, add user to sudo group.
        create_home: If True, create a home directory.
        shell: Login shell (default: /bin/bash).

    Returns:
        True if user was created successfully.
    """
    # Validate username
    if not _is_valid_username(username):
        error(f"Invalid username: '{username}'. Use only letters, numbers, hyphens, underscores.")
        return False

    # Check if already exists
    if user_exists(username):
        warning(f"User '{username}' already exists.")
        return True

    step(f"Creating user: {username}")

    # Build useradd command
    cmd = ["sudo", "useradd"]
    if create_home:
        cmd.append("--create-home")
    cmd.extend(["--shell", shell])
    if full_name:
        cmd.extend(["--comment", full_name])
    cmd.append(username)

    result = run_cmd(cmd)
    if not result.success:
        error(f"Failed to create user: {result.stderr.strip()[:200]}")
        return False

    # Set password
    if not set_user_password(username, password):
        error(f"Failed to set password for {username}")
        # Clean up the partially created user
        run_cmd(["sudo", "userdel", "--remove", username])
        return False

    # Grant sudo if admin
    if is_admin:
        if not grant_sudo(username):
            error(f"Failed to grant sudo to {username}")
            return False

    success(f"User '{username}' created successfully")
    return True


def set_user_password(username: str, password: str) -> bool:
    """Set a user's password.

    Args:
        username: The username.
        password: Plain-text password.

    Returns:
        True if password was set successfully.
    """
    # Use chpasswd which reads "user:password" from stdin
    run_cmd(
        ["sudo", "chpasswd"],
        env={"CHPASSWD_INPUT": f"{username}:{password}"},
    )

    # chpasswd doesn't support env input directly, use echo pipe approach
    # but avoid shell=True for security — use a subprocess with input
    import subprocess
    try:
        proc = subprocess.run(
            ["sudo", "chpasswd"],
            input=f"{username}:{password}",
            text=True,
            capture_output=True,
        )
        return proc.returncode == 0
    except Exception as e:
        error(f"Failed to set password: {e}")
        return False


def grant_sudo(username: str) -> bool:
    """Grant sudo (administrator) privileges to a user.

    Adds the user to the 'sudo' group (Debian/Ubuntu) and also the
    'wheel' group (RHEL/CentOS) for compatibility.

    Args:
        username: The username to grant sudo to.

    Returns:
        True if sudo was granted successfully.
    """
    step(f"Granting sudo privileges to: {username}")

    # Add to sudo group (Ubuntu/Debian)
    result = run_cmd(["sudo", "usermod", "-aG", "sudo", username])

    # Also try wheel group (RHEL/CentOS/Amazon Linux) — don't fail if it doesn't exist
    run_cmd(["sudo", "usermod", "-aG", "wheel", username])

    if result.success:
        success(f"User '{username}' added to sudo group")
        return True
    else:
        error(f"Failed to add {username} to sudo group: {result.stderr.strip()[:200]}")
        return False


def revoke_sudo(username: str) -> bool:
    """Remove sudo privileges from a user.

    Args:
        username: The username.

    Returns:
        True if sudo was revoked.
    """
    result = run_cmd(["sudo", "gpasswd", "-d", username, "sudo"])
    run_cmd(["sudo", "gpasswd", "-d", username, "wheel"])
    return result.success


def delete_user(username: str, remove_home: bool = False) -> bool:
    """Delete a system user.

    Args:
        username: The username to delete.
        remove_home: If True, also delete the user's home directory.

    Returns:
        True if user was deleted.
    """
    if not user_exists(username):
        warning(f"User '{username}' does not exist.")
        return True

    cmd = ["sudo", "userdel"]
    if remove_home:
        cmd.append("--remove")
    cmd.append(username)

    result = run_cmd(cmd)
    if result.success:
        success(f"User '{username}' deleted")
    else:
        error(f"Failed to delete user: {result.stderr.strip()[:200]}")
    return result.success


def list_sudo_users() -> list[str]:
    """List all users with sudo privileges.

    Returns:
        List of usernames in the sudo/wheel group.
    """
    users = set()

    # Check sudo group
    result = run_cmd(["getent", "group", "sudo"])
    if result.success and ":" in result.stdout:
        members = result.stdout.strip().split(":")[-1]
        if members:
            users.update(members.split(","))

    # Check wheel group
    result = run_cmd(["getent", "group", "wheel"])
    if result.success and ":" in result.stdout:
        members = result.stdout.strip().split(":")[-1]
        if members:
            users.update(members.split(","))

    return sorted(u for u in users if u)


def is_admin(username: str) -> bool:
    """Check if a user has sudo privileges.

    Args:
        username: The username to check.

    Returns:
        True if the user is in the sudo or wheel group.
    """
    return username in list_sudo_users()


def get_user_info(username: str) -> Optional[dict]:
    """Get basic information about a system user.

    Args:
        username: The username.

    Returns:
        Dict with uid, gid, home, shell, groups — or None if user doesn't exist.
    """
    result = run_cmd(["id", username])
    if not result.success:
        return None

    # Parse id output: uid=1001(username) gid=1001(username) groups=...
    info = {"username": username}
    result.stdout.strip()

    # Extract home from /etc/passwd
    passwd_result = run_cmd(["getent", "passwd", username])
    if passwd_result.success:
        fields = passwd_result.stdout.strip().split(":")
        if len(fields) >= 7:
            info["home"] = fields[5]
            info["shell"] = fields[6]
            info["full_name"] = fields[4]

    info["is_admin"] = is_admin(username)
    return info


def run_user_create_wizard() -> Optional[dict]:
    """Interactive wizard for creating a system user.

    Returns:
        Dict with created user's details, or None if cancelled/failed.
    """
    console.print("\n[bold cyan]Create System User[/bold cyan]\n")

    # Username
    while True:
        username = Prompt.ask("Username").strip().lower()
        if not username:
            return None
        if not _is_valid_username(username):
            error("Username must start with a letter and contain only letters, numbers, hyphens, or underscores.")
            continue
        if user_exists(username):
            warning(f"User '{username}' already exists.")
            if not Confirm.ask("Continue with a different name?", default=True):
                return None
            continue
        break

    # Full name (optional)
    full_name = Prompt.ask("Full name (optional)", default="")

    # Password
    while True:
        password = Prompt.ask("Password", password=True)
        if len(password) < 8:
            error("Password must be at least 8 characters.")
            continue
        confirm = Prompt.ask("Confirm password", password=True)
        if password != confirm:
            error("Passwords do not match.")
            continue
        break

    # Admin role
    is_admin_user = Confirm.ask(
        f"Grant administrator (sudo) privileges to '{username}'?",
        default=False,
    )

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Username: [cyan]{username}[/cyan]")
    if full_name:
        console.print(f"  Full name: {full_name}")
    console.print(f"  Role: {'[red]Administrator (sudo)[/red]' if is_admin_user else 'Standard user'}")
    console.print(f"  Home: /home/{username}")
    console.print("  Shell: /bin/bash")

    if not Confirm.ask("\nCreate this user?", default=True):
        return None

    # Create the user
    created = create_user(
        username=username,
        password=password,
        full_name=full_name,
        is_admin=is_admin_user,
    )

    if not created:
        return None

    result = {
        "username": username,
        "password": password,
        "full_name": full_name,
        "is_admin": is_admin_user,
        "home": f"/home/{username}",
    }

    # Show result panel
    console.print("")
    console.print(Panel(
        f"[bold green]User created successfully![/bold green]\n\n"
        f"Username: [cyan]{username}[/cyan]\n"
        f"Password: [yellow]{password}[/yellow]\n"
        f"Role: {'Administrator' if is_admin_user else 'Standard user'}\n"
        f"Home: /home/{username}\n\n"
        f"[dim]⚠ Save these credentials! The password won't be shown again.[/dim]",
        title="✅ New User",
    ))

    # Ask if they want to create another
    while Confirm.ask("\nCreate another user?", default=False):
        additional = run_user_create_wizard()
        if not additional:
            break

    return result


def _is_valid_username(username: str) -> bool:
    """Validate a Linux username.

    Rules: starts with letter or underscore, contains only letters,
    digits, hyphens, underscores, max 32 chars.

    Args:
        username: Username to validate.

    Returns:
        True if valid.
    """
    if not username or len(username) > 32:
        return False
    if not (username[0].isalpha() or username[0] == "_"):
        return False
    allowed = set(string.ascii_lowercase + string.digits + "-_")
    return all(c in allowed for c in username)
