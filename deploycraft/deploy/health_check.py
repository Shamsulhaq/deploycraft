"""Post-deployment health checking.

Verifies that deployed applications are responding correctly.
"""

import time
import urllib.error
import urllib.request

from rich.console import Console
from rich.table import Table

from deploycraft.config import get_all_projects, load_project_config
from deploycraft.services import pm2, systemd
from deploycraft.stacks.base import StackType
from deploycraft.utils import error, step, success, warning

console = Console()


def run_health_check(domain: str, timeout: int = 10, retries: int = 3) -> bool:
    """Check if a deployed application is responding.

    Performs HTTP GET request to the domain and checks for a successful response.

    Args:
        domain: Domain name to check.
        timeout: Request timeout in seconds.
        retries: Number of retry attempts.

    Returns:
        True if the application responds with a 2xx or 3xx status.
    """
    step(f"Health check: {domain}")

    # Try HTTPS first, fall back to HTTP
    urls = [f"https://{domain}", f"http://{domain}"]

    for url in urls:
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "DeployCraft-HealthCheck/1.0"},
                )
                response = urllib.request.urlopen(req, timeout=timeout)
                status = response.status

                if 200 <= status < 400:
                    success(f"Health check passed: {url} (HTTP {status})")
                    return True
                else:
                    warning(f"Unexpected status: HTTP {status}")

            except urllib.error.HTTPError as e:
                # 4xx/5xx are still "responding" in a sense
                if e.code < 500:
                    success(f"Application responding: {url} (HTTP {e.code})")
                    return True
                warning(f"Server error: HTTP {e.code} (attempt {attempt + 1}/{retries})")

            except urllib.error.URLError:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue

            except Exception:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue

    error(f"Health check failed: {domain} is not responding")
    return False


def check_service_health(project_name: str) -> dict[str, bool]:
    """Check the health of all services for a project.

    Args:
        project_name: Name of the project.

    Returns:
        Dict mapping service name → is_healthy.
    """
    project = load_project_config(project_name)
    if not project:
        return {}

    results = {}
    stack_type = StackType(project.stack)

    # Check main application service
    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        service_name = (
            f"{project_name}-gunicorn"
            if stack_type == StackType.DJANGO
            else f"{project_name}-uvicorn"
        )
        results[service_name] = systemd.is_service_active(service_name)

        # Check celery services
        if "celery" in project.services:
            celery_name = f"{project_name}-celery-worker"
            results[celery_name] = systemd.is_service_active(celery_name)

        if "celery-beat" in project.services:
            beat_name = f"{project_name}-celery-beat"
            results[beat_name] = systemd.is_service_active(beat_name)

    elif stack_type == StackType.NEXTJS:
        results[f"{project_name} (PM2)"] = pm2.is_running(project_name)

    # Check HTTP health
    if project.domain:
        results[f"HTTP ({project.domain})"] = run_health_check(
            project.domain, timeout=5, retries=1
        )

    return results


def show_status() -> None:
    """Display a dashboard of all projects and system health."""
    import psutil

    projects = get_all_projects()

    if not projects:
        console.print("[yellow]No projects deployed yet.[/yellow]")
        console.print("Run [bold]deploycraft deploy[/bold] to get started.")
        return

    # Project status table
    table = Table(title="DeployCraft Status Dashboard")
    table.add_column("Project", style="cyan")
    table.add_column("Stack", style="magenta")
    table.add_column("Domain", style="blue")
    table.add_column("Release", style="dim")
    table.add_column("Status", style="green")
    table.add_column("Health")

    for project in projects:
        # Quick service check
        stack_type = StackType(project.stack)
        is_running = False

        if stack_type in (StackType.DJANGO, StackType.FASTAPI):
            service_name = (
                f"{project.name}-gunicorn"
                if stack_type == StackType.DJANGO
                else f"{project.name}-uvicorn"
            )
            is_running = systemd.is_service_active(service_name)
        elif stack_type == StackType.NEXTJS:
            is_running = pm2.is_running(project.name)
        else:
            # Static sites are always "running" via Nginx
            is_running = True

        status = "[green]Running[/green]" if is_running else "[red]Stopped[/red]"
        health = "✓" if is_running else "✗"

        table.add_row(
            project.name,
            project.stack,
            project.domain or "-",
            project.current_release or "-",
            status,
            f"[green]{health}[/green]" if is_running else f"[red]{health}[/red]",
        )

    console.print(table)

    # System metrics
    console.print("")
    cpu = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    cpu_color = "green" if cpu < 80 else ("yellow" if cpu < 90 else "red")
    mem_color = "green" if memory.percent < 80 else ("yellow" if memory.percent < 90 else "red")
    disk_color = "green" if disk.percent < 80 else ("yellow" if disk.percent < 90 else "red")

    console.print(
        f"  CPU: [{cpu_color}]{cpu:.1f}%[/{cpu_color}]  |  "
        f"Memory: [{mem_color}]{memory.percent:.1f}%[/{mem_color}]  |  "
        f"Disk: [{disk_color}]{disk.percent:.1f}%[/{disk_color}]"
    )
