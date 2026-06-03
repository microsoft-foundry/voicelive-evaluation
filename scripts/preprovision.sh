#!/usr/bin/env bash
set -euo pipefail

echo "=== Pre-provision validation ==="

# Validate required environment variables
: "${AZURE_ENV_NAME:?AZURE_ENV_NAME is required. Run 'azd init' first.}"
: "${AZURE_LOCATION:?AZURE_LOCATION is required. Run 'azd env set AZURE_LOCATION <region>'.}"

# Voice Live + Foundry Evaluators are only confirmed in these regions
VALID_REGIONS=("eastus2" "swedencentral")

REGION_VALID=false
for region in "${VALID_REGIONS[@]}"; do
    if [[ "$AZURE_LOCATION" == "$region" ]]; then
        REGION_VALID=true
        break
    fi
done

if [[ "$REGION_VALID" != "true" ]]; then
    echo ""
    echo "ERROR: Region '$AZURE_LOCATION' is not confirmed for Voice Live + Foundry Evaluators."
    echo ""
    echo "Confirmed regions: ${VALID_REGIONS[*]}"
    echo ""
    echo "To fix: azd env set AZURE_LOCATION eastus2"
    echo "  or:   azd env set AZURE_LOCATION swedencentral"
    echo ""
    echo "Other regions may work but are not validated. To override:"
    echo "  azd env set SKIP_REGION_VALIDATION true"
    exit 1
fi

echo "Region validation passed: $AZURE_LOCATION"
echo "=== Pre-provision validation complete ==="
