"""DeployCraft CLI - Main entry point."""

from typing import Optional

import typer
from rich.console import Console

from deploycraft import __version__

app = typer.Typer(
    name="deploycraft",
    help="Interactive CLI tool for automated web application deployment.",
    no_args_is_help=False,
    invoke_without_command=True,
)
monitor_app = typer.Typer(help="System monitoring commands.")
ssh_key_app = typer.Typer(help="SSH key management.")
user_app = typer.Typer(help="System user management.")

app.add_typer(monitor_app, name="monitor")
app.add_typer(ssh_key_app, name="ssh-key")
app.add_typer(user_app, name="user")

console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"DeployCraft v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit.", callback=version_callback
    ),
) -> None:
    """DeployCraft - Deploy web applications with ease."""
    # If invoked with no subcommand, launch the interactive shell
    if ctx.invoked_subcommand is None:
        from deploycraft.shell import run_shell
        run_shell()


@app.command()
def init() -> None:
    """First-time setup: configure admin email, SMTP, and global preferences."""
    from deploycraft.config import run_init_wizard

    run_init_wizard()


@app.command()
def deploy() -> None:
    """Interactive deployment wizard - deploy a new project."""
    from deploycraft.deploy.deployer import run_deploy_wizard

    run_deploy_wizard()


@app.command()
def redeploy(
    project: str = typer.Argument(..., help="Project name to redeploy."),
) -> None:
    """Pull latest code and redeploy a project."""
    from deploycraft.deploy.deployer import run_redeploy

    run_redeploy(project)


@app.command()
def rollback(
    project: str = typer.Argument(..., help="Project name to rollback."),
) -> None:
    """Revert a project to its previous release version."""
    from deploycraft.deploy.rollback import run_rollback

    run_rollback(project)


@app.command()
def stable(
    project: str = typer.Argument(..., help="Project name to mark as stable."),
) -> None:
    """Mark the current release as stable (rollback floor)."""
    from deploycraft.deploy.rollback import mark_stable

    mark_stable(project)


@app.command()
def status() -> None:
    """Show dashboard: all projects, health, and system metrics."""
    from deploycraft.deploy.health_check import show_status

    show_status()


@app.command(name="list")
def list_projects() -> None:
    """List all managed projects with their status."""
    from deploycraft.config import list_all_projects

    list_all_projects()


