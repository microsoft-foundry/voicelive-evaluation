$ErrorActionPreference = "Stop"

Write-Host "=== Pre-provision validation ==="

# Validate required environment variables
if (-not $env:AZURE_ENV_NAME) { throw "AZURE_ENV_NAME is required. Run 'azd init' first." }
if (-not $env:AZURE_LOCATION) { throw "AZURE_LOCATION is required. Run 'azd env set AZURE_LOCATION <region>'." }

# Voice Live + Foundry Evaluators are only confirmed in these regions
$validRegions = @("eastus2", "swedencentral")

if ($env:AZURE_LOCATION -notin $validRegions) {
    Write-Host ""
    Write-Error "Region '$($env:AZURE_LOCATION)' is not confirmed for Voice Live + Foundry Evaluators."
    Write-Host ""
    Write-Host "Confirmed regions: $($validRegions -join ', ')"
    Write-Host ""
    Write-Host "To fix: azd env set AZURE_LOCATION eastus2"
    Write-Host "  or:   azd env set AZURE_LOCATION swedencentral"
    Write-Host ""
    Write-Host "Other regions may work but are not validated. To override:"
    Write-Host "  azd env set SKIP_REGION_VALIDATION true"
    exit 1
}

Write-Host "Region validation passed: $env:AZURE_LOCATION"
Write-Host "=== Pre-provision validation complete ==="
