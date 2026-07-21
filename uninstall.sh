#!/bin/bash
# DeployCraft Uninstaller
# Usage: curl -fsSL https://raw.githubusercontent.com/Shamsulhaq/deploycraft/main/uninstall.sh | bash

set -e

if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

echo "Removing DeployCraft..."

$SUDO rm -f /usr/local/bin/deploycraft
$SUDO rm -rf /opt/deploycraft

echo "✓ DeployCraft uninstalled."
