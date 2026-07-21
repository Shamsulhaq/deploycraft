"""System metrics collection for monitoring.

Collects CPU, memory, disk, and service health metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import psutil
from rich.console import Console

from deploycraft.config import GlobalConfig, get_all_projects, load_global_config
from deploycraft.deploy.health_check import check_service_health

console = Console()


class AlertLevel:
    """Alert severity levels."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class MetricResult:
    """Result of a single metric check."""

    name: str
    value: float
    unit: str
    level: str  # ok, warning, critical
    message: str = ""

    @property
    def is_alert(self) -> bool:
        return self.level in (AlertLevel.WARNING, AlertLevel.CRITICAL)


@dataclass
class SystemCheckResult:
    """Result of a full system check."""

    timestamp: str
    hostname: str
    metrics: list[MetricResult] = field(default_factory=list)
    service_statuses: dict[str, bool] = field(default_factory=dict)

    @property
    def has_alerts(self) -> bool:
        return any(m.is_alert for m in self.metrics)

    @property
    def alerts(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.is_alert]

    @property
    def critical_alerts(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.level == AlertLevel.CRITICAL]

    @property
    def warning_alerts(self) -> list[MetricResult]:
        return [m for m in self.metrics if m.level == AlertLevel.WARNING]


def run_system_check(config: Optional[GlobalConfig] = None) -> SystemCheckResult:
    """Run a full system health check.

    Collects all metrics and compares against configured thresholds.

    Args:
        config: Global config with threshold settings. Loaded if not provided.

    Returns:
        SystemCheckResult with all metrics and their alert levels.
    """
    if config is None:
        config = load_global_config()

    import socket

    result = SystemCheckResult(
        timestamp=datetime.now().isoformat(),
        hostname=socket.gethostname(),
    )

    # CPU check
    cpu_percent = psutil.cpu_percent(interval=2)
    cpu_level = _check_threshold(
        cpu_percent,
        config.cpu_warning_threshold,
        config.cpu_critical_threshold,
    )
    result.metrics.append(MetricResult(
        name="CPU Usage",
        value=cpu_percent,
        unit="%",
        level=cpu_level,
        message=f"CPU at {cpu_percent:.1f}%",
    ))

    # Memory check
    memory = psutil.virtual_memory()
    mem_level = _check_threshold(
        memory.percent,
        config.memory_warning_threshold,
        config.memory_critical_threshold,
    )
    result.metrics.append(MetricResult(
        name="Memory Usage",
        value=memory.percent,
        unit="%",
        level=mem_level,
        message=f"Memory at {memory.percent:.1f}% ({_format_bytes(memory.used)}/{_format_bytes(memory.total)})",
    ))

    # Disk checks (all mounted partitions)
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disk_level = _check_threshold(
                usage.percent,
                config.disk_warning_threshold,
                config.disk_critical_threshold,
            )
            result.metrics.append(MetricResult(
                name=f"Disk ({partition.mountpoint})",
                value=usage.percent,
                unit="%",
                level=disk_level,
                message=(
                    f"Disk {partition.mountpoint} at {usage.percent:.1f}%"
                    f" ({_format_bytes(usage.used)}/{_format_bytes(usage.total)})"
                ),
            ))
        except (PermissionError, OSError):
            continue

    # Load average (Linux)
    try:
        load1, load5, load15 = psutil.getloadavg()
        cpu_count = psutil.cpu_count() or 1
        # Load is concerning if > CPU count
        load_percent = (load1 / cpu_count) * 100
        load_level = _check_threshold(load_percent, 80, 100)
        result.metrics.append(MetricResult(
            name="Load Average (1m)",
            value=load1,
            unit="",
            level=load_level,
            message=f"Load: {load1:.2f} / {load5:.2f} / {load15:.2f} ({cpu_count} cores)",
        ))
    except (AttributeError, OSError):
        pass

    # Service health for all projects
    projects = get_all_projects()
    for project in projects:
        services = check_service_health(project.name)
        for service_name, is_healthy in services.items():
            result.service_statuses[service_name] = is_healthy
            if not is_healthy:
                result.metrics.append(MetricResult(
                    name=f"Service: {service_name}",
                    value=0,
                    unit="",
                    level=AlertLevel.CRITICAL,
                    message=f"Service '{service_name}' is DOWN",
                ))

    return result


def _check_threshold(value: float, warning_threshold: int, critical_threshold: int) -> str:
    """Compare a value against warning and critical thresholds.

    Args:
        value: Current metric value.
        warning_threshold: Warning threshold.
        critical_threshold: Critical threshold.

    Returns:
        Alert level string: "ok", "warning", or "critical".
    """
    if value >= critical_threshold:
        return AlertLevel.CRITICAL
    elif value >= warning_threshold:
        return AlertLevel.WARNING
    return AlertLevel.OK


def _format_bytes(bytes_val: int) -> str:
    """Format bytes into human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}PB"
