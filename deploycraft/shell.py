"""Interactive shell mode for DeployCraft.

Provides a REPL-style interface where users can type commands without
repeating the 'deploycraft' prefix. Supports command history, tab completion,
and colored prompt.
"""

import shlex
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from deploycraft import __version__

console = Console()

# All available top-level and subcommands for tab completion
COMMANDS = [
    "init",
    "deploy",
    "clone",
    "inspect",
    "install-services",
    "configure",
    "restart",
    "redeploy",
    "rollback",
    "stable",
    "status",
    "list",
    "remove",
    "logs",
    "monitor start",
    "monitor stop",
    "monitor status",
    "ssh-key",
    "ssh-key show",
    "ssh-key generate",
    "ssh-key test",
    "user",
    "user create",
    "user delete",
    "user sudo",
    "user list",
    "help",
    "exit",
    "quit",
    "clear",
    "version",
]

# History file location
HISTORY_FILE = Path.home() / ".config" / "deploycraft" / ".shell_history"


def _completer(text: str, state: int) -> Optional[str]:
    """Tab completion handler for readline."""
    try:
        import readline
        line = readline.get_line_buffer().lstrip()
    except Exception:
        line = text

    matches = [cmd for cmd in COMMANDS if cmd.startswith(line or text)]

    if state < len(matches):
        match = matches[state]
        # Return only the suffix that isn't already typed
        if line and match.startswith(line):
            return match[len(line) - len(text):]
        return match
    return None


def _setup_readline() -> None:
    """Configure readline with history and tab completion."""
    try:
        import readline

        readline.set_completer(_completer)

        # Use parse_and_bind (correct name, works on Linux/macOS with GNU readline)
        try:
            readline.parse_and_bind("tab: complete")
        except AttributeError:
            # libedit on macOS uses a different syntax
            readline.parse_and_bind("bind ^I rl_complete")

        # Load history file
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            if HISTORY_FILE.exists():
                readline.read_history_file(str(HISTORY_FILE))
        except (OSError, PermissionError):
            pass

        readline.set_history_length(500)

    except ImportError:
        pass  # readline not available — continue without history/completion


def _save_history() -> None:
    """Save command history to disk."""
    try:
        import readline
        readline.write_history_file(str(HISTORY_FILE))
    except (ImportError, OSError, PermissionError):
        pass


def _print_help() -> None:
    """Display help with all available commands."""
    console.print("\n[bold cyan]Available Commands:[/bold cyan]\n")

    commands_help = [
        ("init", "First-time setup (SMTP, admin email, preferences)"),
        ("deploy", "Interactive deployment wizard (all steps)"),
        ("", ""),
        ("clone <url>", "Clone a git repo (--path, --branch)"),
        ("inspect [path]", "Detect services needed (--stack to override)"),
        ("install-services <project>", "Install PostgreSQL, Redis, Node etc."),
        ("configure <project>", "Set up Nginx, systemd, .env"),
        ("restart <project>", "Restart all services"),
        ("", ""),
        ("redeploy <project>", "Pull latest and redeploy"),
        ("rollback <project>", "Revert to previous commit"),
        ("stable <project>", "Mark current commit as stable"),
        ("status", "Show all projects + system health"),
        ("list", "List managed projects"),
        ("remove <project>", "Remove a project"),
        ("logs <project>", "Show project logs"),
        ("", ""),
        ("ssh-key", "SSH key wizard"),
        ("ssh-key show", "Display public key"),
        ("ssh-key generate", "Generate new keypair (--force to regenerate)"),
        ("ssh-key test <url>", "Test SSH connectivity"),
        ("", ""),
        ("user create", "Create a system user"),
        ("user delete <name>", "Delete a system user"),
        ("user sudo <name>", "Grant sudo (--revoke to remove)"),
        ("user list", "List admin users"),
        ("", ""),
        ("monitor start", "Enable monitoring daemon"),
        ("monitor stop", "Disable monitoring daemon"),
        ("monitor status", "Show monitor status"),
        ("", ""),
        ("help", "Show this help"),
        ("clear", "Clear the screen"),
        ("version", "Show DeployCraft version"),
        ("exit / quit", "Exit interactive shell"),
    ]

    for cmd, desc in commands_help:
        if not cmd:
            console.print("")
        else:
            console.print(f"  [green]{cmd:<28}[/green] {desc}")

    console.print("")


def _execute_command(input_line: str) -> bool:
    """Parse and execute a shell command.

    Args:
        input_line: Raw user input string.

    Returns:
        False if the shell should exit, True to continue.
    """
    line = input_line.strip()
    if not line:
        return True

    # Built-in shell commands
    if line in ("exit", "quit", "q"):
        return False

    if line == "help":
        _print_help()
        return True

    if line == "clear":
        import os
        os.system("clear")
        return True

    if line == "version":
        console.print(f"DeployCraft v[bold cyan]{__version__}[/bold cyan]")
        return True

    # Parse line into argument list
    try:
        args = shlex.split(line)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        return True

    # Invoke the typer app by temporarily replacing sys.argv
    # This is the cleanest approach that preserves interactive prompts/TTY
    original_argv = sys.argv[:]
    try:
        from deploycraft.cli import app

        sys.argv = ["deploycraft"] + args
        app(standalone_mode=False)

    except SystemExit:
        # typer raises SystemExit on --help, version, explicit exit()
        pass
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted[/dim]")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
    finally:
        sys.argv = original_argv

    return True


def run_shell() -> None:
    """Start the interactive DeployCraft shell (REPL).

    Displays a welcome banner, sets up readline for history and tab
    completion, then enters the read-eval-print loop.
    """
    console.print(
        Panel(
            f"[bold blue]DeployCraft[/bold blue] v{__version__} — Interactive Shell\n\n"
            "[dim]Type commands without the 'deploycraft' prefix.\n"
            "↑/↓ for history  |  Tab for completion  |  Ctrl+C or 'exit' to quit[/dim]",
            border_style="blue",
        )
    )

    _setup_readline()

    try:
        while True:
            try:
                line = input("\033[1;36mdeploycraft>\033[0m ")
                if not _execute_command(line):
                    break
            except KeyboardInterrupt:
                # First Ctrl+C — warn, don't exit
                console.print(
                    "\n[dim]Press Ctrl+C again or type 'exit' to quit.[/dim]"
                )
                try:
                    line = input("\033[1;36mdeploycraft>\033[0m ")
                    if not _execute_command(line):
                        break
                except (KeyboardInterrupt, EOFError):
                    break
            except EOFError:
                # Ctrl+D — exit gracefully
                break
    finally:
        _save_history()
        console.print("\n[dim]Goodbye![/dim]")
