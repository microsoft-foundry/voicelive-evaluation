#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Sets up Entra ID authentication for the VoiceLive Evaluation Function App.

.DESCRIPTION
    This script:
    1. Creates an App Registration for the Function App
    2. Configures the App Registration with the correct settings
    3. Updates the azd environment with the client ID
    4. Runs azd provision to apply Entra auth settings

.PARAMETER FunctionAppName
    Name of the Function App (optional - auto-detected from azd environment)

.EXAMPLE
    ./setup-entra-auth.ps1
#>

param(
    [string]$FunctionAppName
)

$ErrorActionPreference = "Stop"

Write-Host "=== VoiceLive Evaluation - Entra ID Auth Setup ===" -ForegroundColor Cyan

# Get azd environment values
Write-Host "`nReading azd environment..." -ForegroundColor Yellow
$envName = azd env get-value AZURE_ENV_NAME 2>$null
if (-not $envName) {
    Write-Error "No azd environment found. Run 'azd up' first."
    exit 1
}

$resourceGroup = azd env get-value AZURE_RESOURCE_GROUP 2>$null
if (-not $FunctionAppName) {
    $FunctionAppName = azd env get-value AZURE_FUNCTION_APP_NAME 2>$null
}

if (-not $FunctionAppName) {
    Write-Error "Function App name not found. Run 'azd up' first or provide -FunctionAppName parameter."
    exit 1
}

Write-Host "  Environment: $envName"
Write-Host "  Resource Group: $resourceGroup"
Write-Host "  Function App: $FunctionAppName"

# Check if App Registration already exists
$appName = "voicelive-eval-api-$envName"
Write-Host "`nChecking for existing App Registration '$appName'..." -ForegroundColor Yellow

$existingApp = az ad app list --display-name $appName --query "[0]" 2>$null | ConvertFrom-Json
if ($existingApp -and $existingApp.appId) {
    $clientId = $existingApp.appId
    Write-Host "  Found existing App Registration: $clientId" -ForegroundColor Green
} else {
    # Create App Registration using Graph REST API (handles service management reference)
    Write-Host "`nCreating App Registration..." -ForegroundColor Yellow
    
    # Get access token for Graph API
    $accessToken = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
    
    # Create app via REST API
    $body = @{
        displayName = $appName
        signInAudience = "AzureADMyOrg"
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod `
            -Uri "https://graph.microsoft.com/v1.0/applications" `
            -Method POST `
            -Headers @{ Authorization = "Bearer $accessToken"; "Content-Type" = "application/json" } `
            -Body $body
        
        $clientId = $response.appId
        $objectId = $response.id
        
        Write-Host "  Created App Registration: $clientId" -ForegroundColor Green
        
        # Wait for replication
        Start-Sleep -Seconds 5
        
        # Set App ID URI
        Write-Host "  Setting App ID URI..." -ForegroundColor Yellow
        $updateBody = @{
            identifierUris = @("api://$clientId")
        } | ConvertTo-Json
        
        Invoke-RestMethod `
            -Uri "https://graph.microsoft.com/v1.0/applications/$objectId" `
            -Method PATCH `
            -Headers @{ Authorization = "Bearer $accessToken"; "Content-Type" = "application/json" } `
            -Body $updateBody | Out-Null
        
        # Create Service Principal
        Write-Host "  Creating Service Principal..." -ForegroundColor Yellow
        $spBody = @{ appId = $clientId } | ConvertTo-Json
        
        Invoke-RestMethod `
            -Uri "https://graph.microsoft.com/v1.0/servicePrincipals" `
            -Method POST `
            -Headers @{ Authorization = "Bearer $accessToken"; "Content-Type" = "application/json" } `
            -Body $spBody | Out-Null
        
        Write-Host "  App Registration created successfully!" -ForegroundColor Green
    }
    catch {
        Write-Host "  REST API failed, falling back to az ad app create..." -ForegroundColor Yellow
        
        $app = az ad app create `
            --display-name $appName `
            --sign-in-audience AzureADMyOrg `
            --query "{appId: appId, id: id}" `
            --output json | ConvertFrom-Json
        
        if (-not $app -or -not $app.appId) {
            Write-Error "Failed to create App Registration. Please create it manually in Azure Portal."
            exit 1
        }
        
        $clientId = $app.appId
        $objectId = $app.id
        
        Write-Host "  Created App Registration: $clientId" -ForegroundColor Green
        
        # Set App ID URI
        Write-Host "  Setting App ID URI..." -ForegroundColor Yellow
        az ad app update --id $clientId --identifier-uris "api://$clientId" | Out-Null
        
        # Create Service Principal
        Write-Host "  Creating Service Principal..." -ForegroundColor Yellow
        az ad sp create --id $clientId | Out-Null
        
        Write-Host "  App Registration created successfully!" -ForegroundColor Green
    }
}

if (-not $clientId) {
    Write-Error "Failed to get Client ID. Please check App Registration status."
    exit 1
}

# Update azd environment
Write-Host "`nUpdating azd environment..." -ForegroundColor Yellow
azd env set ENABLE_ENTRA_AUTH "true"
azd env set ENTRA_CLIENT_ID "$clientId"

Write-Host "  ENABLE_ENTRA_AUTH=true"
Write-Host "  ENTRA_CLIENT_ID=$clientId"

# Run azd provision to apply changes
Write-Host "`nApplying Entra ID configuration to Function App..." -ForegroundColor Yellow
Write-Host "(This will run 'azd provision')" -ForegroundColor Gray

$confirm = Read-Host "Continue? (y/N)"
if ($confirm -eq 'y' -or $confirm -eq 'Y') {
    azd provision --no-prompt
    
    Write-Host "`n=== Entra ID Auth Setup Complete ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Update the agent to use managed identity auth:"
    Write-Host "   python setup_agent_openapi.py --function-url https://$FunctionAppName.azurewebsites.net/api --entra-auth --client-id $clientId --update"
    Write-Host ""
    Write-Host "2. The agent will use its managed identity to authenticate"
    Write-Host "   with the Function App using audience: api://$clientId"
} else {
    Write-Host "`nSkipped provisioning. Run 'azd provision' manually when ready." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "App Registration Details:" -ForegroundColor Cyan
Write-Host "  Display Name: $appName"
Write-Host "  Client ID: $clientId"
Write-Host "  App ID URI: api://$clientId"
