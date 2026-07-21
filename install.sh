#!/bin/bash
# DeployCraft Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Shamsulhaq/deploycraft/main/install.sh | bash
#
# This installs DeployCraft globally so it works from any directory, any user session.

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "${GREEN}╭────────────────────────────────────╮${NC}"
echo -e "${GREEN}│   DeployCraft Installer            │${NC}"
echo -e "${GREEN}╰────────────────────────────────────╯${NC}"
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    OS_VERSION=$VERSION_ID
else
    echo -e "${RED}Error: Cannot detect OS. Only Linux is supported.${NC}"
    exit 1
fi

echo -e "  Detected: ${GREEN}$PRETTY_NAME${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
    echo -e "  Running as: $(whoami) (will use sudo)"
else
    SUDO=""
    echo -e "  Running as: root"
fi

echo ""

# Install Python3 + pip if missing
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}→ Installing Python3...${NC}"
    if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
        $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3 python3-pip python3-venv
    elif [[ "$OS" == "centos" || "$OS" == "rhel" || "$OS" == "fedora" || "$OS" == "amzn" ]]; then
        $SUDO dnf install -y python3 python3-pip || $SUDO yum install -y python3 python3-pip
    fi
fi

# Ensure git is installed (needed to install from GitHub)
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}→ Installing git...${NC}"
    if [[ "$OS" == "ubuntu" || "$OS" == "debian" ]]; then
        $SUDO apt-get install -y -qq git
    elif [[ "$OS" == "centos" || "$OS" == "rhel" || "$OS" == "fedora" || "$OS" == "amzn" ]]; then
        $SUDO dnf install -y git || $SUDO yum install -y git
    fi
fi

# Method: Install into /opt and symlink to /usr/local/bin (works globally for ALL users)
INSTALL_DIR="/opt/deploycraft"
BIN_LINK="/usr/local/bin/deploycraft"

echo -e "→ Installing DeployCraft to ${GREEN}$INSTALL_DIR${NC}..."

# Create isolated venv in /opt
$SUDO rm -rf "$INSTALL_DIR"
$SUDO python3 -m venv "$INSTALL_DIR"

# Install deploycraft into the venv
$SUDO "$INSTALL_DIR/bin/pip" install --upgrade pip -q
$SUDO "$INSTALL_DIR/bin/pip" install "git+https://github.com/Shamsulhaq/deploycraft.git" -q

# Create global symlink in /usr/local/bin (always in PATH for every user)
$SUDO rm -f "$BIN_LINK"
$SUDO ln -s "$INSTALL_DIR/bin/deploycraft" "$BIN_LINK"

echo ""

# Verify
if command -v deploycraft &> /dev/null; then
    VERSION=$(deploycraft --version 2>&1 | head -1)
    echo -e "${GREEN}✓ DeployCraft installed successfully!${NC}"
    echo -e "  Version: $VERSION"
    echo -e "  Command: deploycraft"
    echo -e "  Location: $BIN_LINK → $INSTALL_DIR/bin/deploycraft"
    echo ""
    echo -e "  Get started:"
    echo -e "    ${GREEN}deploycraft init${NC}      # First-time setup"
    echo -e "    ${GREEN}deploycraft deploy${NC}    # Deploy a project"
    echo -e "    ${GREEN}deploycraft${NC}           # Interactive shell"
    echo ""
else
    echo -e "${RED}✗ Installation failed. Please report this issue.${NC}"
    exit 1
fi
