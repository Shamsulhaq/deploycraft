"""Tests for deploycraft.deploy.rollback module (git commit-based)."""

import subprocess
from pathlib import Path

import pytest

from deploycraft.deploy.rollback import (
    get_current_commit,
    get_current_commit_short,
    get_commit_log,
    get_project_path,
    checkout_commit,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a mock git repository with multiple commits."""
    repo = tmp_path / "myproject"
    repo.mkdir()

    # Init repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)

    # First commit
    (repo / "file1.txt").write_text("version 1")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True)

    # Second commit
    (repo / "file1.txt").write_text("version 2")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Second update"], cwd=repo, capture_output=True)

    # Third commit
    (repo / "file1.txt").write_text("version 3")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Third update"], cwd=repo, capture_output=True)

    return repo


class TestGetProjectPath:
    def test_returns_path(self):
        path = get_project_path("/var/www/myproject")
        assert path == Path("/var/www/myproject")


class TestGetCurrentCommit:
    def test_returns_commit_hash(self, git_repo):
        commit = get_current_commit(git_repo)
        assert commit is not None
        assert len(commit) == 40  # Full SHA

    def test_returns_none_for_non_git(self, tmp_path):
        commit = get_current_commit(tmp_path)
        assert commit is None


class TestGetCurrentCommitShort:
    def test_returns_short_hash(self, git_repo):
        short = get_current_commit_short(git_repo)
        assert short is not None
        assert len(short) >= 7


class TestGetCommitLog:
    def test_returns_commits(self, git_repo):
        commits = get_commit_log(git_repo, count=10)
        assert len(commits) == 3
        assert commits[0]["message"] == "Third update"
        assert commits[1]["message"] == "Second update"
        assert commits[2]["message"] == "Initial commit"

    def test_each_commit_has_fields(self, git_repo):
        commits = get_commit_log(git_repo)
        for commit in commits:
            assert "hash" in commit
            assert "short_hash" in commit
            assert "message" in commit
            assert "date" in commit
            assert len(commit["hash"]) == 40

    def test_respects_count(self, git_repo):
        commits = get_commit_log(git_repo, count=2)
        assert len(commits) == 2

    def test_empty_for_non_git(self, tmp_path):
        commits = get_commit_log(tmp_path)
        assert commits == []


class TestCheckoutCommit:
    def test_checkout_previous(self, git_repo):
        commits = get_commit_log(git_repo)
        previous = commits[1]["hash"]

        result = checkout_commit(git_repo, previous)
        assert result is True

        # Verify we're on that commit
        current = get_current_commit(git_repo)
        assert current == previous

        # Verify file content matches
        content = (git_repo / "file1.txt").read_text()
        assert content == "version 2"

    def test_checkout_first_commit(self, git_repo):
        commits = get_commit_log(git_repo)
        first = commits[2]["hash"]

        result = checkout_commit(git_repo, first)
        assert result is True

        content = (git_repo / "file1.txt").read_text()
        assert content == "version 1"

    def test_checkout_invalid_hash(self, git_repo):
        result = checkout_commit(git_repo, "0000000000000000000000000000000000000000")
        assert result is False
