"""OS detection and package manager abstraction.

Detects the Linux distribution and provides a unified interface
for package management operations across different distros.
"""

import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rich.console import Console

console = Console()


class Distro(Enum):
    """Supported Linux distributions."""

    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    CENTOS = "centos"
    RHEL = "rhel"
    FEDORA = "fedora"
    AMAZON_LINUX = "amzn"
    UNKNOWN = "unknown"


class PackageManagerType(Enum):
    """Supported package managers."""

    APT = "apt"
    DNF = "dnf"
    YUM = "yum"


@dataclass
class OSInfo:
    """Detected operating system information."""

    distro: Distro
    version: str
    codename: str
    arch: str
    package_manager: PackageManagerType
    is_supported: bool
    pretty_name: str = ""

    @property
    def is_debian_based(self) -> bool:
        return self.distro in (Distro.UBUNTU, Distro.DEBIAN)

    @property
    def is_rhel_based(self) -> bool:
        return self.distro in (Distro.CENTOS, Distro.RHEL, Distro.FEDORA, Distro.AMAZON_LINUX)


def detect_os() -> OSInfo:
    """Detect the current operating system and return OS information.

    Reads /etc/os-release to determine the Linux distribution,
    version, and appropriate package manager.

    Returns:
        OSInfo with all detected system details.

    Raises:
        SystemExit: If the OS is not Linux or not a supported distribution.
    """
    system = platform.system()
    if system != "Linux":
        console.print(
            f"[red]Error:[/red] DeployCraft requires Linux. Detected: {system}",
        )
        raise SystemExit(1)

    arch = platform.machine()
    os_release = _parse_os_release()

    distro_id = os_release.get("ID", "").lower()
    version_id = os_release.get("VERSION_ID", "").strip('"')
    codename = os_release.get("VERSION_CODENAME", "").strip('"')
    pretty_name = os_release.get("PRETTY_NAME", "").strip('"')

    # Also check ID_LIKE for derivatives
    id_like = os_release.get("ID_LIKE", "").lower()

    distro = _map_distro(distro_id, id_like)
    pkg_manager = _detect_package_manager(distro)
    is_supported = distro != Distro.UNKNOWN

    return OSInfo(
        distro=distro,
        version=version_id,
        codename=codename,
        arch=arch,
        package_manager=pkg_manager,
        is_supported=is_supported,
        pretty_name=pretty_name,
    )


def _parse_os_release() -> dict[str, str]:
    """Parse /etc/os-release into a dictionary."""
    os_release_path = Path("/etc/os-release")
    if not os_release_path.exists():
        return {}

    result = {}
    for line in os_release_path.read_text().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip('"')
    return result


def _map_distro(distro_id: str, id_like: str) -> Distro:
    """Map distro ID to our Distro enum."""
    mapping = {
        "ubuntu": Distro.UBUNTU,
        "debian": Distro.DEBIAN,
        "centos": Distro.CENTOS,
        "rhel": Distro.RHEL,
        "fedora": Distro.FEDORA,
        "amzn": Distro.AMAZON_LINUX,
    }

    if distro_id in mapping:
        return mapping[distro_id]

    # Check ID_LIKE for derivatives (e.g., Linux Mint → ubuntu → debian)
    for like_id in id_like.split():
        if like_id in mapping:
            return mapping[like_id]

    return Distro.UNKNOWN


def _detect_package_manager(distro: Distro) -> PackageManagerType:
    """Determine the package manager for the given distribution."""
    if distro in (Distro.UBUNTU, Distro.DEBIAN):
        return PackageManagerType.APT
    if distro in (Distro.FEDORA, Distro.CENTOS, Distro.RHEL, Distro.AMAZON_LINUX):
        # CentOS 8+, RHEL 8+, Fedora all use dnf; fall back to yum
        if shutil.which("dnf"):
            return PackageManagerType.DNF
        return PackageManagerType.YUM
    # Fallback: check what's available
    if shutil.which("apt-get"):
        return PackageManagerType.APT
    if shutil.which("dnf"):
        return PackageManagerType.DNF
    if shutil.which("yum"):
        return PackageManagerType.YUM
    return PackageManagerType.APT  # Default assumption


