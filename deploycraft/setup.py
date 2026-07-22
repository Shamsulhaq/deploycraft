"""Progressive deployment setup.

One command to fully deploy a project. Detects what's needed,
skips what's already done, walks through each step.

Usage:
    cd ~/websites/backend
    deploycraft setup

Supports same-domain routing (frontend at /, backend at /api/).
"""

import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt

from deploycraft.config import (
    ProjectConfig,
    get_all_projects,
    get_next_available_port,
    load_project_config,
    save_project_config,
)
from deploycraft.deploy.env_manager import (
    collect_env_vars_interactive,
    create_env_file,
    get_env_file_path,
    symlink_env_to_project,
)
from deploycraft.os_detect import ensure_supported_os
from deploycraft.services import nginx, node, pm2, postgres, redis, ssl, systemd
from deploycraft.stacks import StackType, get_stack_class
from deploycraft.stacks.base import StackContext
from deploycraft.utils import error, run_cmd, step, success, warning

console = Console()


def run_setup() -> None:
    """Run the progressive setup flow for the current directory."""
    cwd = Path(os.getcwd())
    project_name = cwd.name

    console.print(f"\n[bold cyan]DeployCraft Setup[/bold cyan] — {project_name}\n")

    # --- Step 1: Detect stack ---
    stack = _detect_stack(cwd)
    if not stack:
        error("Could not detect project type.")
        console.print("  Supported: Django, FastAPI, Next.js, React (Vite/CRA), Plain HTML")
        return

    console.print(f"  [green]✓[/green] Detected: [cyan]{stack}[/cyan]")
    stack_type = StackType(stack)

    # --- Step 2: Load or create project config ---
    project_config = load_project_config(project_name)
    if not project_config:
        project_config = ProjectConfig(
            name=project_name,
            stack=stack,
            base_path=str(cwd),
            git_url="",
        )

    # Assign port if needed
    if project_config.port == 0 and stack_type in (StackType.DJANGO, StackType.FASTAPI):
        project_config.port = get_next_available_port()

    save_project_config(project_config)

    # --- Step 3: OS check ---
    os_info, pkg_manager = ensure_supported_os()

    # --- Route based on stack type ---
    setup_ok = False
    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        setup_ok = _setup_python_backend(project_config, cwd, os_info, pkg_manager, stack_type)
    elif stack_type in (StackType.NEXTJS,):
        setup_ok = _setup_nextjs(project_config, cwd, os_info, pkg_manager)
    elif stack_type in (StackType.REACT_VITE, StackType.REACT, StackType.HTML):
        setup_ok = _setup_static_frontend(project_config, cwd, os_info, pkg_manager, stack_type)

    if not setup_ok:
        save_project_config(project_config)
        error("Setup failed. Fix the issue above and run 'deploycraft setup' again.")
        return

    # --- Final: Domain + Nginx + SSL ---
    _setup_nginx_and_ssl(project_config, cwd, stack_type, pkg_manager)

    # Save final config
    from deploycraft.utils import human_timestamp

    project_config.last_deployed = human_timestamp()
    project_config.created_at = project_config.created_at or human_timestamp()
    save_project_config(project_config)

    console.print(f"\n[bold green]✓ Setup complete! Project '{project_name}' is live.[/bold green]")
    if project_config.domain:
        protocol = "https" if Confirm.ask("Did you install SSL?", default=False) else "http"
        console.print(f"  [dim]URL: {protocol}://{project_config.domain}[/dim]")


# ─── Python Backend (Django/FastAPI) ──────────────────────────────────────────


