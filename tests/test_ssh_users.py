"""Tests for services/ssh.py and services/users.py."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─── SSH tests ───────────────────────────────────────────────────────────────

class TestSSHKeyPaths:
    def test_get_key_paths(self, tmp_path):
        from deploycraft.services.ssh import get_key_paths

        priv, pub = get_key_paths("mykey", ssh_dir=tmp_path)
        assert priv == tmp_path / "mykey"
        assert pub == tmp_path / "mykey.pub"

    def test_default_key_name(self, tmp_path):
        from deploycraft.services.ssh import get_key_paths, DEFAULT_KEY_NAME

        priv, pub = get_key_paths(ssh_dir=tmp_path)
        assert priv.name == DEFAULT_KEY_NAME
        assert pub.name == f"{DEFAULT_KEY_NAME}.pub"


class TestKeyExists:
    def test_returns_false_when_no_files(self, tmp_path):
        from deploycraft.services.ssh import key_exists

        assert key_exists(ssh_dir=tmp_path) is False

    def test_returns_false_when_only_private(self, tmp_path):
        from deploycraft.services.ssh import key_exists, DEFAULT_KEY_NAME

        (tmp_path / DEFAULT_KEY_NAME).write_text("private")
        assert key_exists(ssh_dir=tmp_path) is False

    def test_returns_true_when_both_exist(self, tmp_path):
        from deploycraft.services.ssh import key_exists, DEFAULT_KEY_NAME

        (tmp_path / DEFAULT_KEY_NAME).write_text("private")
        (tmp_path / f"{DEFAULT_KEY_NAME}.pub").write_text("ssh-rsa AAAA...")
        assert key_exists(ssh_dir=tmp_path) is True


class TestGetPublicKey:
    def test_returns_none_when_missing(self, tmp_path):
        from deploycraft.services.ssh import get_public_key

        assert get_public_key(ssh_dir=tmp_path) is None

    def test_returns_content_when_exists(self, tmp_path):
        from deploycraft.services.ssh import get_public_key, DEFAULT_KEY_NAME

        pub_content = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI deploycraft@server"
        (tmp_path / f"{DEFAULT_KEY_NAME}.pub").write_text(pub_content + "\n")
        assert get_public_key(ssh_dir=tmp_path) == pub_content


class TestGenerateKeypair:
    def test_generates_real_keypair(self, tmp_path):
        """Test actual key generation with ssh-keygen (requires ssh-keygen installed)."""
        from deploycraft.services.ssh import generate_keypair, DEFAULT_KEY_NAME

        pub_path = generate_keypair(ssh_dir=tmp_path)

        assert pub_path is not None
        assert pub_path.exists()
        assert (tmp_path / DEFAULT_KEY_NAME).exists()

        # Verify key format
        pub_content = pub_path.read_text()
        assert pub_content.startswith("ssh-rsa")

    def test_does_not_overwrite_without_force(self, tmp_path):
        from deploycraft.services.ssh import generate_keypair, DEFAULT_KEY_NAME

        # Create existing key
        priv = tmp_path / DEFAULT_KEY_NAME
        pub = tmp_path / f"{DEFAULT_KEY_NAME}.pub"
        priv.write_text("original-private")
        pub.write_text("original-public")

        result = generate_keypair(ssh_dir=tmp_path, force=False)

        # Should return existing pub key without regenerating
        assert pub.read_text() == "original-public"

    def test_overwrites_with_force(self, tmp_path):
        from deploycraft.services.ssh import generate_keypair, DEFAULT_KEY_NAME

        # Create existing key
        pub = tmp_path / f"{DEFAULT_KEY_NAME}.pub"
        pub.write_text("old-public")

        result = generate_keypair(ssh_dir=tmp_path, force=True)

        # Should have regenerated
        assert result is not None
        new_content = pub.read_text()
        assert new_content != "old-public"
        assert "ssh-rsa" in new_content


class TestEnsureKeypairExists:
    def test_creates_if_missing(self, tmp_path):
        from deploycraft.services.ssh import ensure_keypair_exists

        public_key = ensure_keypair_exists(ssh_dir=tmp_path)
        assert public_key is not None
        assert "ssh-rsa" in public_key

    def test_returns_existing_key(self, tmp_path):
        from deploycraft.services.ssh import ensure_keypair_exists, DEFAULT_KEY_NAME

        pub_content = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAA existing@key"
        priv = tmp_path / DEFAULT_KEY_NAME
        pub = tmp_path / f"{DEFAULT_KEY_NAME}.pub"
        priv.write_text("private")
        pub.write_text(pub_content)

        result = ensure_keypair_exists(ssh_dir=tmp_path)
        assert result == pub_content


# ─── User management tests ────────────────────────────────────────────────────

class TestIsValidUsername:
    def test_valid_simple(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("alice") is True

    def test_valid_with_numbers(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("alice123") is True

    def test_valid_with_hyphen(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("deploy-user") is True

    def test_valid_with_underscore(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("deploy_user") is True

    def test_invalid_starts_with_number(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("1alice") is False

    def test_invalid_empty(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("") is False

    def test_invalid_too_long(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("a" * 33) is False

    def test_invalid_special_chars(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("alice@domain") is False
        assert _is_valid_username("alice user") is False
        assert _is_valid_username("alice!") is False

    def test_max_length_exactly_32(self):
        from deploycraft.services.users import _is_valid_username
        assert _is_valid_username("a" * 32) is True


class TestUserExists:
    @patch("deploycraft.services.users.run_cmd")
    def test_user_exists_returns_true(self, mock_run):
        from deploycraft.services.users import user_exists
        from deploycraft.utils import CommandResult

        mock_run.return_value = CommandResult(0, "uid=1001(alice)", "", "id alice")
        assert user_exists("alice") is True

    @patch("deploycraft.services.users.run_cmd")
    def test_user_not_found_returns_false(self, mock_run):
        from deploycraft.services.users import user_exists
        from deploycraft.utils import CommandResult

        mock_run.return_value = CommandResult(1, "", "no such user", "id nobody")
        assert user_exists("nobody") is False


class TestCreateUser:
    @patch("deploycraft.services.users.run_cmd")
    @patch("deploycraft.services.users.set_user_password")
    @patch("deploycraft.services.users.user_exists")
    def test_creates_user_without_sudo(self, mock_exists, mock_set_pw, mock_run):
        from deploycraft.services.users import create_user
        from deploycraft.utils import CommandResult

        mock_exists.return_value = False
        mock_run.return_value = CommandResult(0, "", "", "useradd alice")
        mock_set_pw.return_value = True

        result = create_user("alice", "SecurePass123!", is_admin=False)
        assert result is True

    @patch("deploycraft.services.users.grant_sudo")
    @patch("deploycraft.services.users.run_cmd")
    @patch("deploycraft.services.users.set_user_password")
    @patch("deploycraft.services.users.user_exists")
    def test_creates_admin_user(self, mock_exists, mock_set_pw, mock_run, mock_grant):
        from deploycraft.services.users import create_user
        from deploycraft.utils import CommandResult

        mock_exists.return_value = False
        mock_run.return_value = CommandResult(0, "", "", "useradd bob")
        mock_set_pw.return_value = True
        mock_grant.return_value = True

        result = create_user("bob", "SecurePass123!", is_admin=True)
        assert result is True
        mock_grant.assert_called_once_with("bob")

    def test_rejects_invalid_username(self):
        from deploycraft.services.users import create_user

        result = create_user("1invalid", "password")
        assert result is False

    @patch("deploycraft.services.users.user_exists")
    def test_skips_if_already_exists(self, mock_exists):
        from deploycraft.services.users import create_user

        mock_exists.return_value = True
        result = create_user("existing", "password")
        assert result is True  # Not an error


class TestGrantRevokeSudo:
    @patch("deploycraft.services.users.run_cmd")
    def test_grant_sudo_success(self, mock_run):
        from deploycraft.services.users import grant_sudo
        from deploycraft.utils import CommandResult

        mock_run.return_value = CommandResult(0, "", "", "usermod -aG sudo alice")
        result = grant_sudo("alice")
        assert result is True

    @patch("deploycraft.services.users.run_cmd")
    def test_revoke_sudo(self, mock_run):
        from deploycraft.services.users import revoke_sudo
        from deploycraft.utils import CommandResult

        mock_run.return_value = CommandResult(0, "", "", "gpasswd -d alice sudo")
        result = revoke_sudo("alice")
        assert result is True


class TestListSudoUsers:
    @patch("deploycraft.services.users.run_cmd")
    def test_lists_users_from_sudo_group(self, mock_run):
        from deploycraft.services.users import list_sudo_users
        from deploycraft.utils import CommandResult

        def side_effect(cmd, **kwargs):
            if "sudo" in cmd:
                return CommandResult(0, "sudo:x:27:alice,bob", "", "getent group sudo")
            return CommandResult(1, "", "", "getent group wheel")

        mock_run.side_effect = side_effect
        users = list_sudo_users()
        assert "alice" in users
        assert "bob" in users

    @patch("deploycraft.services.users.run_cmd")
    def test_empty_when_no_sudo_group(self, mock_run):
        from deploycraft.services.users import list_sudo_users
        from deploycraft.utils import CommandResult

        mock_run.return_value = CommandResult(1, "", "", "getent group")
        users = list_sudo_users()
        assert users == []
