"""Tests for deploycraft.config module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from deploycraft.config import (
    GlobalConfig,
    ProjectConfig,
    SMTPConfig,
    load_global_config,
    load_project_config,
    save_global_config,
    save_project_config,
    get_all_projects,
    delete_project_config,
)


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Override config directory to temp path."""
    with patch("deploycraft.config.get_config_dir", return_value=tmp_path):
        with patch("deploycraft.config.get_projects_dir", return_value=tmp_path / "projects"):
            (tmp_path / "projects").mkdir()
            yield tmp_path


class TestGlobalConfig:
    def test_default_config(self):
        config = GlobalConfig()
        assert config.admin_email == ""
        assert config.default_base_path == "/var/www"
        assert config.max_releases == 5
        assert config.monitor_interval_minutes == 5
        assert config.cpu_warning_threshold == 80
        assert config.cpu_critical_threshold == 90
        assert config.initialized is False

    def test_save_and_load(self, tmp_config_dir):
        config = GlobalConfig(
            admin_email="test@example.com",
            default_base_path="/opt/apps",
            max_releases=10,
            initialized=True,
            smtp=SMTPConfig(host="smtp.gmail.com", port=587),
        )
        save_global_config(config)

        # Verify file exists
        config_file = tmp_config_dir / "config.json"
        assert config_file.exists()

        # Load and verify
        loaded = load_global_config()
        assert loaded.admin_email == "test@example.com"
        assert loaded.default_base_path == "/opt/apps"
        assert loaded.max_releases == 10
        assert loaded.initialized is True
        assert loaded.smtp.host == "smtp.gmail.com"
        assert loaded.smtp.port == 587

    def test_load_missing_file(self, tmp_config_dir):
        config = load_global_config()
        assert config.admin_email == ""
        assert config.initialized is False


class TestProjectConfig:
    def test_create_project_config(self):
        config = ProjectConfig(
            name="myproject",
            stack="django",
            base_path="/var/www/myproject",
            git_url="https://github.com/user/repo.git",
            branch="main",
            domain="myproject.com",
        )
        assert config.name == "myproject"
        assert config.stack == "django"
        assert config.releases == []
        assert config.services == []

    def test_save_and_load_project(self, tmp_config_dir):
        config = ProjectConfig(
            name="testapp",
            stack="fastapi",
            base_path="/var/www/testapp",
            git_url="https://github.com/user/testapp.git",
            branch="develop",
            domain="testapp.io",
            services=["postgresql", "redis"],
            db_name="testapp_db",
            db_user="testapp_user",
        )
        save_project_config(config)

        loaded = load_project_config("testapp")
        assert loaded is not None
        assert loaded.name == "testapp"
        assert loaded.stack == "fastapi"
        assert loaded.branch == "develop"
        assert "postgresql" in loaded.services
        assert "redis" in loaded.services
        assert loaded.db_name == "testapp_db"

    def test_load_missing_project(self, tmp_config_dir):
        loaded = load_project_config("nonexistent")
        assert loaded is None

    def test_delete_project(self, tmp_config_dir):
        config = ProjectConfig(
            name="todelete",
            stack="html",
            base_path="/var/www/todelete",
            git_url="https://github.com/user/todelete.git",
        )
        save_project_config(config)
        assert load_project_config("todelete") is not None

        result = delete_project_config("todelete")
        assert result is True
        assert load_project_config("todelete") is None

    def test_delete_nonexistent(self, tmp_config_dir):
        result = delete_project_config("nonexistent")
        assert result is False

    def test_get_all_projects(self, tmp_config_dir):
        for name in ["alpha", "beta", "gamma"]:
            save_project_config(ProjectConfig(
                name=name,
                stack="django",
                base_path=f"/var/www/{name}",
                git_url=f"https://github.com/user/{name}.git",
            ))

        projects = get_all_projects()
        assert len(projects) == 3
        names = [p.name for p in projects]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