def _setup_python_backend(
    config: ProjectConfig,
    project_path: Path,
    os_info,
    pkg_manager,
    stack_type: StackType,
) -> bool:
    """Setup a Python backend project progressively. Returns True on success."""
    venv_path = project_path / "venv"
    pip_path = venv_path / "bin" / "pip"
    python_path = venv_path / "bin" / "python"

    # --- Virtual environment ---
    if venv_path.exists() and pip_path.exists():
        console.print("  [green]✓[/green] Virtual environment — exists")
    else:
        step("Creating virtual environment...")
        result = run_cmd(["python3", "-m", "venv", str(venv_path)])
        if not result.success:
            error("Failed to create virtualenv")
            return
        success("Virtual environment created")

    # --- Install requirements ---
    step("Installing requirements...")
    req_file = project_path / "requirements.txt"
    if req_file.exists():
        run_cmd([str(pip_path), "install", "--upgrade", "pip", "setuptools", "wheel"], timeout=60)
        result = run_cmd([str(pip_path), "install", "-r", str(req_file)], timeout=300)
        if result.success:
            success("Requirements installed")
        else:
            error(f"Requirements failed: {result.stderr.strip()[:100]}")
            return
    elif (project_path / "pyproject.toml").exists():
        run_cmd([str(pip_path), "install", "."], cwd=project_path, timeout=300)
        success("Requirements installed (from pyproject.toml)")
    else:
        warning("No requirements.txt or pyproject.toml found")

    # Install gunicorn/uvicorn
    if stack_type == StackType.DJANGO:
        run_cmd([str(pip_path), "install", "gunicorn"])
        console.print("  [green]✓[/green] Gunicorn installed")
    else:
        run_cmd([str(pip_path), "install", "uvicorn[standard]"])
        console.print("  [green]✓[/green] Uvicorn installed")

    # --- Detect and install services ---
    stack_class = get_stack_class(stack_type)
    env_file_path = get_env_file_path(config.name)
    context = StackContext(
        project_config=config,
        os_info=os_info,
        package_manager=pkg_manager,
        project_path=project_path,
        shared_path=project_path / "shared",
        env_file_path=env_file_path,
        domain=config.domain,
        port=config.port or 8000,
    )
    stack_instance = stack_class(context)
    detected = stack_instance.detect_services(project_path)

    # PostgreSQL
    if detected.needs_postgresql:
        if postgres.is_postgresql_running():
            console.print("  [green]✓[/green] PostgreSQL — running")
        else:
            postgres.install_postgresql(pkg_manager)

        if not config.db_name:
            db_info = postgres.create_database(config.name)
            if db_info:
                config.db_name = db_info["db_name"]
                config.db_user = db_info["db_user"]
                config.db_password = db_info["db_password"]
                if "postgresql" not in config.services:
                    config.services.append("postgresql")

                # Show credentials
                console.print(f"  [green]✓[/green] Database: [yellow]{db_info['db_name']}[/yellow]")
                console.print(f"      User: [yellow]{db_info['db_user']}[/yellow]")
                console.print(f"      Pass: [yellow]{db_info['db_password']}[/yellow]")
        else:
            console.print(f"  [green]✓[/green] Database — {config.db_name} (already created)")

    # Redis
    if detected.needs_redis:
        if redis.is_redis_running(pkg_manager):
            console.print("  [green]✓[/green] Redis — running")
        else:
            redis.install_redis(pkg_manager)
        if "redis" not in config.services:
            config.services.append("redis")

    save_project_config(config)

    # --- .env file ---
    env_in_project = project_path / ".env"
    if env_in_project.exists():
        console.print("  [green]✓[/green] .env — exists")
    else:
        db_info = None
        if config.db_name:
            db_info = {
                "db_name": config.db_name,
                "db_user": config.db_user,
                "db_password": config.db_password,
                "db_host": "localhost",
                "db_port": "5432",
            }
        redis_url = redis.get_redis_url() if "redis" in config.services else ""

        env_vars = collect_env_vars_interactive(
            project_name=config.name,
            stack=config.stack,
            db_info=db_info,
            domain=config.domain,
            redis_url=redis_url,
        )
        create_env_file(config.name, env_vars)
        symlink_env_to_project(config.name, project_path)
        success(".env created")

    # --- Migrations ---
    if stack_type == StackType.DJANGO:
        manage_py = project_path / "manage.py"
        if manage_py.exists():
            step("Running migrations...")
            result = run_cmd([str(python_path), "manage.py", "migrate", "--noinput"], cwd=project_path)
            if result.success:
                success("Migrations applied")
            else:
                warning("Migrations failed — check .env DB settings")

    # --- Systemd services ---
    # Main service (gunicorn/uvicorn)
    service_name = stack_instance.get_service_name()
    systemd.enable_service(service_name)
    console.print(f"  [green]✓[/green] {service_name} — active (port {config.port})")

    # Celery worker
    if detected.needs_celery:
        celery_app = _detect_celery_app(project_path, config.name)
        systemd.create_celery_worker_service(
            project_name=config.name,
            working_dir=project_path,
            venv_path=venv_path,
            celery_app=celery_app,
            env_file=env_file_path,
        )
        systemd.enable_service(f"{config.name}-celery-worker")
        console.print(f"  [green]✓[/green] {config.name}-celery-worker — active")
        if "celery" not in config.services:
            config.services.append("celery")

    # Celery beat
    if detected.needs_celery_beat:
        celery_app = _detect_celery_app(project_path, config.name)
        shared_path = project_path / "shared"
        shared_path.mkdir(parents=True, exist_ok=True)
        systemd.create_celery_beat_service(
            project_name=config.name,
            working_dir=project_path,
            venv_path=venv_path,
            celery_app=celery_app,
            env_file=env_file_path,
            shared_dir=shared_path,
        )
        systemd.enable_service(f"{config.name}-celery-beat")
        console.print(f"  [green]✓[/green] {config.name}-celery-beat — active")
        if "celery-beat" not in config.services:
            config.services.append("celery-beat")

    return True


