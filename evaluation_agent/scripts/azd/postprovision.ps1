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
$containerAppName = $env:AZURE_CONTAINER_APP_NAME
$containerAppUrl = $env:AZURE_CONTAINER_APP_URL
$containerAppPrincipalId = $env:AZURE_CONTAINER_APP_PRINCIPAL_ID
$containerAppEntraClientId = $env:CONTAINER_APP_ENTRA_CLIENT_ID
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

# ===== 2. Set Container App URL and Entra Client ID on Function App =====
if ($containerAppUrl) {
    Write-Host "`n----- 2. Setting Container App URL & Entra Auth -----" -ForegroundColor Yellow
    Write-Host "Container App URL: $containerAppUrl"
    az functionapp config appsettings set `
        --name $functionAppName `
        --resource-group $resourceGroup `
        --settings "CONTAINER_APP_URL=$containerAppUrl" `
        --output none 2>$null
    if ($containerAppEntraClientId) {
        Write-Host "Container App Entra Client ID: $containerAppEntraClientId"
        az functionapp config appsettings set `
            --name $functionAppName `
            --resource-group $resourceGroup `
            --settings "CONTAINER_APP_ENTRA_CLIENT_ID=$containerAppEntraClientId" `
            --output none 2>$null
    }
    Write-Host "  App settings configured on Function App" -ForegroundColor Green

    # Assign ContainerApp.Access app role to Function App MI
    if ($containerAppEntraClientId -and $functionAppPrincipalId) {
        Write-Host "`n  Assigning ContainerApp.Access app role to Function App MI..."
        
        # Get the service principal for the app registration
        $appSpId = az ad sp list --filter "appId eq '$containerAppEntraClientId'" --query "[0].id" -o tsv 2>$null
        if ($appSpId) {
            # Get the app role ID
            $appRoleId = az ad sp show --id $appSpId --query "appRoles[?value=='ContainerApp.Access'].id | [0]" -o tsv 2>$null
            
            if ($appRoleId) {
                # Check if assignment already exists
                $existingAssignment = az rest --method GET `
                    --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$appSpId/appRoleAssignedTo" `
                    --query "value[?principalId=='$functionAppPrincipalId' && appRoleId=='$appRoleId'] | [0]" `
                    2>$null | ConvertFrom-Json
                
                if (-not $existingAssignment) {
                    $body = @{
                        principalId = $functionAppPrincipalId
                        resourceId = $appSpId
                        appRoleId = $appRoleId
                    } | ConvertTo-Json

                    $tempFile = [System.IO.Path]::GetTempFileName()
                    $body | Out-File -FilePath $tempFile -Encoding utf8
                    
                    az rest --method POST `
                        --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$appSpId/appRoleAssignedTo" `
                        --body "@$tempFile" `
                        --headers "Content-Type=application/json" `
                        --output none 2>$null
                    Remove-Item $tempFile -ErrorAction SilentlyContinue
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "  ContainerApp.Access app role assigned to Function App MI" -ForegroundColor Green
                    } else {
                        Write-Host "  WARNING: Failed to assign app role. Assign manually in Azure Portal." -ForegroundColor Yellow
                    }
                } else {
                    Write-Host "  ContainerApp.Access app role already assigned" -ForegroundColor DarkGray
                }
            } else {
                Write-Host "  WARNING: ContainerApp.Access app role not found on service principal" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  WARNING: Service principal not found for $containerAppEntraClientId. Create with: az ad sp create --id $containerAppEntraClientId" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "`n----- 2. Skipping Container App settings (not deployed) -----" -ForegroundColor DarkGray
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

    # Foundry User role (for general API + VoiceLive access)
    $foundryUserRole = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
    $existing = az role assignment list --scope $foundryAccountResourceId --assignee $functionAppPrincipalId --role $foundryUserRole --output json 2>$null | ConvertFrom-Json
    if (-not $existing -or $existing.Count -eq 0) {
        Write-Host "  Assigning Foundry User role..."
        az role assignment create `
            --scope $foundryAccountResourceId `
            --assignee-object-id $functionAppPrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $foundryUserRole `
            --output none 2>$null
        Write-Host "  Foundry User role assigned" -ForegroundColor Green
    } else {
        Write-Host "  Foundry User role already assigned" -ForegroundColor DarkGray
    }

    Write-Host "  NOTE: Role propagation may take several minutes" -ForegroundColor Yellow

    # Container App RBAC (if deployed)
    if ($containerAppName) {
        $caPrincipalId = az containerapp identity show --name $containerAppName --resource-group $resourceGroup --query "principalId" -o tsv 2>$null
        if ($caPrincipalId) {
            Write-Host "`n  Container App Principal: $caPrincipalId"

            # Container App → Foundry: Foundry User (VoiceLive access)
            $existing = az role assignment list --scope $foundryAccountResourceId --assignee $caPrincipalId --role $foundryUserRole --output json 2>$null | ConvertFrom-Json
            if (-not $existing -or $existing.Count -eq 0) {
                Write-Host "  Assigning Foundry User to Container App..."
                az role assignment create --scope $foundryAccountResourceId --assignee-object-id $caPrincipalId --assignee-principal-type ServicePrincipal --role $foundryUserRole --output none 2>$null
                Write-Host "  Foundry User assigned to Container App" -ForegroundColor Green
            } else {
                Write-Host "  Foundry User already assigned to Container App" -ForegroundColor DarkGray
            }

            # Container App → Storage: Blob Data Contributor + Table Data Contributor
            $storageId = az storage account show --name $storageAccountName --resource-group $resourceGroup --query "id" -o tsv 2>$null
            if ($storageId) {
                $blobRole = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
                $tableRole = "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3"

                $existing = az role assignment list --scope $storageId --assignee $caPrincipalId --role $blobRole --output json 2>$null | ConvertFrom-Json
                if (-not $existing -or $existing.Count -eq 0) {
                    Write-Host "  Assigning Storage Blob Data Contributor to Container App..."
                    az role assignment create --scope $storageId --assignee-object-id $caPrincipalId --assignee-principal-type ServicePrincipal --role $blobRole --output none 2>$null
                    Write-Host "  Storage Blob Data Contributor assigned" -ForegroundColor Green
                } else {
                    Write-Host "  Storage Blob Data Contributor already assigned" -ForegroundColor DarkGray
                }

                $existing = az role assignment list --scope $storageId --assignee $caPrincipalId --role $tableRole --output json 2>$null | ConvertFrom-Json
                if (-not $existing -or $existing.Count -eq 0) {
                    Write-Host "  Assigning Storage Table Data Contributor to Container App..."
                    az role assignment create --scope $storageId --assignee-object-id $caPrincipalId --assignee-principal-type ServicePrincipal --role $tableRole --output none 2>$null
                    Write-Host "  Storage Table Data Contributor assigned" -ForegroundColor Green
                } else {
                    Write-Host "  Storage Table Data Contributor already assigned" -ForegroundColor DarkGray
                }
            }
        }
    }
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