class PackageManager:
    """Unified package manager interface.

    Provides consistent methods for installing packages, updating repos,
    and checking if packages are installed, regardless of the underlying
    package manager (apt, dnf, yum).
    """

    # Package name mappings: canonical name → {apt: name, dnf: name}
    PACKAGE_MAP: dict[str, dict[str, str]] = {
        "nginx": {"apt": "nginx", "dnf": "nginx", "yum": "nginx"},
        "postgresql": {
            "apt": "postgresql postgresql-contrib",
            "dnf": "postgresql-server postgresql-contrib",
            "yum": "postgresql-server postgresql-contrib",
        },
        "redis": {"apt": "redis-server", "dnf": "redis", "yum": "redis"},
        "certbot": {"apt": "certbot", "dnf": "certbot", "yum": "certbot"},
        "certbot-nginx": {
            "apt": "python3-certbot-nginx",
            "dnf": "python3-certbot-nginx",
            "yum": "python3-certbot-nginx",
        },
        "python3-venv": {
            "apt": "python3-venv",
            "dnf": "python3-virtualenv",
            "yum": "python3-virtualenv",
        },
        "python3-dev": {
            "apt": "python3-dev build-essential",
            "dnf": "python3-devel gcc",
            "yum": "python3-devel gcc",
        },
        "git": {"apt": "git", "dnf": "git", "yum": "git"},
        "curl": {"apt": "curl", "dnf": "curl", "yum": "curl"},
        "supervisor": {"apt": "supervisor", "dnf": "supervisor", "yum": "supervisor"},
    }

    def __init__(self, os_info: OSInfo) -> None:
        self.os_info = os_info
        self.pkg_type = os_info.package_manager

    def _get_pkg_cmd(self) -> str:
        """Get the package manager command."""
        return self.pkg_type.value  # "apt", "dnf", or "yum"

    def resolve_package(self, canonical_name: str) -> str:
        """Resolve a canonical package name to the distro-specific name(s).

        Args:
            canonical_name: The canonical package name (e.g., "postgresql").

        Returns:
            The distro-specific package name(s) as a string.
        """
        if canonical_name in self.PACKAGE_MAP:
            pkg_key = "apt" if self.pkg_type == PackageManagerType.APT else self.pkg_type.value
            return self.PACKAGE_MAP[canonical_name].get(pkg_key, canonical_name)
        return canonical_name

    def update_cmd(self) -> list[str]:
        """Get the command to update package repositories."""
        if self.pkg_type == PackageManagerType.APT:
            return ["sudo", "apt-get", "update", "-y"]
        elif self.pkg_type == PackageManagerType.DNF:
            return ["sudo", "dnf", "makecache", "-y"]
        else:
            return ["sudo", "yum", "makecache", "-y"]

    def install_cmd(self, *packages: str) -> list[str]:
        """Get the command to install packages.

        Args:
            packages: Canonical package names to install.

        Returns:
            Full command list ready for subprocess.
        """
        resolved = []
        for pkg in packages:
            resolved.extend(self.resolve_package(pkg).split())

        if self.pkg_type == PackageManagerType.APT:
            return ["sudo", "apt-get", "install", "-y"] + resolved
        elif self.pkg_type == PackageManagerType.DNF:
            return ["sudo", "dnf", "install", "-y"] + resolved
        else:
            return ["sudo", "yum", "install", "-y"] + resolved

    def is_installed(self, package: str) -> bool:
        """Check if a package is installed.

        Args:
            package: Package name to check.

        Returns:
            True if the package is installed.
        """
        try:
            if self.pkg_type == PackageManagerType.APT:
                result = subprocess.run(
                    ["dpkg", "-s", package],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0
            else:
                result = subprocess.run(
                    ["rpm", "-q", package],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0
        except FileNotFoundError:
            return False

    def enable_service_cmd(self, service: str) -> list[str]:
        """Get command to enable and start a systemd service."""
        return ["sudo", "systemctl", "enable", "--now", service]

    def restart_service_cmd(self, service: str) -> list[str]:
        """Get command to restart a systemd service."""
        return ["sudo", "systemctl", "restart", service]

    def service_status_cmd(self, service: str) -> list[str]:
        """Get command to check systemd service status."""
        return ["sudo", "systemctl", "is-active", service]


def ensure_supported_os() -> tuple[OSInfo, PackageManager]:
    """Detect OS and return info + package manager, or exit if unsupported.

    Returns:
        Tuple of (OSInfo, PackageManager) ready to use.

    Raises:
        SystemExit: If OS is not supported.
    """
    os_info = detect_os()
    if not os_info.is_supported:
        console.print(
            f"[red]Error:[/red] Unsupported Linux distribution: {os_info.pretty_name}",
        )
        console.print("Supported: Ubuntu, Debian, CentOS, RHEL, Fedora, Amazon Linux")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Detected: {os_info.pretty_name} ({os_info.arch})")
    return os_info, PackageManager(os_info)
