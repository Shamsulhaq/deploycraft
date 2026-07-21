"""Monitoring scheduler.

Manages the systemd timer that runs periodic health checks.
Also provides the entry point that the timer executes.
"""

import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.table import Table

from deploycraft.config import load_global_config
from deploycraft.monitor.alerter import send_alert
from deploycraft.monitor.checker import AlertLevel, run_system_check
from deploycraft.utils import error, run_cmd, step, success, warning

console = Console()

TIMER_NAME = "deploycraft-monitor"
SYSTEMD_DIR = Path("/etc/systemd/system")

MONITOR_SERVICE_TEMPLATE = """\
[Unit]
Description=DeployCraft System Monitor
After=network.target

[Service]
Type=oneshot
ExecStart={python_path} -m deploycraft.monitor.scheduler --run-check
StandardOutput=journal
StandardError=journal
"""

MONITOR_TIMER_TEMPLATE = """\
[Unit]
Description=DeployCraft Monitoring Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec={interval}min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""


def start_monitoring() -> None:
    """Install and start the monitoring systemd timer."""
    config = load_global_config()

    if not config.initialized:
        warning("DeployCraft not initialized. Run 'deploycraft init' first.")
        return

    step("Setting up monitoring timer...")

    # Find the python interpreter
    python_path = sys.executable

    # Create service file
    service_content = MONITOR_SERVICE_TEMPLATE.format(python_path=python_path)
    timer_content = MONITOR_TIMER_TEMPLATE.format(
        interval=config.monitor_interval_minutes
    )

    # Write service file
    service_path = SYSTEMD_DIR / f"{TIMER_NAME}.service"
    _write_systemd_file(service_path, service_content)

    # Write timer file
    timer_path = SYSTEMD_DIR / f"{TIMER_NAME}.timer"
    _write_systemd_file(timer_path, timer_content)

    # Reload systemd
    run_cmd(["sudo", "systemctl", "daemon-reload"])

    # Enable and start timer
    result = run_cmd(["sudo", "systemctl", "enable", "--now", f"{TIMER_NAME}.timer"])
    if result.success:
        success(f"Monitoring started (every {config.monitor_interval_minutes} minutes)")
        console.print(f"  [dim]Timer: {timer_path}[/dim]")
        console.print(f"  [dim]Service: {service_path}[/dim]")
    else:
        error(f"Failed to start monitoring timer: {result.stderr.strip()[:200]}")


def stop_monitoring() -> None:
    """Stop and disable the monitoring timer."""
    step("Stopping monitoring timer...")

    run_cmd(["sudo", "systemctl", "stop", f"{TIMER_NAME}.timer"])
    run_cmd(["sudo", "systemctl", "disable", f"{TIMER_NAME}.timer"])

    success("Monitoring stopped")


def show_monitor_status() -> None:
    """Show the current monitoring status."""
    # Check if timer is active
    result = run_cmd(["sudo", "systemctl", "is-active", f"{TIMER_NAME}.timer"])
    timer_active = result.success and result.stdout.strip() == "active"

    config = load_global_config()

    console.print("\n[bold]Monitoring Status[/bold]")
    console.print(f"  Timer: {'[green]Active[/green]' if timer_active else '[red]Inactive[/red]'}")
    console.print(f"  Interval: {config.monitor_interval_minutes} minutes")
    console.print(f"  Admin email: {config.admin_email or '[yellow]Not configured[/yellow]'}")
    console.print(f"  SMTP: {'[green]Configured[/green]' if config.smtp.host else '[yellow]Not configured[/yellow]'}")

    # Show thresholds
    console.print("\n[bold]Thresholds:[/bold]")
    table = Table(show_header=True)
    table.add_column("Metric")
    table.add_column("Warning", style="yellow")
    table.add_column("Critical", style="red")

    table.add_row("CPU", f"{config.cpu_warning_threshold}%", f"{config.cpu_critical_threshold}%")
    table.add_row("Memory", f"{config.memory_warning_threshold}%", f"{config.memory_critical_threshold}%")
    table.add_row("Disk", f"{config.disk_warning_threshold}%", f"{config.disk_critical_threshold}%")

    console.print(table)

    # Run a quick check now
    if timer_active:
        console.print("\n[bold]Current Metrics:[/bold]")
        check_result = run_system_check(config)

        for metric in check_result.metrics:
            if metric.level == AlertLevel.OK:
                icon = "[green]✓[/green]"
            elif metric.level == AlertLevel.WARNING:
                icon = "[yellow]⚠[/yellow]"
            else:
                icon = "[red]✗[/red]"
            console.print(f"  {icon} {metric.name}: {metric.value:.1f}{metric.unit}")


def execute_check() -> None:
    """Execute a monitoring check (called by systemd timer).

    This is the main entry point that the timer service calls.
    It runs the system check and sends alerts if needed.
    """
    config = load_global_config()
    check_result = run_system_check(config)

    if check_result.has_alerts:
        send_alert(check_result, config)

    # Log results
    import logging

    logger = logging.getLogger("deploycraft.monitor")
    if check_result.has_alerts:
        alert_summary = ", ".join(
            f"{a.name}={a.value:.1f}{a.unit}" for a in check_result.alerts
        )
        logger.warning(f"Alerts triggered: {alert_summary}")
    else:
        logger.info("System check passed - all metrics OK")


def _write_systemd_file(path: Path, content: str) -> None:
    """Write a systemd file via sudo."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".service", delete=False) as f:
        f.write(content)
        temp_path = f.name

    run_cmd(["sudo", "cp", temp_path, str(path)])
    run_cmd(["sudo", "chmod", "644", str(path)])
    Path(temp_path).unlink(missing_ok=True)


# Entry point for the systemd service
if __name__ == "__main__":
    if "--run-check" in sys.argv:
        execute_check()
