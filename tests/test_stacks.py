"""Tests for stack registration and service detection."""

import json
from pathlib import Path

import pytest

from deploycraft.stacks.base import (
    StackType,
    get_available_stacks,
    get_stack_class,
    STACK_CHOICES,
)


class TestStackRegistration:
    def test_all_stacks_registered(self):
        """All 6 stacks should be registered after importing."""
        # Import triggers registration
        import deploycraft.stacks  # noqa: F401

        available = get_available_stacks()
        assert len(available) == 6

    def test_django_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.DJANGO)
        assert stack_class is not None
        assert stack_class.__name__ == "DjangoStack"

    def test_fastapi_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.FASTAPI)
        assert stack_class is not None
        assert stack_class.__name__ == "FastAPIStack"

    def test_nextjs_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.NEXTJS)
        assert stack_class is not None
        assert stack_class.__name__ == "NextJSStack"

    def test_react_vite_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.REACT_VITE)
        assert stack_class is not None
        assert stack_class.__name__ == "ReactViteStack"

    def test_react_cra_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.REACT)
        assert stack_class is not None
        assert stack_class.__name__ == "ReactCRAStack"

    def test_html_registered(self):
        import deploycraft.stacks  # noqa: F401
        stack_class = get_stack_class(StackType.HTML)
        assert stack_class is not None
        assert stack_class.__name__ == "HTMLStack"

    def test_stack_choices_count(self):
        assert len(STACK_CHOICES) == 6

    def test_stack_choices_have_descriptions(self):
        for stack_type, name, desc in STACK_CHOICES:
            assert isinstance(stack_type, StackType)
            assert len(name) > 0
            assert len(desc) > 0


class TestDjangoDetection:
    """Test Django stack's service detection logic."""

    @pytest.fixture
    def django_project(self, tmp_path):
        """Create a mock Django project."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text(
            "Django==4.2\n"
            "gunicorn==21.2.0\n"
            "psycopg2-binary==2.9.9\n"
            "redis==5.0.0\n"
            "celery==5.3.0\n"
            "django-celery-beat==2.5.0\n"
        )
        return tmp_path

    @pytest.fixture
    def minimal_django(self, tmp_path):
        """Create a minimal Django project (no extras)."""
        requirements = tmp_path / "requirements.txt"
        requirements.write_text("Django==4.2\ngunicorn==21.2.0\n")
        return tmp_path

    def test_detects_postgresql(self, django_project):
        from deploycraft.stacks.django import DjangoStack
        from deploycraft.stacks.base import StackContext
        from deploycraft.config import ProjectConfig
        from deploycraft.os_detect import OSInfo, PackageManager, Distro, PackageManagerType

        os_info = OSInfo(Distro.UBUNTU, "22.04", "jammy", "x86_64", PackageManagerType.APT, True)
        project = ProjectConfig(name="test", stack="django", base_path="/tmp", git_url="x")
        ctx = StackContext(
            project_config=project,
            os_info=os_info,
            package_manager=PackageManager(os_info),
            release_path=django_project,
            shared_path=django_project / "shared",
            env_file_path=django_project / ".env",
        )
        stack = DjangoStack(ctx)
        detected = stack.detect_services(django_project)

        assert detected.needs_postgresql is True
        assert detected.needs_redis is True
        assert detected.needs_celery is True
        assert detected.needs_celery_beat is True
        assert detected.needs_nginx is True

    def test_minimal_no_extras(self, minimal_django):
        from deploycraft.stacks.django import DjangoStack
        from deploycraft.stacks.base import StackContext
        from deploycraft.config import ProjectConfig
        from deploycraft.os_detect import OSInfo, PackageManager, Distro, PackageManagerType

        os_info = OSInfo(Distro.UBUNTU, "22.04", "jammy", "x86_64", PackageManagerType.APT, True)
        project = ProjectConfig(name="test", stack="django", base_path="/tmp", git_url="x")
        ctx = StackContext(
            project_config=project,
            os_info=os_info,
            package_manager=PackageManager(os_info),
            release_path=minimal_django,
            shared_path=minimal_django / "shared",
            env_file_path=minimal_django / ".env",
        )
        stack = DjangoStack(ctx)
        detected = stack.detect_services(minimal_django)

        assert detected.needs_postgresql is False
        assert detected.needs_redis is False
        assert detected.needs_celery is False


class TestNextJSDetection:
    """Test Next.js stack's service detection logic."""

    @pytest.fixture
    def nextjs_project(self, tmp_path):
        """Create a mock Next.js project with PostgreSQL."""
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({
            "name": "my-nextjs-app",
            "dependencies": {
                "next": "14.0.0",
                "react": "18.2.0",
                "@prisma/client": "5.0.0",
                "ioredis": "5.3.0",
            },
        }))
        return tmp_path

    def test_detects_nodejs_and_pm2(self, nextjs_project):
        from deploycraft.stacks.nextjs import NextJSStack
        from deploycraft.stacks.base import StackContext
        from deploycraft.config import ProjectConfig
        from deploycraft.os_detect import OSInfo, PackageManager, Distro, PackageManagerType

        os_info = OSInfo(Distro.UBUNTU, "22.04", "jammy", "x86_64", PackageManagerType.APT, True)
        project = ProjectConfig(name="test", stack="nextjs", base_path="/tmp", git_url="x")
        ctx = StackContext(
            project_config=project,
            os_info=os_info,
            package_manager=PackageManager(os_info),
            release_path=nextjs_project,
            shared_path=nextjs_project / "shared",
            env_file_path=nextjs_project / ".env",
        )
        stack = NextJSStack(ctx)
        detected = stack.detect_services(nextjs_project)

        assert detected.needs_nodejs is True
        assert detected.needs_pm2 is True
        assert detected.needs_nginx is True
        assert detected.needs_postgresql is True
        assert detected.needs_redis is True


class TestHTMLDetection:
    """Test HTML stack's service detection logic."""

    def test_only_needs_nginx(self, tmp_path):
        from deploycraft.stacks.html import HTMLStack
        from deploycraft.stacks.base import StackContext
        from deploycraft.config import ProjectConfig
        from deploycraft.os_detect import OSInfo, PackageManager, Distro, PackageManagerType

        os_info = OSInfo(Distro.UBUNTU, "22.04", "jammy", "x86_64", PackageManagerType.APT, True)
        project = ProjectConfig(name="test", stack="html", base_path="/tmp", git_url="x")
        ctx = StackContext(
            project_config=project,
            os_info=os_info,
            package_manager=PackageManager(os_info),
            release_path=tmp_path,
            shared_path=tmp_path / "shared",
            env_file_path=tmp_path / ".env",
        )
        stack = HTMLStack(ctx)
        detected = stack.detect_services(tmp_path)

        assert detected.needs_nginx is True
        assert detected.needs_postgresql is False
        assert detected.needs_redis is False
        assert detected.needs_nodejs is False
        assert detected.needs_pm2 is False
