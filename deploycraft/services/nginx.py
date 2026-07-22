"""Nginx configuration management.

Generates Nginx server blocks for reverse proxy and static sites.
"""

import tempfile
from pathlib import Path
from typing import Optional

from jinja2 import BaseLoader, Environment
from rich.console import Console

from deploycraft.os_detect import PackageManager
from deploycraft.utils import error, run_cmd, step, success

console = Console()

NGINX_SITES_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_SITES_ENABLED = Path("/etc/nginx/sites-enabled")
NGINX_CONF_D = Path("/etc/nginx/conf.d")

# --- Templates ---

REVERSE_PROXY_TEMPLATE = """\
server {
    listen 80;
    server_name {{ domain }};

    location / {
        proxy_pass http://{{ upstream }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
        proxy_buffering off;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /static/ {
        alias {{ static_path }}/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    {% if media_path %}
    location /media/ {
        alias {{ media_path }}/;
        expires 7d;
    }
    {% endif %}

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 100M;

    access_log /var/log/nginx/{{ project_name }}-access.log;
    error_log /var/log/nginx/{{ project_name }}-error.log;
}
"""

UNIX_SOCKET_PROXY_TEMPLATE = """\
server {
    listen 80;
    server_name {{ domain }};

    location / {
        proxy_pass http://unix:{{ socket_path }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    location /static/ {
        alias {{ static_path }}/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    {% if media_path %}
    location /media/ {
        alias {{ media_path }}/;
        expires 7d;
    }
    {% endif %}

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 100M;

    access_log /var/log/nginx/{{ project_name }}-access.log;
    error_log /var/log/nginx/{{ project_name }}-error.log;
}
"""

STATIC_SITE_TEMPLATE = """\
server {
    listen 80;
    server_name {{ domain }};

    root {{ document_root }};
    index index.html index.htm;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    access_log /var/log/nginx/{{ project_name }}-access.log;
    error_log /var/log/nginx/{{ project_name }}-error.log;
}
"""


def install_nginx(pkg_manager: PackageManager) -> bool:
    """Install and start Nginx.

    Args:
        pkg_manager: Package manager instance.

    Returns:
        True if installation was successful.
    """
    step("Installing Nginx...")

    result = run_cmd(pkg_manager.install_cmd("nginx"))
    if not result.success:
        error(f"Nginx installation failed: {result.stderr.strip()[:200]}")
        return False

    # Enable and start
    result = run_cmd(pkg_manager.enable_service_cmd("nginx"))
    if not result.success:
        error(f"Failed to start Nginx: {result.stderr.strip()[:200]}")
        return False

    success("Nginx installed and running")
    return True


def create_reverse_proxy_config(
    project_name: str,
    domain: str,
    upstream: str = "127.0.0.1:8000",
    static_path: Optional[str] = None,
    media_path: Optional[str] = None,
    use_socket: bool = False,
) -> bool:
    """Create an Nginx reverse proxy configuration.

    Args:
        project_name: Name of the project.
        domain: Domain name for the server block.
        upstream: Upstream server (host:port). Default: 127.0.0.1:8000.
        static_path: Path to static files directory.
        media_path: Path to media files directory.
        use_socket: Whether to use Unix socket or TCP proxy.

    Returns:
        True if config was created and Nginx reloaded successfully.
    """
    step(f"Configuring Nginx for {domain}")

    env = Environment(loader=BaseLoader())

    if use_socket:
        socket_path = f"/run/{project_name}/gunicorn.sock"
        template = env.from_string(UNIX_SOCKET_PROXY_TEMPLATE)
        content = template.render(
            project_name=project_name,
            domain=domain,
            socket_path=socket_path,
            static_path=static_path or f"/var/www/{project_name}/staticfiles",
            media_path=media_path,
        )
    else:
        template = env.from_string(REVERSE_PROXY_TEMPLATE)
        content = template.render(
            project_name=project_name,
            domain=domain,
            upstream=upstream,
            static_path=static_path or f"/var/www/{project_name}/current/staticfiles",
            media_path=media_path,
        )

    return _write_nginx_config(project_name, content)


def create_static_site_config(
    project_name: str,
    domain: str,
    document_root: str,
) -> bool:
    """Create an Nginx static site configuration.

    Args:
        project_name: Name of the project.
        domain: Domain name.
        document_root: Path to the built static files.

    Returns:
        True if config was created and Nginx reloaded successfully.
    """
    step(f"Configuring Nginx static site for {domain}")

    env = Environment(loader=BaseLoader())
    template = env.from_string(STATIC_SITE_TEMPLATE)
    content = template.render(
        project_name=project_name,
        domain=domain,
        document_root=document_root,
    )

    return _write_nginx_config(project_name, content)


def remove_nginx_config(project_name: str) -> bool:
    """Remove Nginx configuration for a project.

    Args:
        project_name: Name of the project.

    Returns:
        True if removed successfully.
    """
    conf_d = NGINX_CONF_D / f"{project_name}.conf"
    if conf_d.exists():
        run_cmd(["sudo", "rm", "-f", str(conf_d)])

    reload_nginx()
    return True


def test_nginx_config() -> bool:
    """Test Nginx configuration for syntax errors.

    Returns:
        True if configuration is valid.
    """
    result = run_cmd(["sudo", "nginx", "-t"])
    return result.success


def reload_nginx() -> bool:
    """Reload Nginx to apply configuration changes.

    Returns:
        True if reload was successful.
    """
    if not test_nginx_config():
        error("Nginx configuration test failed! Not reloading.")
        return False
    result = run_cmd(["sudo", "systemctl", "reload", "nginx"])
    return result.success


def _write_nginx_config(project_name: str, content: str) -> bool:
    """Write Nginx config to /etc/nginx/conf.d/project_name.conf.

    Always uses conf.d/ — no sites-available/sites-enabled symlink dance.

    Args:
        project_name: Name for the config file.
        content: The Nginx configuration content.

    Returns:
        True if successful.
    """
    config_path = NGINX_CONF_D / f"{project_name}.conf"

    # Write via temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
        f.write(content)
        temp_path = f.name

    run_cmd(["sudo", "mkdir", "-p", str(NGINX_CONF_D)])
    run_cmd(["sudo", "cp", temp_path, str(config_path)])
    run_cmd(["sudo", "chmod", "644", str(config_path)])
    Path(temp_path).unlink(missing_ok=True)

    # Test and reload
    if test_nginx_config():
        reload_nginx()
        success(f"Nginx configured: {config_path}")
        return True
    else:
        error("Nginx config test failed! Check configuration.")
        return False
