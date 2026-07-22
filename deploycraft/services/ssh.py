"""SSH key management for DeployCraft.

Generates SSH keypairs for the server and displays the public key so it can
be added to GitHub/GitLab as a Deploy Key, authorizing this server to clone
private repositories.
"""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from deploycraft.utils import error, run_cmd, step, success, warning

console = Console()

# Default SSH key location (for root deployment use)
DEFAULT_KEY_NAME = "deploycraft_deploy"
DEFAULT_SSH_DIR = Path("/root/.ssh")
USER_SSH_DIR = Path.home() / ".ssh"


def get_ssh_dir() -> Path:
    """Get the appropriate SSH directory based on current user.

    Returns:
        Path to ~/.ssh for current user.
    """
    return Path.home() / ".ssh"


def get_key_paths(key_name: str = DEFAULT_KEY_NAME, ssh_dir: Optional[Path] = None) -> tuple[Path, Path]:
    """Get private and public key paths.

    Args:
        key_name: Base name for the key files.
        ssh_dir: SSH directory (defaults to current user's ~/.ssh).

    Returns:
        Tuple of (private_key_path, public_key_path).
    """
    ssh_dir = ssh_dir or get_ssh_dir()
    private_key = ssh_dir / key_name
    public_key = ssh_dir / f"{key_name}.pub"
    return private_key, public_key


def key_exists(key_name: str = DEFAULT_KEY_NAME, ssh_dir: Optional[Path] = None) -> bool:
    """Check if an SSH keypair already exists.

    Args:
        key_name: Key name to check.
        ssh_dir: SSH directory to check in.

    Returns:
        True if the keypair already exists.
    """
    private_key, public_key = get_key_paths(key_name, ssh_dir)
    return private_key.exists() and public_key.exists()


def generate_keypair(
    key_name: str = DEFAULT_KEY_NAME,
    ssh_dir: Optional[Path] = None,
    comment: str = "",
    force: bool = False,
) -> Optional[Path]:
    """Generate an Ed25519 SSH keypair.

    Ed25519 is used instead of RSA — it's shorter, faster, and more secure.
    Also configures ~/.ssh/config so git automatically uses this key.

    Args:
        key_name: Base name for the key files.
        ssh_dir: SSH directory (defaults to current user's ~/.ssh).
        comment: Comment to embed in the public key (e.g., hostname).
        force: If True, overwrite an existing keypair.

    Returns:
        Path to the public key file, or None on failure.
    """
    ssh_dir = ssh_dir or get_ssh_dir()
    private_key, public_key = get_key_paths(key_name, ssh_dir)

    # Check if already exists
    if private_key.exists() and not force:
        # Still ensure SSH config is set up
        _ensure_ssh_config(private_key, ssh_dir)
        return public_key

    # Create SSH directory with correct permissions
    ssh_dir.mkdir(parents=True, exist_ok=True)
    ssh_dir.chmod(0o700)

    # Build comment from hostname if not provided
    if not comment:
        import socket
        comment = f"deploycraft@{socket.gethostname()}"

    step(f"Generating Ed25519 SSH keypair: {private_key}")

    result = run_cmd([
        "ssh-keygen",
        "-t", "ed25519",
        "-C", comment,
        "-f", str(private_key),
        "-N", "",          # No passphrase
        "-q",              # Quiet
    ])

    if not result.success:
        error(f"SSH key generation failed: {result.stderr.strip()[:200]}")
        return None

    # Ensure correct permissions
    private_key.chmod(0o600)
    public_key.chmod(0o644)

    # Configure SSH to use this key for git hosts
    _ensure_ssh_config(private_key, ssh_dir)

    success(f"SSH keypair generated: {private_key}")
    return public_key


def get_public_key(
    key_name: str = DEFAULT_KEY_NAME,
    ssh_dir: Optional[Path] = None,
) -> Optional[str]:
    """Get the content of the public key.

    Args:
        key_name: Key name.
        ssh_dir: SSH directory.

    Returns:
        Public key content as a string, or None if not found.
    """
    _, public_key = get_key_paths(key_name, ssh_dir)
    if not public_key.exists():
        return None
    return public_key.read_text().strip()


def ensure_keypair_exists(
    key_name: str = DEFAULT_KEY_NAME,
    ssh_dir: Optional[Path] = None,
) -> Optional[str]:
    """Ensure an SSH keypair exists, generating one if needed.

    This is the main entry point for the deploy wizard. It checks for an
    existing key, generates one if missing, then returns the public key
    to display to the user.

    Args:
        key_name: Key name.
        ssh_dir: SSH directory.

    Returns:
        Public key string ready to be added to GitHub/GitLab.
    """
    if key_exists(key_name, ssh_dir):
        public_key = get_public_key(key_name, ssh_dir)
        _, pub_path = get_key_paths(key_name, ssh_dir)
        success(f"SSH key already exists: {pub_path}")
        return public_key

    # Generate new key
    pub_path = generate_keypair(key_name, ssh_dir)
    if pub_path is None:
        return None

    return get_public_key(key_name, ssh_dir)


