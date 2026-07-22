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


def _resolve_project(project: str = "") -> str:
    """Resolve project name from argument or current directory.

    If project name is given, use it. Otherwise, detect from current directory
    by looking for a DeployCraft project config that matches the current path,
    or use the current directory name.

    Args:
        project: Explicit project name (empty = auto-detect from cwd).

    Returns:
        Project name string.
    """
    if project:
        return project

    import os
    from pathlib import Path

    cwd = Path(os.getcwd())

    # Check if current dir is a managed project (by matching base_path)
    from deploycraft.config import get_all_projects

    for p in get_all_projects():
        if Path(p.base_path).resolve() == cwd.resolve():
            return p.name

    # Fallback: use current directory name
    return cwd.name


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
    project: str = typer.Argument("", help="Project name to redeploy."),
) -> None:
    """Pull latest code and redeploy a project."""
    project = _resolve_project(project)
    from deploycraft.deploy.deployer import run_redeploy

    run_redeploy(project)


@app.command()
def rollback(
    project: str = typer.Argument("", help="Project name to rollback."),
) -> None:
    """Revert a project to its previous release version."""
    project = _resolve_project(project)
    from deploycraft.deploy.rollback import run_rollback

    run_rollback(project)


@app.command()
def stable(
    project: str = typer.Argument("", help="Project name to mark as stable."),
) -> None:
    """Mark the current release as stable (rollback floor)."""
    project = _resolve_project(project)
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
    project: str = typer.Argument("", help="Project name to remove."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt."),
) -> None:
    """Remove a managed project (with confirmation)."""
    project = _resolve_project(project)
    from deploycraft.deploy.deployer import remove_project

    remove_project(project, force=force)


@app.command()
def logs(
    project: str = typer.Argument("", help="Project name to view logs for."),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of log lines to show."),
) -> None:
    """Tail logs for a project's services."""
    project = _resolve_project(project)
    from deploycraft.deploy.deployer import show_logs

    show_logs(project, lines=lines)


# --- Standalone step commands ---


@app.command()
def clone(
    git_url: str = typer.Argument(..., help="Git repository URL (SSH or HTTPS)."),
    path: str = typer.Option("", "--path", "-p", help="Destination path (default: ./<repo_name>)."),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch to clone."),
) -> None:
    """Clone a git repository to a specified path."""
    from pathlib import Path

    from deploycraft.services import git

    if not git.validate_git_url(git_url):
        console.print("[red]Invalid git URL format.[/red]")
        raise typer.Exit(1)

    # Derive path from URL if not given
    if not path:
        # git@github.com:user/repo.git → repo
        repo_name = git_url.rstrip("/").split("/")[-1].replace(".git", "")
        path = repo_name

    target = Path(path)
    if target.exists() and any(target.iterdir()):
        console.print(f"[yellow]Directory '{path}' already exists and is not empty.[/yellow]")
        raise typer.Exit(1)

    if not git.clone_repo(git_url, target, branch=branch):
        raise typer.Exit(1)


@app.command()
def inspect(
    path: str = typer.Argument(".", help="Path to the project directory to inspect."),
    stack: str = typer.Option(
        "", "--stack", "-s",
        help="Stack type (django/fastapi/nextjs/react_vite/react/html). Auto-detects if not given.",
    ),
) -> None:
    """Detect what services a project needs (PostgreSQL, Redis, Celery, etc.)."""
    from pathlib import Path

    from rich.table import Table

    from deploycraft.config import ProjectConfig
    from deploycraft.os_detect import Distro, OSInfo, PackageManager, PackageManagerType
    from deploycraft.stacks import StackType, get_stack_class
    from deploycraft.stacks.base import StackContext

    project_path = Path(path).resolve()
    if not project_path.exists():
        console.print(f"[red]Path not found: {path}[/red]")
        raise typer.Exit(1)

    # Auto-detect stack if not provided
    if not stack:
        stack = _detect_stack_type(project_path)
        if not stack:
            console.print("[yellow]Could not auto-detect stack. Use --stack flag.[/yellow]")
            raise typer.Exit(1)
        console.print(f"  Detected stack: [cyan]{stack}[/cyan]")

    stack_type = StackType(stack)
    stack_class = get_stack_class(stack_type)
    if not stack_class:
        console.print(f"[red]Unknown stack: {stack}[/red]")
        raise typer.Exit(1)

    # Create minimal context for detection
    os_info = OSInfo(Distro.UBUNTU, "22.04", "", "x86_64", PackageManagerType.APT, True)
    project_config = ProjectConfig(name="inspect", stack=stack, base_path=str(project_path), git_url="")
    context = StackContext(
        project_config=project_config,
        os_info=os_info,
        package_manager=PackageManager(os_info),
        project_path=project_path,
        shared_path=project_path / "shared",
        env_file_path=project_path / ".env",
    )

    stack_instance = stack_class(context)
    detected = stack_instance.detect_services(project_path)

    # Display results
    services = detected.summary()
    if services:
        table = Table(title=f"Detected Services for '{project_path.name}'")
        table.add_column("Service", style="cyan")
        table.add_column("Required", style="green")

        for svc in services:
            table.add_row(svc, "✓")

        console.print(table)
    else:
        console.print("[dim]No additional services detected.[/dim]")


