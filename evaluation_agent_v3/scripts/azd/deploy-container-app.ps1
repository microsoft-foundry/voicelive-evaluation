#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Builds and deploys the VoiceLive Container App.
.DESCRIPTION
    This script builds the Docker image for the VoiceLive processor,
    pushes it to ACR, and updates the Container App.
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$AcrName,
    
    [Parameter(Mandatory=$true)]
    [string]$ContainerAppName,
    
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"

Write-Host "Building and deploying VoiceLive Container App..."
Write-Host "  ACR: $AcrName"
Write-Host "  Container App: $ContainerAppName"
Write-Host "  Resource Group: $ResourceGroup"

# Navigate to container app directory
$containerAppDir = Join-Path $PSScriptRoot "..\..\deploy\container-app"
Push-Location $containerAppDir

try {
    $imageName = "voicelive-processor"
    $fullImage = "$AcrName.azurecr.io/${imageName}:$ImageTag"
    
    Write-Host "`n1. Building Docker image in ACR..."
    az acr build --registry $AcrName --image "${imageName}:$ImageTag" .
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to build Docker image"
    }
    
    Write-Host "`n2. Updating Container App..."
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --image $fullImage
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to update Container App"
    }
    
    Write-Host "`n✓ Container App deployed successfully" -ForegroundColor Green
    Write-Host "  Image: $fullImage"
    
} finally {
    Pop-Location
}
