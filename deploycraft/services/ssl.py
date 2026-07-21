"""SSL certificate management via Certbot/Let's Encrypt.

Handles SSL certificate obtaining, renewal, and Nginx HTTPS configuration.
"""

from rich.console import Console

from deploycraft.os_detect import PackageManager
from deploycraft.utils import error, run_cmd, step, success, warning

console = Console()


def install_certbot(pkg_manager: PackageManager) -> bool:
    """Install Certbot and the Nginx plugin.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        True if installation was successful.
    """
    step("Installing Certbot...")

    result = run_cmd(pkg_manager.install_cmd("certbot", "certbot-nginx"))
    if not result.success:
        error(f"Certbot installation failed: {result.stderr.strip()[:200]}")
        return False

    success("Certbot installed")
    return True


def obtain_certificate(
    domain: str,
    email: str,
    nginx_plugin: bool = True,
    dry_run: bool = False,
) -> bool:
    """Obtain an SSL certificate from Let's Encrypt.

    Args:
        domain: Domain name for the certificate.
        email: Email address for registration and renewal notices.
        nginx_plugin: Use the Nginx plugin for automatic configuration.
        dry_run: If True, perform a test run without actually obtaining a cert.

    Returns:
        True if certificate was obtained successfully.
    """
    step(f"Obtaining SSL certificate for {domain}")

    cmd = ["sudo", "certbot"]

    if nginx_plugin:
        cmd.append("--nginx")
    else:
        cmd.append("certonly")
        cmd.extend(["--webroot", "-w", "/var/www/html"])

    cmd.extend([
        "-d", domain,
        "--email", email,
        "--agree-tos",
        "--non-interactive",
        "--redirect",  # Automatically redirect HTTP to HTTPS
    ])

    if dry_run:
        cmd.append("--dry-run")

    result = run_cmd(cmd, timeout=120)
    if result.success:
        if dry_run:
            success(f"SSL dry-run successful for {domain}")
        else:
            success(f"SSL certificate obtained for {domain}")
        return True
    else:
        error(f"Failed to obtain SSL certificate: {result.stderr.strip()[:300]}")
        if "too many" in result.stderr.lower():
            warning("Rate limit reached. Try again later or use staging.")
        return False


def setup_auto_renewal() -> bool:
    """Set up automatic certificate renewal via systemd timer.

    Returns:
        True if auto-renewal is configured.
    """
    step("Setting up auto-renewal...")

    # Certbot usually sets up its own timer on install, check if it exists
    result = run_cmd(["sudo", "systemctl", "is-enabled", "certbot.timer"])
    if result.success:
        success("Certbot auto-renewal timer already active")
        return True

    # Try to enable the timer
    result = run_cmd(["sudo", "systemctl", "enable", "--now", "certbot.timer"])
    if result.success:
        success("Certbot auto-renewal timer enabled")
        return True

    # Fallback: create a cron job
    warning("Could not enable certbot timer, setting up cron renewal")
    result = run_cmd([
        "sudo", "bash", "-c",
        "echo '0 3 * * * root certbot renew --quiet --deploy-hook \"systemctl reload nginx\"' "
        "> /etc/cron.d/certbot-renew"
    ])
    if result.success:
        success("Certbot cron renewal configured")
        return True

    error("Failed to set up auto-renewal")
    return False


def check_certificate(domain: str) -> bool:
    """Check if a valid certificate exists for a domain.

    Args:
        domain: Domain to check.

    Returns:
        True if a valid certificate exists.
    """
    result = run_cmd([
        "sudo", "certbot", "certificates", "--domain", domain
    ])
    return result.success and "Certificate Name" in result.stdout


def revoke_certificate(domain: str) -> bool:
    """Revoke and delete a certificate for a domain.

    Args:
        domain: Domain whose certificate to revoke.

    Returns:
        True if revoked successfully.
    """
    result = run_cmd([
        "sudo", "certbot", "revoke",
        "--cert-name", domain,
        "--non-interactive",
        "--delete-after-revoke",
    ])
    return result.success