# ─── Next.js ──────────────────────────────────────────────────────────────────


def _setup_nextjs(
    config: ProjectConfig,
    project_path: Path,
    os_info,
    pkg_manager,
) -> bool:
    """Setup a Next.js project progressively. Returns True on success."""
    # Install Node.js — STOP if this fails
    if not node.is_nodejs_installed():
        if not _install_nodejs_with_fallback(pkg_manager):
            error("Node.js installation failed. Install manually: sudo apt install nodejs npm")
            return
    else:
        console.print(f"  [green]✓[/green] Node.js — {node.get_node_version()}")

    if not node.is_npm_installed():
        error("npm not found. Install manually: sudo apt install npm")
        return False

    # Install PM2
    pm2.install_pm2()

    # npm install
    step("Installing dependencies...")
    pkg_mgr = _detect_node_pkg_manager(project_path)
    if pkg_mgr == "yarn":
        result = run_cmd(["yarn", "install"], cwd=project_path, timeout=300)
    elif pkg_mgr == "pnpm":
        result = run_cmd(["pnpm", "install"], cwd=project_path, timeout=300)
    else:
        cmd = ["npm", "ci"] if (project_path / "package-lock.json").exists() else ["npm", "install"]
        result = run_cmd(cmd, cwd=project_path, timeout=300)

    if not result.success:
        error("Dependency installation failed")
        return False
    success("Dependencies installed")

    # npm build
    step("Building...")
    if pkg_mgr == "yarn":
        result = run_cmd(["yarn", "build"], cwd=project_path, timeout=600)
    elif pkg_mgr == "pnpm":
        result = run_cmd(["pnpm", "run", "build"], cwd=project_path, timeout=600)
    else:
        result = run_cmd(["npm", "run", "build"], cwd=project_path, timeout=600)

    if result.success:
        success("Build complete")
    else:
        error("Build failed")
        return False

    # Start with PM2
    port = config.port or 3000
    config.port = port
    pm2.start_app(
        project_name=config.name,
        working_dir=project_path,
        script="npm",
        args="start",
        port=port,
    )
    console.print(f"  [green]✓[/green] PM2 process — running (port {port})")

    if "pm2" not in config.services:
        config.services.append("pm2")

    return True


# ─── Static Frontend (React Vite/CRA, HTML) ──────────────────────────────────


