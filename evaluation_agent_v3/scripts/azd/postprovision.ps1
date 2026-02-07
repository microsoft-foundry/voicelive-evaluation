#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Post-provision hook for azd - runs after infrastructure is created.
.DESCRIPTION
    This script is called by azd after the Bicep infrastructure is deployed.
    It seeds the session configs table.
#>

$ErrorActionPreference = "Stop"

Write-Host "===== Post-Provision Hook ====="

# Get outputs from azd
$storageAccountName = $env:AZURE_STORAGE_ACCOUNT_NAME
$resourceGroup = $env:AZURE_RESOURCE_GROUP

if (-not $storageAccountName) {
    Write-Host "ERROR: AZURE_STORAGE_ACCOUNT_NAME not set" -ForegroundColor Red
    exit 1
}

Write-Host "Storage Account: $storageAccountName"
Write-Host "Resource Group: $resourceGroup"

# Seed session configs
Write-Host "`n----- Seeding Session Configs -----"
$scriptDir = $PSScriptRoot
& "$scriptDir\seed-session-configs.ps1" -StorageAccountName $storageAccountName

Write-Host "`n===== Post-Provision Complete ====="
