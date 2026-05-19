#!/usr/bin/env bash
set -euo pipefail

echo "===== Deployment Complete ====="

# Retrieve deployment outputs
FUNC_URL="${AZURE_FUNCTION_APP_URL:-<not set>}"
CA_URL="${AZURE_CONTAINER_APP_URL:-<not set>}"

echo ""
echo "  Function App URL: $FUNC_URL"
echo "  Container App:    $CA_URL"
echo ""

# Run canonical post-deploy if PowerShell is available
if command -v pwsh &> /dev/null; then
    echo "Running post-deploy setup..."
    pwsh evaluation_agent/scripts/azd/postdeploy.ps1
else
    echo "Next steps (run the evaluation harness locally):"
    echo ""
    echo "  1. cd evaluation_harness"
    echo "  2. cp .sample_env .env"
    echo "  3. Edit .env with your Voice Live endpoint"
    echo "  4. python voice_agent_evaluation.py --config configs/sample_vad_realtime.json"
    echo ""
    echo "For full agent setup, install PowerShell and run:"
    echo "  pwsh evaluation_agent/scripts/azd/postdeploy.ps1"
fi

echo ""
echo "===== Done ====="