def _setup_static_frontend(
    config: ProjectConfig,
    project_path: Path,
    os_info,
    pkg_manager,
    stack_type: StackType,
) -> bool:
    """Setup a static frontend project. Returns True on success."""
    if stack_type == StackType.HTML:
        console.print("  [green]✓[/green] Static HTML — no build needed")
        return True

    # Install Node.js — STOP if this fails
    if not node.is_nodejs_installed():
        if not _install_nodejs_with_fallback(pkg_manager):
            error("Node.js installation failed. Install manually: sudo apt install nodejs npm")
            return
    else:
        console.print(f"  [green]✓[/green] Node.js — {node.get_node_version()}")

    # Verify npm is available
    if not node.is_npm_installed():
        error("npm not found. Install manually: sudo apt install npm")
        return False

    # npm install
    step("Installing dependencies...")
    pkg_mgr = _detect_node_pkg_manager(project_path)
    if pkg_mgr == "yarn":
        result = run_cmd(["yarn", "install"], cwd=project_path, timeout=300)
    elif pkg_mgr == "pnpm":
        result = run_cmd(["pnpm", "install"], cwd=project_path, timeout=300)
    else:
        cmd = ["npm", "ci"] if (project_path / "package-lock.json").exists() else ["npm", "install"]
        result = run_cmd(cmd, cwd=project_path, timeout=300)

    if not result.success:
        error("Dependency installation failed")
        return False
    success("Dependencies installed")

    # npm build
    step("Building...")
    if pkg_mgr == "yarn":
        result = run_cmd(["yarn", "build"], cwd=project_path, timeout=300)
    elif pkg_mgr == "pnpm":
        result = run_cmd(["pnpm", "run", "build"], cwd=project_path, timeout=300)
    else:
        result = run_cmd(["npm", "run", "build"], cwd=project_path, timeout=300, env={"CI": "true"})

    if result.success:
        build_dir = "dist" if stack_type == StackType.REACT_VITE else "build"
        success(f"Build complete → {build_dir}/")
        return True
    else:
        error("Build failed")
        return False


# ─── Nginx + SSL (shared) ─────────────────────────────────────────────────────


def _setup_nginx_and_ssl(
    config: ProjectConfig,
    project_path: Path,
    stack_type: StackType,
    pkg_manager,
) -> None:
    """Configure Nginx and optionally SSL."""

    # Ask for domain
    if not config.domain:
        config.domain = Prompt.ask("\nDomain name (e.g., myapp.com)")
        save_project_config(config)

    if not config.domain:
        warning("No domain — skipping Nginx")
        return

    # Check if same domain as another project (for frontend+backend on same domain)
    same_domain_project = _find_project_with_domain(config.domain, exclude=config.name)

    if same_domain_project:
        # Same domain — ask about path-based routing
        console.print(f"\n  [yellow]Domain '{config.domain}' is already used by '{same_domain_project.name}'[/yellow]")
        if Confirm.ask("  Configure same-domain routing? (frontend at /, backend at /api/)", default=True):
            api_prefix = Prompt.ask("  Backend URL prefix", default="/api/")
            _create_same_domain_nginx(config, same_domain_project, project_path, stack_type, api_prefix)
            save_project_config(config)
        else:
            warning("Skipping Nginx — domain conflict")
            return
    else:
        # Unique domain — create standard nginx config
        _create_standard_nginx(config, project_path, stack_type)
        save_project_config(config)

    console.print(f"  [green]✓[/green] Nginx — {config.domain}")

    # SSL
    if Confirm.ask("\n  Install SSL certificate?", default=True):
        email = Prompt.ask("  Email for Let's Encrypt")
        ssl.install_certbot(pkg_manager)
        if ssl.obtain_certificate(domain=config.domain, email=email):
            ssl.setup_auto_renewal()
            console.print("  [green]✓[/green] SSL — installed + auto-renewal")
        else:
            warning("SSL installation failed — you can retry with 'deploycraft ssl'")


def _create_standard_nginx(config: ProjectConfig, project_path: Path, stack_type: StackType) -> None:
    """Create a standard Nginx config for a single project on its own domain."""
    if stack_type in (StackType.REACT_VITE, StackType.REACT, StackType.HTML):
        build_dir = "dist" if stack_type == StackType.REACT_VITE else "build"
        if stack_type == StackType.HTML:
            doc_root = str(project_path)
        else:
            doc_root = str(project_path / build_dir)
        nginx.create_static_site_config(config.name, config.domain, doc_root)
    elif stack_type == StackType.NEXTJS:
        nginx.create_reverse_proxy_config(
            config.name, config.domain,
            upstream=f"127.0.0.1:{config.port or 3000}",
            use_socket=False,
        )
    else:
        # Django/FastAPI
        nginx.create_reverse_proxy_config(
            config.name, config.domain,
            upstream=f"127.0.0.1:{config.port or 8000}",
            static_path=str(project_path / "staticfiles"),
            media_path=str(project_path / "shared" / "media"),
            use_socket=False,
        )