def display_public_key_instructions(public_key: str, git_url: str = "") -> None:
    """Display the public key with instructions on how to add it to Git.

    Args:
        public_key: The public key string.
        git_url: Optional git URL to customize instructions.
    """
    # Determine hosting platform
    if "github.com" in git_url:
        platform = "GitHub"
        url_hint = "https://github.com/<user>/<repo>/settings/keys/new"
        title = "Add as GitHub Deploy Key"
    elif "gitlab.com" in git_url:
        platform = "GitLab"
        url_hint = "https://gitlab.com/<user>/<repo>/-/settings/repository → Deploy Keys"
        title = "Add as GitLab Deploy Key"
    elif "bitbucket.org" in git_url:
        platform = "Bitbucket"
        url_hint = "https://bitbucket.org/<user>/<repo>/admin/access-keys/"
        title = "Add as Bitbucket Access Key"
    else:
        platform = "Git"
        url_hint = "Your repository settings → Deploy Keys / SSH Keys"
        title = "Add SSH Deploy Key"

    console.print("")
    console.print(Panel(
        f"[bold yellow]{public_key}[/bold yellow]",
        title=f"🔑 SSH Public Key — {title}",
        border_style="yellow",
    ))
    console.print(f"\n[bold]How to add this key to {platform}:[/bold]")
    console.print("  1. Copy the key above")
    console.print(f"  2. Go to: [cyan]{url_hint}[/cyan]")
    console.print("  3. Paste the key → give it a title (e.g., 'Server Deploy Key')")
    console.print("  4. Enable [bold]write access[/bold] only if you need to push from the server")
    console.print("  5. Save and come back here\n")


def run_ssh_key_wizard(git_url: str = "") -> Optional[str]:
    """Interactive SSH key setup wizard.

    Checks for an existing key, generates if needed, displays it,
    and waits for the user to confirm they've added it to their Git provider.

    Args:
        git_url: Optional repository URL to customize instructions.

    Returns:
        The public key string, or None if setup failed.
    """
    console.print("\n[bold cyan]SSH Key Setup[/bold cyan]")
    console.print("[dim]DeployCraft needs an SSH key to clone private repositories.[/dim]\n")

    public_key = ensure_keypair_exists()
    if not public_key:
        error("Failed to set up SSH key")
        return None

    display_public_key_instructions(public_key, git_url)

    Confirm.ask(
        "Have you added the key to your Git provider? Press Enter to continue",
        default=True,
    )

    return public_key


def test_ssh_connection(git_url: str) -> bool:
    """Test SSH connectivity to a Git provider.

    Args:
        git_url: The repository URL (to determine which host to test).

    Returns:
        True if the SSH connection is authorized.
    """
    # Extract hostname from git URL
    if "github.com" in git_url:
        host = "github.com"
    elif "gitlab.com" in git_url:
        host = "gitlab.com"
    elif "bitbucket.org" in git_url:
        host = "bitbucket.org"
    else:
        # Can't test unknown hosts
        return True

    step(f"Testing SSH connection to {host}...")

    result = run_cmd([
        "ssh",
        "-T",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        f"git@{host}",
    ])

    # GitHub/GitLab return exit code 1 with a success message ("Hi username!")
    # A real auth failure returns exit code 255
    if result.returncode in (0, 1) and (
        "successfully authenticated" in result.stderr.lower()
        or "welcome to gitlab" in result.stderr.lower()
        or "hi " in result.stderr.lower()
    ):
        success(f"SSH connection to {host} authorized")
        return True

    warning(f"SSH connection to {host} may not be authorized yet")
    return False


def _ensure_ssh_config(private_key_path: Path, ssh_dir: Optional[Path] = None) -> None:
    """Configure ~/.ssh/config so SSH uses our deploy key for git hosts.

    Adds entries for github.com, gitlab.com, and bitbucket.org pointing
    to our deploy key. This is required because SSH won't automatically
    try a key with a non-standard name.

    Args:
        private_key_path: Path to the private key file.
        ssh_dir: SSH directory (defaults to current user's ~/.ssh).
    """
    ssh_dir = ssh_dir or get_ssh_dir()
    config_path = ssh_dir / "config"

    # The config block we want to add
    marker = "# DeployCraft deploy key configuration"
    config_block = f"""\n{marker}
Host github.com
    HostName github.com
    User git
    IdentityFile {private_key_path}
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new

Host gitlab.com
    HostName gitlab.com
    User git
    IdentityFile {private_key_path}
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new

Host bitbucket.org
    HostName bitbucket.org
    User git
    IdentityFile {private_key_path}
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
"""

    # Check if already configured
    if config_path.exists():
        existing_content = config_path.read_text()
        if marker in existing_content:
            # Already configured — update the key path in case it changed
            import re
            # Remove old block and add new one
            pattern = f"{marker}.*?(?=\\n# |\\Z)"
            cleaned = re.sub(pattern, "", existing_content, flags=re.DOTALL).rstrip()
            config_path.write_text(cleaned + config_block)
            config_path.chmod(0o600)
            return
        else:
            # Append to existing config
            with config_path.open("a") as f:
                f.write(config_block)
    else:
        # Create new config
        config_path.write_text(config_block.lstrip())

    config_path.chmod(0o600)
    step("SSH config updated to use deploy key")
