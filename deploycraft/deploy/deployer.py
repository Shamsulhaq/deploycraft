"""Deployment orchestrator.

The main deployment pipeline that coordinates all services and stack operations.
This is the core of DeployCraft - it runs the interactive wizard and orchestrates
the full deployment process.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from deploycraft.config import (
    GlobalConfig,
    ProjectConfig,
    delete_project_config,
    load_global_config,
    load_project_config,
    save_project_config,
)
from deploycraft.deploy.env_manager import (
    collect_env_vars_interactive,
    create_env_file,
    get_env_file_path,
    symlink_env_to_release,
)
from deploycraft.deploy.health_check import run_health_check
from deploycraft.deploy.rollback import create_release_dir, prune_old_releases, set_current_symlink
from deploycraft.os_detect import ensure_supported_os
from deploycraft.services import git, nginx, node, pm2, postgres, redis, ssl, systemd
from deploycraft.stacks.base import (
    STACK_CHOICES,
    StackContext,
    StackType,
    get_stack_class,
)
from deploycraft.utils import (
    ensure_dir,
    error,
    header,
    human_timestamp,
    step,
    success,
    timestamp,
    warning,
)

console = Console()


def run_deploy_wizard() -> None:
    """Run the interactive deployment wizard.

    This is the main entry point for deploying a new project. It:
    1. Asks user to select a stack
    2. Collects project info (name, git URL, domain, etc.)
    3. Detects required services
    4. Installs and configures everything
    5. Reports results
    6. Optionally loops to deploy another project
    """
    global_config = load_global_config()

    if not global_config.initialized:
        console.print(
            "[yellow]DeployCraft has not been initialized yet.[/yellow]\n"
            "Run [bold]deploycraft init[/bold] first to configure SMTP and preferences.\n"
            "Continuing with defaults..."
        )

    console.print(
        Panel(
            "[bold blue]DeployCraft Deployment Wizard[/bold blue]\n\n"
            "Let's deploy your application step by step.",
            title="🚀 Deploy",
        )
    )

    while True:
        _deploy_single_project(global_config)

        if not Confirm.ask("\n[bold]Deploy another project?[/bold]", default=False):
            break

    console.print("\n[green]All done![/green] Use [bold]deploycraft status[/bold] to check health.")


def _deploy_single_project(global_config: GlobalConfig) -> None:
    """Deploy a single project through the full pipeline."""

    # --- Step 1: Select stack ---
    header("Step 1: Select Stack")
    console.print("")
    for i, (stack_type, name, desc) in enumerate(STACK_CHOICES, 1):
        console.print(f"  [cyan]{i}[/cyan]. {name} — [dim]{desc}[/dim]")

    choice = IntPrompt.ask(
        "\nSelect stack",
        default=1,
        choices=[str(i) for i in range(1, len(STACK_CHOICES) + 1)],
    )
    selected_stack_type, selected_name, _ = STACK_CHOICES[choice - 1]
    success(f"Selected: {selected_name}")

    # --- Step 2: Project details ---
    header("Step 2: Project Details")

    project_name = Prompt.ask("Project name (no spaces)")
    project_name = project_name.lower().replace(" ", "-").strip()

    # Check if project already exists
    existing = load_project_config(project_name)
    if existing:
        if not Confirm.ask(
            f"[yellow]Project '{project_name}' already exists. Overwrite?[/yellow]",
            default=False,
        ):
            return

    base_path = Prompt.ask(
        "Base path",
        default=f"{global_config.default_base_path}/{project_name}",
    )
    git_url = Prompt.ask("GitHub/Git URL")
    branch = Prompt.ask("Branch", default="main")
    domain = Prompt.ask("Domain name (e.g., myapp.com)")

    # Validate git URL
    if not git.validate_git_url(git_url):
        error("Invalid git URL format")
        return

    # --- Step 3: Detect OS and prepare ---
    header("Step 3: System Check")
    os_info, pkg_manager = ensure_supported_os()

    # --- Step 3b: SSH Key setup (for SSH git URLs or private repos) ---
    _ensure_ssh_key_for_git(git_url)

    # --- Step 4: Clone repository ---
    header("Step 4: Clone Repository")

    # Test git access
    step("Testing repository access...")
    if not git.test_git_access(git_url):
        error("Cannot access the git repository. Check URL and permissions.")
        if git_url.startswith("git@") or git_url.startswith("ssh://"):
            warning(
                "This looks like an SSH URL. Make sure you've added the deploy key "
                "to your Git provider. Run 'deploycraft ssh-key show' to see your key."
            )
        return
    success("Repository accessible")

    # Create release directory
    release_ts = timestamp()
    release_path = create_release_dir(base_path, release_ts)
    shared_path = ensure_dir(Path(base_path) / "shared")
    ensure_dir(shared_path / "logs")
    ensure_dir(shared_path / "media")

    # Clone
    if not git.clone_repo(git_url, release_path, branch=branch):
        error("Failed to clone repository")
        return

    # --- Step 5: Detect services ---
    header("Step 5: Detect Dependencies")

    # Import the correct stack class
    stack_class = get_stack_class(selected_stack_type)
    if stack_class is None:
        error(f"Stack '{selected_name}' is not yet implemented")
        return

    # Create project config (partial, will be updated)
    project_config = ProjectConfig(
        name=project_name,
        stack=selected_stack_type.value,
        base_path=base_path,
        git_url=git_url,
        branch=branch,
        domain=domain,
    )

    # Create stack context
    env_file_path = get_env_file_path(project_name)
    context = StackContext(
        project_config=project_config,
        os_info=os_info,
        package_manager=pkg_manager,
        release_path=release_path,
        shared_path=shared_path,
        env_file_path=env_file_path,
        domain=domain,
    )

    stack = stack_class(context)
    detected = stack.detect_services(release_path)

    # Show detected services
    services = detected.summary()
    if services:
        console.print(f"\n[green]Detected services:[/green] {', '.join(services)}")
        if not Confirm.ask("Proceed with these services?", default=True):
            return
    else:
        console.print("[dim]No additional services detected.[/dim]")

    # --- Step 6: Install system services ---
    header("Step 6: Install Services")

    db_info: Optional[dict[str, str]] = None
    redis_url = ""

    # Install PostgreSQL if needed
    if detected.needs_postgresql:
        if not postgres.is_postgresql_running():
            if not postgres.install_postgresql(pkg_manager):
                error("PostgreSQL installation failed")
                return
        db_info = postgres.create_database(project_name)
        if not db_info:
            error("Database creation failed")
            return
        project_config.db_name = db_info["db_name"]
        project_config.db_user = db_info["db_user"]
        project_config.db_password = db_info["db_password"]
        project_config.services.append("postgresql")

    # Install Redis if needed
    if detected.needs_redis:
        if not redis.is_redis_running(pkg_manager):
            if not redis.install_redis(pkg_manager):
                error("Redis installation failed")
                return
        redis_url = redis.get_redis_url()
        project_config.services.append("redis")

    # Install Node.js if needed
    if detected.needs_nodejs:
        if not node.install_nodejs(pkg_manager):
            error("Node.js installation failed")
            return

    # Install PM2 if needed
    if detected.needs_pm2:
        if not pm2.install_pm2():
            error("PM2 installation failed")
            return
        project_config.services.append("pm2")

    # Install Nginx
    if detected.needs_nginx:
        run_cmd_safe(pkg_manager.install_cmd("nginx"))
        # Nginx might already be installed, that's fine

    # --- Step 7: Configure environment ---
    header("Step 7: Environment Configuration")

    env_vars = collect_env_vars_interactive(
        project_name=project_name,
        stack=selected_stack_type.value,
        db_info=db_info,
        domain=domain,
        redis_url=redis_url,
    )
    create_env_file(project_name, env_vars)
    project_config.env_vars = env_vars

    # Symlink .env into release
    symlink_env_to_release(project_name, release_path)

    # --- Step 8: Install app dependencies ---
    header("Step 8: Install Dependencies")

    if not stack.install_dependencies():
        error("Dependency installation failed")
        return

    # --- Step 9: Build ---
    header("Step 9: Build")

    if not stack.build():
        error("Build failed")
        return

    # --- Step 10: Run migrations ---
    header("Step 10: Database Migration")

    if not stack.run_migrations():
        error("Migration failed")
        return

    # --- Step 11: Create superuser ---
    superuser_info = stack.create_superuser()

    # --- Step 12: Configure process manager ---
    header("Step 11: Process Manager")

    service_name = stack.get_service_name()

    # For systemd-based stacks (Django, FastAPI)
    if selected_stack_type in (StackType.DJANGO, StackType.FASTAPI):
        # Celery services
        if detected.needs_celery:
            celery_app = _detect_celery_app(release_path, project_name)
            venv_path = release_path / "venv"
            systemd.create_celery_worker_service(
                project_name=project_name,
                working_dir=release_path,
                venv_path=venv_path,
                celery_app=celery_app,
                env_file=env_file_path,
            )
            systemd.enable_service(f"{project_name}-celery-worker")
            project_config.services.append("celery")

        if detected.needs_celery_beat:
            celery_app = _detect_celery_app(release_path, project_name)
            venv_path = release_path / "venv"
            systemd.create_celery_beat_service(
                project_name=project_name,
                working_dir=release_path,
                venv_path=venv_path,
                celery_app=celery_app,
                env_file=env_file_path,
                shared_dir=shared_path,
            )
            systemd.enable_service(f"{project_name}-celery-beat")
            project_config.services.append("celery-beat")

        # Enable main app service
        systemd.enable_service(service_name)

    elif selected_stack_type == StackType.NEXTJS:
        # Start with PM2
        port = 3000
        pm2.start_app(
            project_name=project_name,
            working_dir=release_path,
            script="npm",
            args="start",
            port=port,
        )
        context.port = port

    # --- Step 13: Configure Nginx ---
    header("Step 12: Nginx Configuration")

    if selected_stack_type in (StackType.REACT_VITE, StackType.REACT, StackType.HTML):
        # Static site
        document_root = str(release_path / "build")  # Will be adjusted per stack
        if selected_stack_type == StackType.REACT_VITE:
            document_root = str(release_path / "dist")
        elif selected_stack_type == StackType.HTML:
            document_root = str(release_path)

        nginx.create_static_site_config(
            project_name=project_name,
            domain=domain,
            document_root=document_root,
        )
    elif selected_stack_type == StackType.NEXTJS:
        # Reverse proxy to PM2 (localhost:3000)
        nginx.create_reverse_proxy_config(
            project_name=project_name,
            domain=domain,
            upstream="localhost:3000",
            use_socket=False,
        )
    else:
        # Django/FastAPI with Unix socket
        nginx.create_reverse_proxy_config(
            project_name=project_name,
            domain=domain,
            static_path=str(release_path / "staticfiles"),
            media_path=str(shared_path / "media"),
            use_socket=True,
        )

    # --- Step 14: SSL Certificate ---
    header("Step 13: SSL Certificate")

    if Confirm.ask(f"Obtain SSL certificate for {domain}?", default=True):
        admin_email = global_config.admin_email or Prompt.ask("Email for Let's Encrypt")
        ssl.install_certbot(pkg_manager)
        ssl.obtain_certificate(domain=domain, email=admin_email)
        ssl.setup_auto_renewal()

    # --- Step 15: Set current symlink ---
    set_current_symlink(base_path, release_ts)

    # --- Step 16: Update project config ---
    project_config.current_release = release_ts
    project_config.releases.append(release_ts)
    project_config.last_deployed = human_timestamp()
    project_config.created_at = project_config.created_at or human_timestamp()
    save_project_config(project_config)

    # --- Step 17: Health check ---
    header("Step 14: Health Check")
    health_ok = run_health_check(domain)

    # --- Step 18: Report ---
    _display_deploy_report(project_config, db_info, superuser_info, health_ok)

    # Prune old releases
    prune_old_releases(base_path, max_releases=global_config.max_releases)


def run_redeploy(project_name: str) -> None:
    """Redeploy a project: pull latest code, rebuild, restart.

    Args:
        project_name: Name of the project to redeploy.
    """
    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found. Run 'deploycraft list' to see projects.")
        return

    header(f"Redeploying: {project_name}")

    os_info, pkg_manager = ensure_supported_os()

    # Create new release
    release_ts = timestamp()
    release_path = create_release_dir(project.base_path, release_ts)
    shared_path = Path(project.base_path) / "shared"

    # Clone fresh
    if not git.clone_repo(project.git_url, release_path, branch=project.branch):
        error("Failed to clone repository")
        return

    # Symlink .env
    symlink_env_to_release(project_name, release_path)

    # Get stack and rebuild
    stack_type = StackType(project.stack)
    stack_class = get_stack_class(stack_type)
    if not stack_class:
        error(f"Stack class not found for: {project.stack}")
        return

    env_file_path = get_env_file_path(project_name)
    context = StackContext(
        project_config=project,
        os_info=os_info,
        package_manager=pkg_manager,
        release_path=release_path,
        shared_path=shared_path,
        env_file_path=env_file_path,
        domain=project.domain,
    )
    stack = stack_class(context)

    # Install deps and build
    step("Installing dependencies...")
    if not stack.install_dependencies():
        error("Dependency installation failed")
        return

    step("Building...")
    if not stack.build():
        error("Build failed")
        return

    step("Running migrations...")
    stack.run_migrations()

    # Switch symlink
    set_current_symlink(project.base_path, release_ts)

    # Restart services
    step("Restarting services...")
    service_name = stack.get_service_name()
    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        systemd.restart_service(service_name)
        if "celery" in project.services:
            systemd.restart_service(f"{project_name}-celery-worker")
        if "celery-beat" in project.services:
            systemd.restart_service(f"{project_name}-celery-beat")
    elif stack_type == StackType.NEXTJS:
        pm2.restart_app(project_name)

    # Update config
    project.current_release = release_ts
    project.releases.append(release_ts)
    project.last_deployed = human_timestamp()
    save_project_config(project)

    # Health check
    health_ok = run_health_check(project.domain)

    # Prune old releases
    global_config = load_global_config()
    prune_old_releases(project.base_path, max_releases=global_config.max_releases)

    if health_ok:
        success(f"Redeployment of '{project_name}' complete!")
    else:
        warning(f"Deployed but health check failed. Consider rollback: deploycraft rollback {project_name}")


def remove_project(project_name: str, force: bool = False) -> None:
    """Remove a managed project.

    Args:
        project_name: Name of the project.
        force: Skip confirmation prompt.
    """
    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    if not force:
        console.print(f"\n[red bold]This will remove project '{project_name}':[/red bold]")
        console.print("  • Nginx configuration")
        console.print("  • Systemd services")
        console.print("  • Environment files")
        console.print("  • Project configuration")
        console.print(f"  [yellow]Note: Project files at {project.base_path} will NOT be deleted.[/yellow]")

        if not Confirm.ask("\nProceed?", default=False):
            return

    step("Removing services...")
    # Stop and remove systemd services
    stack_type = StackType(project.stack)
    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_base = f"{project_name}-gunicorn" if stack_type == StackType.DJANGO else f"{project_name}-uvicorn"
        systemd.remove_service(service_base)
        if "celery" in project.services:
            systemd.remove_service(f"{project_name}-celery-worker")
        if "celery-beat" in project.services:
            systemd.remove_service(f"{project_name}-celery-beat")
    elif stack_type == StackType.NEXTJS:
        pm2.delete_app(project_name)

    # Remove Nginx config
    nginx.remove_nginx_config(project_name)

    # Remove project config
    delete_project_config(project_name)

    success(f"Project '{project_name}' removed from DeployCraft management.")


def show_logs(project_name: str, lines: int = 50) -> None:
    """Show logs for a project's services.

    Args:
        project_name: Name of the project.
        lines: Number of lines to show.
    """
    from deploycraft.utils import run_cmd

    project = load_project_config(project_name)
    if not project:
        error(f"Project '{project_name}' not found.")
        return

    stack_type = StackType(project.stack)

    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_name = f"{project_name}-gunicorn" if stack_type == StackType.DJANGO else f"{project_name}-uvicorn"
        console.print(f"\n[bold]Logs for {service_name}:[/bold]")
        result = run_cmd(
            ["sudo", "journalctl", "-u", f"{service_name}.service", "-n", str(lines), "--no-pager"]
        )
        if result.success:
            console.print(result.stdout)
    elif stack_type == StackType.NEXTJS:
        console.print(f"\n[bold]PM2 logs for {project_name}:[/bold]")
        result = run_cmd(["pm2", "logs", project_name, "--lines", str(lines), "--nostream"])
        if result.success:
            console.print(result.stdout)


def _ensure_ssh_key_for_git(git_url: str) -> None:
    """Ensure an SSH key exists and prompt user to add it to Git if needed.

    For SSH-based git URLs (git@github.com:...) this is mandatory.
    For HTTPS URLs it's optional but offered for convenience.

    Args:
        git_url: The repository URL.
    """
    from rich.prompt import Confirm

    from deploycraft.services.ssh import (
        display_public_key_instructions,
        ensure_keypair_exists,
        key_exists,
        test_ssh_connection,
    )

    is_ssh_url = git_url.startswith("git@") or git_url.startswith("ssh://")
    is_https_url = git_url.startswith("https://") or git_url.startswith("http://")

    if is_ssh_url:
        # SSH URL — deploy key is required
        header("Step 3b: SSH Key Setup")
        if not key_exists():
            console.print(
                "[yellow]No SSH deploy key found — generating one now...[/yellow]"
            )
            public_key = ensure_keypair_exists()
            if public_key:
                display_public_key_instructions(public_key, git_url)
                Confirm.ask(
                    "Add the key to your Git provider, then press Enter to continue",
                    default=True,
                )
        else:
            public_key = ensure_keypair_exists()
            success("SSH deploy key already exists.")
            if Confirm.ask("Show the public key?", default=False):
                if public_key:
                    display_public_key_instructions(public_key, git_url)

        # Test the connection
        test_ssh_connection(git_url)

    elif is_https_url:
        # HTTPS URL — key is optional; offer if it already exists
        if key_exists():
            # Key exists but not shown yet — offer to show it in case this is a private repo
            if Confirm.ask(
                "Show SSH deploy key? (useful if the repo is private and you want to use SSH later)",
                default=False,
            ):
                public_key = ensure_keypair_exists()
                if public_key:
                    display_public_key_instructions(public_key, git_url)
        else:
            # No key at all — offer to generate one
            if Confirm.ask(
                "Generate an SSH deploy key for this server? "
                "(optional for HTTPS, required for SSH git URLs)",
                default=False,
            ):
                public_key = ensure_keypair_exists()
                if public_key:
                    display_public_key_instructions(public_key, git_url)
                    Confirm.ask("Press Enter once you've added the key (or skip)", default=True)


def _detect_celery_app(release_path: Path, project_name: str) -> str:
    """Try to detect the Celery app module name from the project.

    Args:
        release_path: Path to the project source.
        project_name: Project name as fallback.

    Returns:
        Celery app string (e.g., "myproject.celery:app").
    """
    # Look for celery.py in common locations
    for candidate in release_path.iterdir():
        if candidate.is_dir():
            celery_file = candidate / "celery.py"
            if celery_file.exists():
                return candidate.name
    # Fallback
    return project_name


def _display_deploy_report(
    project: ProjectConfig,
    db_info: Optional[dict[str, str]],
    superuser_info: Optional[dict[str, str]],
    health_ok: bool,
) -> None:
    """Display the deployment summary report."""
    console.print("")
    console.print(
        Panel(
            "[bold green]Deployment Complete![/bold green]",
            title=f"✅ {project.name}",
        )
    )

    table = Table(title="Deployment Summary")
    table.add_column("Item", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Project", project.name)
    table.add_row("Stack", project.stack)
    table.add_row("Domain", project.domain)
    table.add_row("Path", project.base_path)
    table.add_row("Branch", project.branch)
    table.add_row("Release", project.current_release)
    table.add_row("Health", "[green]✓ OK[/green]" if health_ok else "[red]✗ Failed[/red]")

    console.print(table)

    if db_info:
        console.print("\n[bold]Database Credentials:[/bold]")
        cred_table = Table(show_header=False)
        cred_table.add_column("Key", style="dim")
        cred_table.add_column("Value", style="yellow")
        cred_table.add_row("Database", db_info["db_name"])
        cred_table.add_row("User", db_info["db_user"])
        cred_table.add_row("Password", db_info["db_password"])
        cred_table.add_row("Host", f"{db_info['db_host']}:{db_info['db_port']}")
        console.print(cred_table)
        console.print("[dim]⚠ Save these credentials! They won't be shown again.[/dim]")

    if superuser_info:
        console.print("\n[bold]Admin/Superuser:[/bold]")
        su_table = Table(show_header=False)
        su_table.add_column("Key", style="dim")
        su_table.add_column("Value", style="yellow")
        for key, value in superuser_info.items():
            su_table.add_row(key, value)
        console.print(su_table)


def run_cmd_safe(cmd: list[str]) -> bool:
    """Run a command and return success status (no exit on failure)."""
    from deploycraft.utils import run_cmd

    result = run_cmd(cmd)
    return result.success