def _create_same_domain_nginx(
    current_config: ProjectConfig,
    other_config: ProjectConfig,
    project_path: Path,
    stack_type: StackType,
    api_prefix: str,
) -> None:
    """Create an Nginx config that serves frontend + backend on the same domain.

    Routes:
    - / → frontend (static files or Next.js)
    - /api/ (or custom prefix) → backend (gunicorn)
    """
    from jinja2 import BaseLoader, Environment

    domain = current_config.domain

    # Determine which is frontend and which is backend
    if stack_type in (StackType.DJANGO, StackType.FASTAPI):
        # Current project is the backend being added to an existing frontend domain
        backend_config = current_config
        frontend_config = other_config
    else:
        # Current project is the frontend being added to an existing backend domain
        frontend_config = current_config
        backend_config = other_config

    # Determine frontend root
    frontend_path = Path(frontend_config.base_path)
    frontend_stack = StackType(frontend_config.stack)
    if frontend_stack == StackType.REACT_VITE:
        frontend_root = str(frontend_path / "dist")
    elif frontend_stack in (StackType.REACT, StackType.HTML):
        frontend_root = str(frontend_path / "build")
    elif frontend_stack == StackType.HTML:
        frontend_root = str(frontend_path)
    else:
        # Next.js — proxy to PM2
        frontend_root = None

    backend_port = backend_config.port or 8000
    backend_path = Path(backend_config.base_path)

    # Ensure api_prefix has proper format
    if not api_prefix.startswith("/"):
        api_prefix = f"/{api_prefix}"
    if not api_prefix.endswith("/"):
        api_prefix = f"{api_prefix}/"

    SAME_DOMAIN_TEMPLATE = """\
server {
    listen 80;
    server_name {{ domain }};

    # Backend API ({{ api_prefix }})
    location {{ api_prefix }} {
        proxy_pass http://127.0.0.1:{{ backend_port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Django/FastAPI admin
    location /admin/ {
        proxy_pass http://127.0.0.1:{{ backend_port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend static files
    location /static/ {
        alias {{ backend_static }}/;
        expires 30d;
    }

    {% if backend_media %}
    location /media/ {
        alias {{ backend_media }}/;
        expires 7d;
    }
    {% endif %}

    {% if frontend_root %}
    # Frontend (static build)
    location / {
        root {{ frontend_root }};
        index index.html;
        try_files $uri $uri/ /index.html;
    }
    {% elif frontend_port %}
    # Frontend (Next.js via PM2)
    location / {
        proxy_pass http://127.0.0.1:{{ frontend_port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    {% endif %}

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    client_max_body_size 100M;

    access_log /var/log/nginx/{{ config_name }}-access.log;
    error_log /var/log/nginx/{{ config_name }}-error.log;
}
"""

    env = Environment(loader=BaseLoader())
    template = env.from_string(SAME_DOMAIN_TEMPLATE)

    content = template.render(
        domain=domain,
        api_prefix=api_prefix,
        backend_port=backend_port,
        backend_static=str(backend_path / "staticfiles"),
        backend_media=str(backend_path / "shared" / "media"),
        frontend_root=frontend_root,
        frontend_port=frontend_config.port if frontend_root is None else None,
        config_name=domain.replace(".", "_"),
    )

    # Write as domain-based config name
    config_name = domain.replace(".", "_")
    import tempfile

    NGINX_CONF_D = Path("/etc/nginx/conf.d")
    config_path = NGINX_CONF_D / f"{config_name}.conf"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
        f.write(content)
        temp_path = f.name

    run_cmd(["sudo", "mkdir", "-p", str(NGINX_CONF_D)])
    run_cmd(["sudo", "cp", temp_path, str(config_path)])
    run_cmd(["sudo", "chmod", "644", str(config_path)])
    Path(temp_path).unlink(missing_ok=True)

    # Remove old individual configs that might conflict
    old_configs = [
        NGINX_CONF_D / f"{current_config.name}.conf",
        NGINX_CONF_D / f"{other_config.name}.conf",
    ]
    for old in old_configs:
        if old.exists() and old != config_path:
            run_cmd(["sudo", "rm", "-f", str(old)])

    # Test and reload
    if nginx.test_nginx_config():
        nginx.reload_nginx()
        success(f"Same-domain Nginx: {domain} (frontend at /, backend at {api_prefix})")
    else:
        error("Nginx config test failed")


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _install_nodejs_with_fallback(pkg_manager) -> bool:
    """Install Node.js using NVM (Node Version Manager).

    NVM installs Node.js in user directory — no sudo, no apt lock issues.
    Steps:
    1. Install NVM
    2. Source bashrc
    3. nvm install --lts
    4. Verify node and npm work

    Returns:
        True if Node.js was installed successfully.
    """
    import os

    step("Installing Node.js via NVM...")

    home = os.path.expanduser("~")
    nvm_dir = os.path.join(home, ".nvm")

    # Check if NVM already installed
    if not os.path.exists(nvm_dir):
        # Install NVM
        result = run_cmd(
            ["bash", "-c", "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"],
            timeout=60,
        )
        if not result.success:
            error(f"NVM installation failed: {result.stderr.strip()[:200]}")
            return False
        success("NVM installed")
    else:
        console.print("  [green]✓[/green] NVM — already installed")

    # Install Node.js LTS using NVM
    # Need to source nvm.sh before running nvm commands
    nvm_script = f'export NVM_DIR="{nvm_dir}" && [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"'

    result = run_cmd(
        ["bash", "-c", f'{nvm_script} && nvm install --lts'],
        timeout=120,
    )
    if not result.success:
        error(f"Node.js installation failed: {result.stderr.strip()[:200]}")
        return False

    # Verify node works
    result = run_cmd(
        ["bash", "-c", f'{nvm_script} && node --version'],
    )
    if result.success:
        version = result.stdout.strip()
        success(f"Node.js installed: {version}")

        # Create symlinks so node/npm are available without sourcing nvm
        # This makes them work in systemd services and other non-interactive shells
        node_path = run_cmd(["bash", "-c", f'{nvm_script} && which node'])
        npm_path = run_cmd(["bash", "-c", f'{nvm_script} && which npm'])

        if node_path.success and npm_path.success:
            node_bin = node_path.stdout.strip()
            npm_bin = npm_path.stdout.strip()
            # Symlink to /usr/local/bin for global access
            run_cmd(["sudo", "ln", "-sf", node_bin, "/usr/local/bin/node"])
            run_cmd(["sudo", "ln", "-sf", npm_bin, "/usr/local/bin/npm"])
            # Also link npx
            npx_path = run_cmd(["bash", "-c", f'{nvm_script} && which npx'])
            if npx_path.success:
                run_cmd(["sudo", "ln", "-sf", npx_path.stdout.strip(), "/usr/local/bin/npx"])

        return True
    else:
        error("Node.js installed but not accessible")
        return False


