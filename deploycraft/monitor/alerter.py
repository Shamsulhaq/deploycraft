"""Email alerting for system monitoring.

Sends alert emails when metrics exceed thresholds, with cooldown
to prevent alert flooding.
"""

import json
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from rich.console import Console

from deploycraft.config import GlobalConfig, get_config_dir, load_global_config
from deploycraft.monitor.checker import AlertLevel, MetricResult, SystemCheckResult
from deploycraft.utils import error, warning

console = Console()

# File to track sent alerts (for cooldown)
ALERT_STATE_FILE = "alert_state.json"


def send_alert(check_result: SystemCheckResult, config: Optional[GlobalConfig] = None) -> bool:
    """Send alert email if there are new alerts that haven't been sent recently.

    Args:
        check_result: System check results with metrics.
        config: Global config. Loaded if not provided.

    Returns:
        True if alert was sent (or no alert needed).
    """
    if config is None:
        config = load_global_config()

    if not check_result.has_alerts:
        return True

    # Check cooldown
    alerts_to_send = _filter_cooled_down_alerts(
        check_result.alerts,
        cooldown_minutes=config.alert_cooldown_minutes,
    )

    if not alerts_to_send:
        return True

    # Build email
    subject = _build_subject(alerts_to_send, check_result.hostname)
    body = _build_email_body(check_result, alerts_to_send)

    # Send
    sent = _send_email(
        to_address=config.admin_email,
        subject=subject,
        body=body,
        config=config,
    )

    if sent:
        # Record that we sent these alerts
        _record_alerts_sent(alerts_to_send)

    return sent


def _filter_cooled_down_alerts(
    alerts: list[MetricResult],
    cooldown_minutes: int,
) -> list[MetricResult]:
    """Filter out alerts that were sent too recently.

    Args:
        alerts: List of alert metrics.
        cooldown_minutes: Minimum time between repeated alerts for same metric.

    Returns:
        List of alerts that should be sent.
    """
    state = _load_alert_state()
    now = datetime.now()
    cooldown = timedelta(minutes=cooldown_minutes)

    to_send = []
    for alert in alerts:
        last_sent_str = state.get(alert.name)
        if last_sent_str:
            last_sent = datetime.fromisoformat(last_sent_str)
            if now - last_sent < cooldown:
                continue
        to_send.append(alert)

    return to_send


def _build_subject(alerts: list[MetricResult], hostname: str) -> str:
    """Build email subject line."""
    has_critical = any(a.level == AlertLevel.CRITICAL for a in alerts)
    level_prefix = "🔴 CRITICAL" if has_critical else "🟡 WARNING"
    return f"[DeployCraft] {level_prefix} - {hostname} - {len(alerts)} alert(s)"


def _build_email_body(result: SystemCheckResult, alerts: list[MetricResult]) -> str:
    """Build the email body with alert details."""
    lines = [
        "DeployCraft System Alert",
        "========================",
        "",
        f"Server: {result.hostname}",
        f"Time: {result.timestamp}",
        "",
        f"ALERTS ({len(alerts)}):",
        f"{'─' * 50}",
    ]

    for alert in alerts:
        icon = "🔴" if alert.level == AlertLevel.CRITICAL else "🟡"
        lines.append(f"  {icon} [{alert.level.upper()}] {alert.name}: {alert.message}")

    lines.extend([
        "",
        "ALL METRICS:",
        f"{'─' * 50}",
    ])

    for metric in result.metrics:
        status = "✓" if metric.level == AlertLevel.OK else "⚠"
        lines.append(f"  {status} {metric.name}: {metric.value:.1f}{metric.unit}")

    if result.service_statuses:
        lines.extend([
            "",
            "SERVICE STATUS:",
            f"{'─' * 50}",
        ])
        for service, is_healthy in result.service_statuses.items():
            status = "✓ Running" if is_healthy else "✗ DOWN"
            lines.append(f"  {status}: {service}")

    lines.extend([
        "",
        "─" * 50,
        "This alert was sent by DeployCraft monitoring.",
        "Configure thresholds with: deploycraft init",
    ])

    return "\n".join(lines)


def _send_email(
    to_address: str,
    subject: str,
    body: str,
    config: GlobalConfig,
) -> bool:
    """Send an email via SMTP.

    Args:
        to_address: Recipient email address.
        subject: Email subject.
        body: Email body (plain text).
        config: Global config with SMTP settings.

    Returns:
        True if email was sent successfully.
    """
    smtp = config.smtp
    if not smtp.host or not to_address:
        warning("SMTP not configured. Run 'deploycraft init' to set up email alerts.")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp.from_address or smtp.username
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if smtp.use_tls:
            server = smtplib.SMTP(smtp.host, smtp.port)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp.host, smtp.port)

        if smtp.username and smtp.password:
            server.login(smtp.username, smtp.password)

        server.sendmail(msg["From"], [to_address], msg.as_string())
        server.quit()

        return True

    except Exception as e:
        error(f"Failed to send alert email: {e}")
        return False


def _load_alert_state() -> dict[str, str]:
    """Load the alert state file (tracks when alerts were last sent)."""
    state_file = get_config_dir() / ALERT_STATE_FILE
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _record_alerts_sent(alerts: list[MetricResult]) -> None:
    """Record that alerts were sent at the current time."""
    state = _load_alert_state()
    now = datetime.now().isoformat()

    for alert in alerts:
        state[alert.name] = now

    state_file = get_config_dir() / ALERT_STATE_FILE
    try:
        state_file.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def send_test_email(config: Optional[GlobalConfig] = None) -> bool:
    """Send a test email to verify SMTP configuration.

    Args:
        config: Global config. Loaded if not provided.

    Returns:
        True if test email was sent successfully.
    """
    if config is None:
        config = load_global_config()

    return _send_email(
        to_address=config.admin_email,
        subject="[DeployCraft] Test Alert - Configuration Verified ✓",
        body=(
            "This is a test email from DeployCraft.\n\n"
            "If you received this, your SMTP configuration is working correctly.\n\n"
            "You will receive alerts when system metrics exceed configured thresholds."
        ),
        config=config,
    )
