"""Tests for deploycraft.deploy.rollback module."""

from pathlib import Path

import pytest

from deploycraft.deploy.rollback import (
    create_release_dir,
    set_current_symlink,
    get_current_release,
    get_previous_release,
    list_releases,
    prune_old_releases,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a mock project directory structure."""
    releases_dir = tmp_path / "releases"
    releases_dir.mkdir()
    return tmp_path


class TestCreateReleaseDir:
    def test_creates_directory(self, project_dir):
        release = create_release_dir(str(project_dir), "20260721_140000")
        assert release.exists()
        assert release.is_dir()
        assert release.name == "20260721_140000"

    def test_creates_under_releases(self, project_dir):
        release = create_release_dir(str(project_dir), "20260721_150000")
        assert release.parent.name == "releases"

    def test_idempotent(self, project_dir):
        release1 = create_release_dir(str(project_dir), "20260721_140000")
        release2 = create_release_dir(str(project_dir), "20260721_140000")
        assert release1 == release2


class TestSetCurrentSymlink:
    def test_creates_symlink(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        result = set_current_symlink(str(project_dir), "20260721_140000")

        assert result is True
        current = project_dir / "current"
        assert current.is_symlink()
        assert current.resolve().name == "20260721_140000"

    def test_switches_symlink(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        create_release_dir(str(project_dir), "20260721_150000")

        set_current_symlink(str(project_dir), "20260721_140000")
        set_current_symlink(str(project_dir), "20260721_150000")

        current = project_dir / "current"
        assert current.resolve().name == "20260721_150000"

    def test_fails_for_nonexistent_release(self, project_dir):
        result = set_current_symlink(str(project_dir), "nonexistent")
        assert result is False


class TestGetCurrentRelease:
    def test_returns_current(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        set_current_symlink(str(project_dir), "20260721_140000")

        assert get_current_release(str(project_dir)) == "20260721_140000"

    def test_returns_none_when_no_symlink(self, project_dir):
        assert get_current_release(str(project_dir)) is None


class TestGetPreviousRelease:
    def test_returns_previous(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        create_release_dir(str(project_dir), "20260721_150000")
        set_current_symlink(str(project_dir), "20260721_150000")

        assert get_previous_release(str(project_dir)) == "20260721_140000"

    def test_returns_none_when_only_one_release(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        set_current_symlink(str(project_dir), "20260721_140000")

        assert get_previous_release(str(project_dir)) is None

    def test_returns_none_when_no_releases(self, project_dir):
        assert get_previous_release(str(project_dir)) is None


class TestListReleases:
    def test_lists_in_order(self, project_dir):
        for ts in ["20260721_160000", "20260721_140000", "20260721_150000"]:
            create_release_dir(str(project_dir), ts)

        releases = list_releases(str(project_dir))
        assert releases == ["20260721_140000", "20260721_150000", "20260721_160000"]

    def test_empty_when_no_releases(self, project_dir):
        releases = list_releases(str(project_dir))
        assert releases == []

    def test_ignores_hidden_dirs(self, project_dir):
        create_release_dir(str(project_dir), "20260721_140000")
        (project_dir / "releases" / ".hidden").mkdir()

        releases = list_releases(str(project_dir))
        assert releases == ["20260721_140000"]


class TestPruneOldReleases:
    def test_prunes_oldest(self, project_dir):
        timestamps = [
            "20260721_100000",
            "20260721_110000",
            "20260721_120000",
            "20260721_130000",
            "20260721_140000",
            "20260721_150000",
            "20260721_160000",
        ]
        for ts in timestamps:
            create_release_dir(str(project_dir), ts)

        # Set current to latest
        set_current_symlink(str(project_dir), "20260721_160000")

        # Keep only 3
        prune_old_releases(str(project_dir), max_releases=3)

        remaining = list_releases(str(project_dir))
        assert len(remaining) <= 3
        # Latest should still be there
        assert "20260721_160000" in remaining

    def test_no_prune_when_under_limit(self, project_dir):
        for ts in ["20260721_140000", "20260721_150000"]:
            create_release_dir(str(project_dir), ts)

        prune_old_releases(str(project_dir), max_releases=5)

        remaining = list_releases(str(project_dir))
        assert len(remaining) == 2

    def test_never_prunes_current(self, project_dir):
        timestamps = [
            "20260721_100000",
            "20260721_110000",
            "20260721_120000",
            "20260721_130000",
        ]
        for ts in timestamps:
            create_release_dir(str(project_dir), ts)

        # Set current to the OLDEST (unusual but should be protected)
        set_current_symlink(str(project_dir), "20260721_100000")

        prune_old_releases(str(project_dir), max_releases=2)

        remaining = list_releases(str(project_dir))
        assert "20260721_100000" in remaining
