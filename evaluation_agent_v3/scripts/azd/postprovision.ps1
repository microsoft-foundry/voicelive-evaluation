#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Post-provision hook for azd - runs after infrastructure is created.
.DESCRIPTION
    This script is called by azd after the Bicep infrastructure is deployed.
    It handles:
    1. Seed session configs table
    2. Assign RBAC roles to Function App for Foundry access
    3. Create Foundry connection for Function App key
    4. Set CONTAINER_APP_URL on Function App
#>

$ErrorActionPreference = "Stop"

Write-Host "===== Post-Provision Hook =====" -ForegroundColor Cyan

# Get outputs from azd
$storageAccountName = $env:AZURE_STORAGE_ACCOUNT_NAME
$resourceGroup = $env:AZURE_RESOURCE_GROUP
$functionAppName = $env:AZURE_FUNCTION_APP_NAME
$functionAppUrl = $env:AZURE_FUNCTION_APP_URL
$functionAppPrincipalId = $env:AZURE_FUNCTION_APP_PRINCIPAL_ID
$containerAppUrl = $env:AZURE_CONTAINER_APP_URL
$foundryAccountResourceId = $env:FOUNDRY_ACCOUNT_RESOURCE_ID
$foundryProjectEndpoint = $env:PROJECT_ENDPOINT

if (-not $storageAccountName) {
    Write-Host "ERROR: AZURE_STORAGE_ACCOUNT_NAME not set" -ForegroundColor Red
    exit 1
}

Write-Host "Storage Account: $storageAccountName"
Write-Host "Resource Group: $resourceGroup"
Write-Host "Function App: $functionAppName"

$scriptDir = $PSScriptRoot

# ===== 1. Seed Session Configs =====
Write-Host "`n----- 1. Seeding Session Configs -----" -ForegroundColor Yellow
& "$scriptDir\seed-session-configs.ps1" -StorageAccountName $storageAccountName

# ===== 2. Set Container App URL on Function App =====
if ($containerAppUrl) {
    Write-Host "`n----- 2. Setting Container App URL -----" -ForegroundColor Yellow
    Write-Host "Container App URL: $containerAppUrl"
    az functionapp config appsettings set `
        --name $functionAppName `
        --resource-group $resourceGroup `
        --settings "CONTAINER_APP_URL=$containerAppUrl" `
        --output none 2>$null
    Write-Host "  CONTAINER_APP_URL set on Function App" -ForegroundColor Green
} else {
    Write-Host "`n----- 2. Skipping Container App URL (not deployed) -----" -ForegroundColor DarkGray
}

# ===== 3. Assign RBAC for Foundry Access =====
if ($foundryAccountResourceId -and $functionAppPrincipalId) {
    Write-Host "`n----- 3. Assigning RBAC Roles to Function App -----" -ForegroundColor Yellow
    Write-Host "  Function App Principal: $functionAppPrincipalId"
    Write-Host "  Foundry Account: $foundryAccountResourceId"

    # Azure AI Developer role (for evaluations data plane)
    $aiDeveloperRole = "64702f94-c441-49e6-a78b-ef80e0188fee"
    $existing = az role assignment list --scope $foundryAccountResourceId --assignee $functionAppPrincipalId --role $aiDeveloperRole --output json 2>$null | ConvertFrom-Json
    if (-not $existing -or $existing.Count -eq 0) {
        Write-Host "  Assigning Azure AI Developer role..."
        az role assignment create `
            --scope $foundryAccountResourceId `
            --assignee-object-id $functionAppPrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $aiDeveloperRole `
            --output none 2>$null
        Write-Host "  Azure AI Developer role assigned" -ForegroundColor Green
    } else {
        Write-Host "  Azure AI Developer role already assigned" -ForegroundColor DarkGray
    }

    # Cognitive Services User role (for general API access)
    $csUserRole = "a97b65f3-24c7-4388-baec-2e87135dc908"
    $existing = az role assignment list --scope $foundryAccountResourceId --assignee $functionAppPrincipalId --role $csUserRole --output json 2>$null | ConvertFrom-Json
    if (-not $existing -or $existing.Count -eq 0) {
        Write-Host "  Assigning Cognitive Services User role..."
        az role assignment create `
            --scope $foundryAccountResourceId `
            --assignee-object-id $functionAppPrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $csUserRole `
            --output none 2>$null
        Write-Host "  Cognitive Services User role assigned" -ForegroundColor Green
    } else {
        Write-Host "  Cognitive Services User role already assigned" -ForegroundColor DarkGray
    }

    Write-Host "  NOTE: Role propagation may take several minutes" -ForegroundColor Yellow
} else {
    Write-Host "`n----- 3. Skipping RBAC (FOUNDRY_ACCOUNT_RESOURCE_ID not set) -----" -ForegroundColor DarkGray
    Write-Host "  Set FOUNDRY_ACCOUNT_RESOURCE_ID to enable automatic RBAC assignment"
}