@app.command(name="install-services")
def install_services(
    project: str = typer.Argument("", help="Project name."),
) -> None:
    """Install system services (PostgreSQL, Redis, Node.js, etc.) for a project."""
    project = _resolve_project(project)
    from pathlib import Path

    from deploycraft.config import load_project_config, save_project_config
    from deploycraft.deploy.env_manager import get_env_file_path
    from deploycraft.os_detect import ensure_supported_os
    from deploycraft.services import node, pm2, postgres, redis
    from deploycraft.stacks import StackType, get_stack_class
    from deploycraft.stacks.base import StackContext

    project_config = load_project_config(project)
    if not project_config:
        console.print(f"[red]Project '{project}' not found. Run 'deploycraft deploy' first.[/red]")
        raise typer.Exit(1)

    os_info, pkg_manager = ensure_supported_os()
    project_path = Path(project_config.base_path)

    # Get stack and detect services
    stack_type = StackType(project_config.stack)
    stack_class = get_stack_class(stack_type)
    if not stack_class:
        console.print(f"[red]Unknown stack: {project_config.stack}[/red]")
        raise typer.Exit(1)

    context = StackContext(
        project_config=project_config,
        os_info=os_info,
        package_manager=pkg_manager,
        project_path=project_path,
        shared_path=project_path / "shared",
        env_file_path=get_env_file_path(project),
        domain=project_config.domain,
    )
    stack_instance = stack_class(context)
    detected = stack_instance.detect_services(project_path)

    # Install each detected service
    if detected.needs_postgresql:
        if not postgres.is_postgresql_running():
            postgres.install_postgresql(pkg_manager)
        db_info = postgres.create_database(project)
        if db_info:
            project_config.db_name = db_info["db_name"]
            project_config.db_user = db_info["db_user"]
            project_config.db_password = db_info["db_password"]
            if "postgresql" not in project_config.services:
                project_config.services.append("postgresql")

    if detected.needs_redis:
        if not redis.is_redis_running(pkg_manager):
            redis.install_redis(pkg_manager)
        if "redis" not in project_config.services:
            project_config.services.append("redis")

    if detected.needs_nodejs:
        node.install_nodejs(pkg_manager)

    if detected.needs_pm2:
        pm2.install_pm2()
        if "pm2" not in project_config.services:
            project_config.services.append("pm2")

    save_project_config(project_config)
    console.print("[green]✓ Services installed.[/green]")