@app.command()
def remove(
    project: str = typer.Argument(..., help="Project name to remove."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt."),
) -> None:
    """Remove a managed project (with confirmation)."""
    from deploycraft.deploy.deployer import remove_project

    remove_project(project, force=force)


@app.command()
def logs(
    project: str = typer.Argument(..., help="Project name to view logs for."),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of log lines to show."),
) -> None:
    """Tail logs for a project's services."""
    from deploycraft.deploy.deployer import show_logs

    show_logs(project, lines=lines)


# --- Monitor subcommands ---


@monitor_app.command("start")
def monitor_start() -> None:
    """Enable system monitoring (installs systemd timer)."""
    from deploycraft.monitor.scheduler import start_monitoring

    start_monitoring()


@monitor_app.command("stop")
def monitor_stop() -> None:
    """Disable system monitoring (removes systemd timer)."""
    from deploycraft.monitor.scheduler import stop_monitoring

    stop_monitoring()


@monitor_app.command("status")
def monitor_status() -> None:
    """Show monitoring status and recent alerts."""
    from deploycraft.monitor.scheduler import show_monitor_status

    show_monitor_status()


# --- SSH Key subcommands ---


@ssh_key_app.callback(invoke_without_command=True)
def ssh_key_default(ctx: typer.Context) -> None:
    """SSH key management — generate, display, and test deploy keys."""
    if ctx.invoked_subcommand is None:
        # Default: run the full wizard
        from deploycraft.services.ssh import run_ssh_key_wizard
        run_ssh_key_wizard()


@ssh_key_app.command("show")
def ssh_key_show() -> None:
    """Display the current SSH public key."""
    from deploycraft.services.ssh import display_public_key_instructions, ensure_keypair_exists

    public_key = ensure_keypair_exists()
    if public_key:
        display_public_key_instructions(public_key)
    else:
        console.print("[red]No SSH key found. Run 'deploycraft ssh-key generate' to create one.[/red]")


@ssh_key_app.command("generate")
def ssh_key_generate(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing key."),
) -> None:
    """Generate a new SSH keypair for this server."""
    from deploycraft.services.ssh import (
        display_public_key_instructions,
        generate_keypair,
        get_public_key,
        key_exists,
    )

    if key_exists() and not force:
        console.print("[yellow]SSH key already exists.[/yellow] Use --force to regenerate.")
        console.print("Run [bold]deploycraft ssh-key show[/bold] to display the existing key.")
        raise typer.Exit()

    pub_path = generate_keypair(force=force)
    if pub_path:
        public_key = get_public_key()
        if public_key:
            display_public_key_instructions(public_key)


@ssh_key_app.command("test")
def ssh_key_test(
    host: str = typer.Argument(
        ...,
        help="Git URL or host to test (e.g., https://github.com/user/repo.git or github.com).",
    ),
) -> None:
    """Test SSH connectivity to a Git provider."""
    from deploycraft.services.ssh import test_ssh_connection

    test_ssh_connection(host)


# --- User subcommands ---


@user_app.callback(invoke_without_command=True)
def user_default(ctx: typer.Context) -> None:
    """System user management — create and manage Linux users."""
    if ctx.invoked_subcommand is None:
        # Default: run the create wizard
        from deploycraft.services.users import run_user_create_wizard
        run_user_create_wizard()


@user_app.command("create")
def user_create() -> None:
    """Interactively create a new system user."""
    from deploycraft.services.users import run_user_create_wizard

    run_user_create_wizard()


@user_app.command("delete")
def user_delete(
    username: str = typer.Argument(..., help="Username to delete."),
    remove_home: bool = typer.Option(
        False, "--remove-home", help="Also delete the user's home directory."
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
) -> None:
    """Delete a system user."""
    from deploycraft.services.users import delete_user, user_exists

    if not user_exists(username):
        console.print(f"[yellow]User '{username}' does not exist.[/yellow]")
        raise typer.Exit()

    if not force:
        from rich.prompt import Confirm
        if not Confirm.ask(
            f"[red]Delete user '{username}'?[/red]"
            + (" (home directory will also be removed)" if remove_home else ""),
            default=False,
        ):
            raise typer.Exit()

    delete_user(username, remove_home=remove_home)


@user_app.command("sudo")
def user_sudo(
    username: str = typer.Argument(..., help="Username."),
    revoke: bool = typer.Option(False, "--revoke", help="Revoke sudo instead of granting."),
) -> None:
    """Grant or revoke sudo (admin) privileges for a user."""
    from deploycraft.services.users import grant_sudo, revoke_sudo, user_exists

    if not user_exists(username):
        console.print(f"[red]User '{username}' does not exist.[/red]")
        raise typer.Exit(1)

    if revoke:
        revoke_sudo(username)
        console.print(f"[green]Sudo revoked from '{username}'.[/green]")
    else:
        grant_sudo(username)


@user_app.command("list")
def user_list() -> None:
    """List all users with sudo (admin) privileges."""
    from rich.table import Table

    from deploycraft.services.users import list_sudo_users

    sudo_users = list_sudo_users()
    if not sudo_users:
        console.print("[yellow]No sudo users found.[/yellow]")
        return

    table = Table(title="Administrator Users (sudo)")
    table.add_column("Username", style="cyan")
    table.add_column("Sudo Group", style="green")

    for user in sudo_users:
        table.add_row(user, "✓")

    console.print(table)


if __name__ == "__main__":
    app()