def _detect_stack(project_path: Path) -> str:
    """Auto-detect the project stack from files."""
    # Django
    if (project_path / "manage.py").exists():
        return "django"

    # Check requirements.txt
    if (project_path / "requirements.txt").exists():
        reqs = (project_path / "requirements.txt").read_text().lower()
        if "django" in reqs:
            return "django"
        if "fastapi" in reqs:
            return "fastapi"

    # FastAPI by main.py
    for f in ["main.py", "app/main.py", "src/main.py"]:
        if (project_path / f).exists():
            content = (project_path / f).read_text()
            if "FastAPI" in content:
                return "fastapi"

    # Node.js projects
    if (project_path / "package.json").exists():
        import json

        try:
            pkg = json.loads((project_path / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "react-scripts" in deps:
                return "react"
            if "vite" in deps:
                return "react_vite"
        except (json.JSONDecodeError, OSError):
            return "nextjs"

    # Plain HTML
    if (project_path / "index.html").exists():
        return "html"

    return ""


def _detect_celery_app(project_path: Path, project_name: str) -> str:
    """Detect Celery app module name."""
    for candidate in project_path.iterdir():
        if candidate.is_dir() and (candidate / "celery.py").exists():
            return candidate.name
    return project_name


def _detect_node_pkg_manager(project_path: Path) -> str:
    """Detect Node.js package manager."""
    if (project_path / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_path / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _find_project_with_domain(domain: str, exclude: str = "") -> Optional[ProjectConfig]:
    """Find an existing project that uses the given domain."""
    for project in get_all_projects():
        if project.domain == domain and project.name != exclude:
            return project
    return None
