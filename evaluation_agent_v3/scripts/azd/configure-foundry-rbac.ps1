<#
.SYNOPSIS
    Configure RBAC for Foundry project tracing.

.DESCRIPTION
    Assigns the Azure AI User role to the Foundry project's managed identity
    to enable tracing in Application Insights.

.PARAMETER FoundryAccountResourceId
    Full resource ID of the Foundry account (Cognitive Services account).
    Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{name}

.PARAMETER FoundryProjectPrincipalId
    The principal ID (object ID) of the Foundry project's managed identity.
    Can be found in Foundry Portal > Project Settings > Identity

.EXAMPLE
    .\configure-foundry-rbac.ps1 `
        -FoundryAccountResourceId "/subscriptions/.../Microsoft.CognitiveServices/accounts/myaccount" `
        -FoundryProjectPrincipalId "12345678-1234-1234-1234-123456789012"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$FoundryAccountResourceId,

    [Parameter(Mandatory = $true)]
    [string]$FoundryProjectPrincipalId
)

$ErrorActionPreference = "Stop"

# Azure AI User role definition ID
$AzureAiUserRoleId = "e47c6f54-e4a2-4754-9501-8e0985b135e1"

Write-Host "Configuring Foundry RBAC for tracing..." -ForegroundColor Cyan
Write-Host "  Foundry Account: $FoundryAccountResourceId"
Write-Host "  Project Principal ID: $FoundryProjectPrincipalId"
Write-Host "  Role: Azure AI User ($AzureAiUserRoleId)"

# Check if role assignment already exists
$existing = az role assignment list `
    --scope $FoundryAccountResourceId `
    --assignee $FoundryProjectPrincipalId `
    --role $AzureAiUserRoleId `
    --output json 2>$null | ConvertFrom-Json

if ($existing -and $existing.Count -gt 0) {
    Write-Host "Role assignment already exists. Skipping." -ForegroundColor Yellow
    exit 0
}

# Create the role assignment
Write-Host "Creating role assignment..."
$result = az role assignment create `
    --scope $FoundryAccountResourceId `
    --assignee-object-id $FoundryProjectPrincipalId `
    --assignee-principal-type ServicePrincipal `
    --role $AzureAiUserRoleId `
    --description "Azure AI User role for Foundry project tracing" `
    --output json | ConvertFrom-Json

if ($result) {
    Write-Host "Successfully assigned Azure AI User role!" -ForegroundColor Green
    Write-Host "  Role Assignment ID: $($result.id)"
    Write-Host ""
    Write-Host "NOTE: Recently granted permissions may take several minutes to propagate." -ForegroundColor Yellow
} else {
    Write-Error "Failed to create role assignment"
    exit 1
}