@app.command()
def configure(
    project: str = typer.Argument("", help="Project name."),
) -> None:
    """Configure Nginx, systemd services, and .env for a project."""
    project = _resolve_project(project)
    from pathlib import Path

    from deploycraft.config import load_project_config, save_project_config
    from deploycraft.deploy.env_manager import (
        collect_env_vars_interactive,
        create_env_file,
        get_env_file_path,
        symlink_env_to_project,
    )
    from deploycraft.os_detect import ensure_supported_os
    from deploycraft.services import nginx, redis, systemd
    from deploycraft.stacks import StackType, get_stack_class
    from deploycraft.stacks.base import StackContext

    project_config = load_project_config(project)
    if not project_config:
        console.print(f"[red]Project '{project}' not found.[/red]")
        raise typer.Exit(1)

    os_info, pkg_manager = ensure_supported_os()
    project_path = Path(project_config.base_path)
    env_file_path = get_env_file_path(project)

    # Collect .env variables
    db_info = None
    if project_config.db_name:
        db_info = {
            "db_name": project_config.db_name,
            "db_user": project_config.db_user,
            "db_password": project_config.db_password,
            "db_host": "localhost",
            "db_port": "5432",
        }

    redis_url = redis.get_redis_url() if "redis" in project_config.services else ""

    env_vars = collect_env_vars_interactive(
        project_name=project,
        stack=project_config.stack,
        db_info=db_info,
        domain=project_config.domain,
        redis_url=redis_url,
    )
    create_env_file(project, env_vars)
    symlink_env_to_project(project, project_path)

    # Configure stack (creates systemd service)
    stack_type = StackType(project_config.stack)
    stack_class = get_stack_class(stack_type)
    if stack_class:
        context = StackContext(
            project_config=project_config,
            os_info=os_info,
            package_manager=pkg_manager,
            project_path=project_path,
            shared_path=project_path / "shared",
            env_file_path=env_file_path,
            domain=project_config.domain,
        )
        stack_instance = stack_class(context)
        service_name = stack_instance.get_service_name()
        systemd.enable_service(service_name)

    # Configure Nginx
    if project_config.domain:
        if stack_type in (StackType.REACT_VITE, StackType.REACT, StackType.HTML):
            doc_root = str(project_path / "dist") if stack_type == StackType.REACT_VITE else str(project_path / "build")
            if stack_type == StackType.HTML:
                doc_root = str(project_path)
            nginx.create_static_site_config(project, project_config.domain, doc_root)
        elif stack_type == StackType.NEXTJS:
            nginx.create_reverse_proxy_config(
                project, project_config.domain, upstream="localhost:3000", use_socket=False
            )
        else:
            nginx.create_reverse_proxy_config(
                project, project_config.domain,
                static_path=str(project_path / "staticfiles"),
                media_path=str(project_path / "shared" / "media"),
                use_socket=True,
            )

    save_project_config(project_config)
    console.print("[green]✓ Project configured.[/green]")


@app.command()
def restart(
    project: str = typer.Argument("", help="Project name to restart."),
) -> None:
    """Restart all services for a project."""
    project = _resolve_project(project)
    from deploycraft.config import load_project_config
    from deploycraft.services import pm2, systemd
    from deploycraft.stacks.base import StackType

    project_config = load_project_config(project)
    if not project_config:
        console.print(f"[red]Project '{project}' not found.[/red]")
        raise typer.Exit(1)

    stack_type = StackType(project_config.stack)

    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_name = (
            f"{project}-gunicorn" if stack_type == StackType.DJANGO else f"{project}-uvicorn"
        )
        systemd.restart_service(service_name)
        console.print(f"  [green]✓[/green] {service_name} restarted")

        if "celery" in project_config.services:
            systemd.restart_service(f"{project}-celery-worker")
            console.print(f"  [green]✓[/green] {project}-celery-worker restarted")

        if "celery-beat" in project_config.services:
            systemd.restart_service(f"{project}-celery-beat")
            console.print(f"  [green]✓[/green] {project}-celery-beat restarted")

    elif stack_type == StackType.NEXTJS:
        pm2.restart_app(project)
        console.print(f"  [green]✓[/green] PM2 process '{project}' restarted")

    else:
        # Static sites — just reload nginx
        from deploycraft.services.nginx import reload_nginx
        reload_nginx()
        console.print("  [green]✓[/green] Nginx reloaded")

    console.print(f"\n[green]All services restarted for '{project}'.[/green]")


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


def _detect_stack_type(project_path) -> str:
    """Auto-detect the stack type from project files.

    Args:
        project_path: Path to the project.

    Returns:
        Stack type string or empty string if can't detect.
    """
    from pathlib import Path

    p = Path(project_path)

    # Check for Python projects
    if (p / "manage.py").exists():
        return "django"
    if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists():
        # Check if FastAPI
        for f in ["main.py", "app/main.py", "src/main.py"]:
            if (p / f).exists():
                content = (p / f).read_text()
                if "FastAPI" in content or "fastapi" in content:
                    return "fastapi"
        # Default Python = django
        if (p / "requirements.txt").exists():
            reqs = (p / "requirements.txt").read_text().lower()
            if "django" in reqs:
                return "django"
            if "fastapi" in reqs:
                return "fastapi"

    # Check for Node.js projects
    if (p / "package.json").exists():
        import json

        try:
            pkg = json.loads((p / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "react-scripts" in deps:
                return "react"
            if "vite" in deps:
                return "react_vite"
        except (json.JSONDecodeError, OSError):
            return "nextjs"

    # Check for static HTML
    if (p / "index.html").exists():
        return "html"

    return ""


if __name__ == "__main__":
    app()