# ===== 4. Create Foundry Connection =====
if ($foundryProjectEndpoint -and $functionAppName) {
    Write-Host "`n----- 4. Creating Foundry Connection -----" -ForegroundColor Yellow

    # Get Function App key
    $funcKey = az functionapp keys list --name $functionAppName --resource-group $resourceGroup --query "functionKeys.default" -o tsv 2>$null
    if (-not $funcKey) {
        Write-Host "  WARNING: Could not retrieve function key. Skipping connection creation." -ForegroundColor Yellow
        Write-Host "  Run manually after deploy: az functionapp keys list --name $functionAppName --resource-group $resourceGroup"
    } else {
        # Parse project endpoint to get ARM path components
        # Endpoint format: https://<account>.services.ai.azure.com/api/projects/<project>
        $foundryConnectionName = $env:FOUNDRY_CONNECTION_NAME
        if (-not $foundryConnectionName) { $foundryConnectionName = "voicelive-eval-api-key" }

        if ($foundryAccountResourceId) {
            # Build connection resource URI from account resource ID + project name
            # Account ID format: /subscriptions/.../providers/Microsoft.CognitiveServices/accounts/<account>
            $projectName = ($foundryProjectEndpoint -split "/projects/")[-1]
            $connectionUri = "$foundryAccountResourceId/projects/$projectName/connections/$foundryConnectionName"
            $apiVersion = "2025-06-01"
            $uri = "https://management.azure.com${connectionUri}?api-version=$apiVersion"

            $body = @{
                properties = @{
                    category = "CustomKeys"
                    target = $functionAppUrl
                    authType = "CustomKeys"
                    credentials = @{
                        keys = @{
                            code = $funcKey
                        }
                    }
                    metadata = @{
                        displayName = "VoiceLive Evaluation Function Key"
                    }
                }
            } | ConvertTo-Json -Depth 5

            $tempFile = [System.IO.Path]::GetTempFileName()
            $body | Out-File -FilePath $tempFile -Encoding utf8

            Write-Host "  Creating connection: $foundryConnectionName"
            $result = az rest --method PUT --uri $uri --body "@$tempFile" --headers "Content-Type=application/json" 2>&1
            Remove-Item $tempFile -ErrorAction SilentlyContinue

            if ($LASTEXITCODE -eq 0) {
                Write-Host "  Connection created: $foundryConnectionName" -ForegroundColor Green
                # Store connection ID for post-deploy agent setup
                $connectionId = ($result | ConvertFrom-Json).id
                Write-Host "  Connection ID: $connectionId"
                # Set as azd env var for post-deploy script
                azd env set AZURE_AGENT_CONNECTION_ID $connectionId 2>$null
            } else {
                Write-Host "  WARNING: Connection creation failed. Create manually in Foundry Portal." -ForegroundColor Yellow
                Write-Host "  $result"
            }
        } else {
            Write-Host "  WARNING: Cannot create connection - FOUNDRY_ACCOUNT_RESOURCE_ID required" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "`n----- 4. Skipping Connection (PROJECT_ENDPOINT not set) -----" -ForegroundColor DarkGray
}

Write-Host "`n===== Post-Provision Complete =====" -ForegroundColor Cyan
