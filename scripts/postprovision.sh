#!/usr/bin/env bash
set -euo pipefail

echo "=== Post-provision: Configuring resources ==="

# Check if PowerShell is available (preferred — the canonical scripts are PowerShell)
if command -v pwsh &> /dev/null; then
    echo "PowerShell found. Running canonical post-provision script..."
    pwsh evaluation_agent/scripts/azd/postprovision.ps1
else
    echo ""
    echo "WARNING: PowerShell (pwsh) not found."
    echo "The post-provision script handles RBAC assignments, storage table seeding,"
    echo "and Foundry connection setup. Without it, you'll need to run these manually."
    echo ""
    echo "To install PowerShell in this environment:"
    echo "  sudo apt-get update && sudo apt-get install -y powershell"
    echo "  pwsh evaluation_agent/scripts/azd/postprovision.ps1"
    echo ""
    echo "Or run from a Windows/macOS machine with PowerShell installed."
    echo ""
    # Exit non-zero so the user knows this step was skipped
    exit 1
fi

echo "=== Post-provision complete ==="
