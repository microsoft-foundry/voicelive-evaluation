#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Creates or updates the Foundry Agent with OpenAPI tools.
.DESCRIPTION
    This script creates/updates the VoiceLive Evaluation Agent in Azure AI Foundry,
    configuring it with OpenAPI tools that call the Azure Functions API.
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$FunctionAppUrl,
    
    [Parameter(Mandatory=$false)]
    [string]$ConnectionName = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$Update
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up Foundry Agent..."
Write-Host "  Function App URL: $FunctionAppUrl"

# Navigate to agent directory
$agentDir = Join-Path $PSScriptRoot "..\.."
Push-Location $agentDir

try {
    $args = @("setup_agent_openapi.py", "--function-url", $FunctionAppUrl)
    
    if ($ConnectionName) {
        $args += "--connection-name"
        $args += $ConnectionName
        Write-Host "  Connection: $ConnectionName"
    }
    
    if ($Update) {
        $args += "--update"
        Write-Host "  Mode: Update existing agent"
    } else {
        Write-Host "  Mode: Create new agent"
    }
    
    Write-Host "`nRunning setup script..."
    python @args
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to setup agent"
    }
    
    Write-Host "`n✓ Agent setup complete" -ForegroundColor Green
    
} finally {
    Pop-Location
}
