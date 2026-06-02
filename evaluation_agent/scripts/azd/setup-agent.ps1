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
    [string]$Model = "",
    
    [Parameter(Mandatory=$false)]
    [switch]$Update
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up Foundry Agent..."
Write-Host "  Function App URL: $FunctionAppUrl"

# Navigate to agent directory
$agentDir = Join-Path $PSScriptRoot "..\.."
Push-Location $agentDir

# Resolve a Python interpreter that has the project dependencies (notably
# azure-ai-projects>=2.2.0) installed. Falling back to bare `python` on PATH
# can pick up a stale/global interpreter (e.g. an older azure-ai-projects that
# lacks OpenApiTool), causing setup_agent_openapi.py to fail with an ImportError.
# Priority: active virtual env > repo .venv > python/python3 on PATH.
function Resolve-ProjectPython {
    param([string]$RepoDir)

    $roots = @()
    if ($env:VIRTUAL_ENV) { $roots += $env:VIRTUAL_ENV }          # whatever env the user activated
    $roots += (Join-Path $RepoDir ".venv")                         # evaluation_agent/.venv
    $roots += (Join-Path (Join-Path $RepoDir "..") ".venv")        # repo-root .venv

    foreach ($root in $roots) {
        foreach ($rel in @("Scripts/python.exe", "bin/python")) {  # Windows, then POSIX
            $candidate = Join-Path $root $rel
            if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
        }
    }

    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }

    throw "No Python interpreter found. Activate the project virtual environment (.venv) or install Python with azure-ai-projects>=2.2.0."
}

$python = Resolve-ProjectPython -RepoDir $agentDir
Write-Host "  Python: $python"

# Preflight: ensure the resolved interpreter actually has a compatible
# azure-ai-projects (>=2.2.0, which exposes OpenApiTool). This turns a cryptic
# ImportError deep inside setup_agent_openapi.py into a clear, actionable error,
# regardless of whether the interpreter came from VIRTUAL_ENV, .venv, or PATH.
& $python -c "import azure.ai.projects.models as m, sys; sys.exit(0 if hasattr(m, 'OpenApiTool') else 3)" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python interpreter '$python' lacks a compatible azure-ai-projects (need >=2.2.0 with OpenApiTool). Activate the project .venv or run: pip install -r requirements.txt"
}

try {
    $args = @("setup_agent_openapi.py", "--function-url", $FunctionAppUrl)
    
    if ($ConnectionName) {
        $args += "--connection-name"
        $args += $ConnectionName
        Write-Host "  Connection: $ConnectionName"
    }
    
    if ($Model) {
        $args += "--model"
        $args += $Model
        Write-Host "  Model: $Model"
    }
    
    if ($Update) {
        $args += "--update"
        Write-Host "  Mode: Update existing agent"
    } else {
        Write-Host "  Mode: Create new agent"
    }
    
    Write-Host "`nRunning setup script..."
    & $python @args
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to setup agent"
    }
    
    Write-Host "`n✓ Agent setup complete" -ForegroundColor Green
    
} finally {
    Pop-Location
}
