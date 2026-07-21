"""Tests for deploycraft.utils module."""

import tempfile
from pathlib import Path

import pytest

from deploycraft.utils import (
    CommandResult,
    generate_db_name,
    generate_db_user,
    generate_password,
    generate_secret_key,
    timestamp,
    human_timestamp,
    ensure_dir,
    write_file_secure,
    run_cmd,
)


class TestCommandResult:
    def test_success(self):
        result = CommandResult(returncode=0, stdout="ok", stderr="", command="echo ok")
        assert result.success is True

    def test_failure(self):
        result = CommandResult(returncode=1, stdout="", stderr="error", command="bad")
        assert result.success is False


class TestRunCmd:
    def test_successful_command(self):
        result = run_cmd(["echo", "hello"])
        assert result.success is True
        assert result.stdout.strip() == "hello"
        assert result.returncode == 0

    def test_failed_command(self):
        result = run_cmd(["false"])
        assert result.success is False
        assert result.returncode != 0

    def test_command_not_found(self):
        result = run_cmd(["nonexistent_command_xyz"])
        assert result.success is False
        assert result.returncode == -1
        assert "not found" in result.stderr.lower()

    def test_with_cwd(self, tmp_path):
        result = run_cmd(["pwd"], cwd=tmp_path)
        assert result.success is True
        assert str(tmp_path) in result.stdout

    def test_timeout(self):
        result = run_cmd(["sleep", "10"], timeout=1)
        assert result.success is False
        assert "timed out" in result.stderr.lower()


class TestPasswordGeneration:
    def test_password_length(self):
        pw = generate_password(24)
        assert len(pw) == 24

    def test_password_custom_length(self):
        pw = generate_password(12)
        assert len(pw) == 12

    def test_password_has_variety(self):
        pw = generate_password(24)
        has_upper = any(c.isupper() for c in pw)
        has_lower = any(c.islower() for c in pw)
        has_digit = any(c.isdigit() for c in pw)
        assert has_upper
        assert has_lower
        assert has_digit

    def test_passwords_are_unique(self):
        passwords = {generate_password(24) for _ in range(10)}
        assert len(passwords) == 10  # All should be different


class TestSecretKeyGeneration:
    def test_secret_key_length(self):
        key = generate_secret_key(50)
        assert len(key) == 50

    def test_secret_keys_are_unique(self):
        keys = {generate_secret_key() for _ in range(10)}
        assert len(keys) == 10


class TestDatabaseNameGeneration:
    def test_simple_name(self):
        assert generate_db_name("myproject") == "myproject"

    def test_dashes_to_underscores(self):
        assert generate_db_name("my-project") == "my_project"

    def test_spaces_to_underscores(self):
        assert generate_db_name("my project") == "my_project"

    def test_special_chars_removed(self):
        assert generate_db_name("my@project!") == "myproject"

    def test_starts_with_number(self):
        assert generate_db_name("123project").startswith("db_")

    def test_max_length(self):
        long_name = "a" * 100
        result = generate_db_name(long_name)
        assert len(result) <= 63

    def test_empty_name(self):
        result = generate_db_name("")
        assert result == "deploycraft_db"


class TestDatabaseUserGeneration:
    def test_simple_name(self):
        assert generate_db_user("myproject") == "myproject"

    def test_dashes_to_underscores(self):
        assert generate_db_user("my-app") == "my_app"

    def test_starts_with_number(self):
        assert generate_db_user("123app").startswith("u_")


class TestTimestamps:
    def test_timestamp_format(self):
        ts = timestamp()
        # Should be YYYYMMDD_HHMMSS format
        assert len(ts) == 15
        assert ts[8] == "_"
        assert ts[:8].isdigit()
        assert ts[9:].isdigit()

    def test_human_timestamp_format(self):
        ts = human_timestamp()
        # Should be YYYY-MM-DD HH:MM:SS format
        assert len(ts) == 19
        assert "-" in ts
        assert ":" in ts


class TestFileHelpers:
    def test_ensure_dir(self, tmp_path):
        new_dir = tmp_path / "a" / "b" / "c"
        result = ensure_dir(new_dir)
        assert result == new_dir
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_ensure_dir_already_exists(self, tmp_path):
        result = ensure_dir(tmp_path)
        assert result == tmp_path

    def test_write_file_secure(self, tmp_path):
        file_path = tmp_path / "secret.txt"
        write_file_secure(file_path, "sensitive data", mode=0o600)

        assert file_path.exists()
        assert file_path.read_text() == "sensitive data"
        # Check permissions
        mode = file_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_write_file_creates_parents(self, tmp_path):
        file_path = tmp_path / "deep" / "nested" / "file.txt"
        write_file_secure(file_path, "content")
        assert file_path.exists()
