#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Post-deploy hook for azd - runs after code deployment.
.DESCRIPTION
    This script is called by azd after the application code is deployed.
    It sets up the Foundry agent.
#>

$ErrorActionPreference = "Stop"

Write-Host "===== Post-Deploy Hook ====="

# Get outputs from azd
$functionAppUrl = $env:AZURE_FUNCTION_APP_URL
$connectionName = $env:AZURE_AGENT_CONNECTION_NAME

if (-not $functionAppUrl) {
    Write-Host "ERROR: AZURE_FUNCTION_APP_URL not set" -ForegroundColor Red
    exit 1
}

Write-Host "Function App URL: $functionAppUrl"
Write-Host "Connection Name: $connectionName"

# Setup agent (update if exists)
$scriptDir = $PSScriptRoot
$agentScript = "$scriptDir\setup-agent.ps1"

if ($connectionName) {
    & $agentScript -FunctionAppUrl $functionAppUrl -ConnectionName $connectionName -Update
} else {
    & $agentScript -FunctionAppUrl $functionAppUrl -Update
}

Write-Host "`n===== Post-Deploy Complete ====="
