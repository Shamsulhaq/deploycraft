"""Tests for deploycraft.os_detect module."""

from unittest.mock import patch, MagicMock

import pytest

from deploycraft.os_detect import (
    Distro,
    OSInfo,
    PackageManager,
    PackageManagerType,
    _map_distro,
    _detect_package_manager,
)


class TestDistroMapping:
    def test_ubuntu(self):
        assert _map_distro("ubuntu", "") == Distro.UBUNTU

    def test_debian(self):
        assert _map_distro("debian", "") == Distro.DEBIAN

    def test_centos(self):
        assert _map_distro("centos", "") == Distro.CENTOS

    def test_rhel(self):
        assert _map_distro("rhel", "") == Distro.RHEL

    def test_fedora(self):
        assert _map_distro("fedora", "") == Distro.FEDORA

    def test_amazon_linux(self):
        assert _map_distro("amzn", "") == Distro.AMAZON_LINUX

    def test_unknown(self):
        assert _map_distro("archlinux", "") == Distro.UNKNOWN

    def test_derivative_via_id_like(self):
        # Linux Mint reports ID_LIKE as "ubuntu debian"
        assert _map_distro("linuxmint", "ubuntu debian") == Distro.UBUNTU

    def test_rocky_via_id_like(self):
        # Rocky Linux reports ID_LIKE as "rhel centos fedora"
        assert _map_distro("rocky", "rhel centos fedora") == Distro.RHEL


class TestPackageManagerDetection:
    def test_ubuntu_uses_apt(self):
        assert _detect_package_manager(Distro.UBUNTU) == PackageManagerType.APT

    def test_debian_uses_apt(self):
        assert _detect_package_manager(Distro.DEBIAN) == PackageManagerType.APT

    @patch("shutil.which", return_value="/usr/bin/dnf")
    def test_centos_with_dnf(self, mock_which):
        assert _detect_package_manager(Distro.CENTOS) == PackageManagerType.DNF

    @patch("shutil.which", return_value=None)
    def test_centos_fallback_yum(self, mock_which):
        assert _detect_package_manager(Distro.CENTOS) == PackageManagerType.YUM


class TestOSInfo:
    def test_debian_based(self):
        info = OSInfo(
            distro=Distro.UBUNTU,
            version="22.04",
            codename="jammy",
            arch="x86_64",
            package_manager=PackageManagerType.APT,
            is_supported=True,
            pretty_name="Ubuntu 22.04.3 LTS",
        )
        assert info.is_debian_based is True
        assert info.is_rhel_based is False

    def test_rhel_based(self):
        info = OSInfo(
            distro=Distro.CENTOS,
            version="9",
            codename="",
            arch="x86_64",
            package_manager=PackageManagerType.DNF,
            is_supported=True,
            pretty_name="CentOS Stream 9",
        )
        assert info.is_debian_based is False
        assert info.is_rhel_based is True


class TestPackageManager:
    @pytest.fixture
    def ubuntu_pkg_manager(self):
        os_info = OSInfo(
            distro=Distro.UBUNTU,
            version="22.04",
            codename="jammy",
            arch="x86_64",
            package_manager=PackageManagerType.APT,
            is_supported=True,
        )
        return PackageManager(os_info)

    @pytest.fixture
    def centos_pkg_manager(self):
        os_info = OSInfo(
            distro=Distro.CENTOS,
            version="9",
            codename="",
            arch="x86_64",
            package_manager=PackageManagerType.DNF,
            is_supported=True,
        )
        return PackageManager(os_info)

    def test_update_cmd_apt(self, ubuntu_pkg_manager):
        cmd = ubuntu_pkg_manager.update_cmd()
        assert cmd == ["sudo", "apt-get", "update", "-y"]

    def test_update_cmd_dnf(self, centos_pkg_manager):
        cmd = centos_pkg_manager.update_cmd()
        assert cmd == ["sudo", "dnf", "makecache", "-y"]

    def test_install_cmd_apt(self, ubuntu_pkg_manager):
        cmd = ubuntu_pkg_manager.install_cmd("nginx")
        assert cmd == ["sudo", "apt-get", "install", "-y", "nginx"]

    def test_install_cmd_dnf(self, centos_pkg_manager):
        cmd = centos_pkg_manager.install_cmd("nginx")
        assert cmd == ["sudo", "dnf", "install", "-y", "nginx"]

    def test_resolve_postgresql_apt(self, ubuntu_pkg_manager):
        resolved = ubuntu_pkg_manager.resolve_package("postgresql")
        assert "postgresql" in resolved
        assert "postgresql-contrib" in resolved

    def test_resolve_redis_apt(self, ubuntu_pkg_manager):
        resolved = ubuntu_pkg_manager.resolve_package("redis")
        assert resolved == "redis-server"

    def test_resolve_redis_dnf(self, centos_pkg_manager):
        resolved = centos_pkg_manager.resolve_package("redis")
        assert resolved == "redis"

    def test_resolve_unknown_package(self, ubuntu_pkg_manager):
        resolved = ubuntu_pkg_manager.resolve_package("some-custom-package")
        assert resolved == "some-custom-package"

    def test_enable_service_cmd(self, ubuntu_pkg_manager):
        cmd = ubuntu_pkg_manager.enable_service_cmd("nginx")
        assert cmd == ["sudo", "systemctl", "enable", "--now", "nginx"]

    def test_restart_service_cmd(self, ubuntu_pkg_manager):
        cmd = ubuntu_pkg_manager.restart_service_cmd("nginx")
        assert cmd == ["sudo", "systemctl", "restart", "nginx"]
