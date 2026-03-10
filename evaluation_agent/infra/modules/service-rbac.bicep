// Assigns RBAC roles for Function App and Container App managed identities
// on the Foundry Cognitive Services account for evaluations and VoiceLive access.

@description('Name of the Foundry account (Cognitive Services) in the same resource group')
param foundryAccountName string

@description('Function App managed identity principal ID')
param functionAppPrincipalId string

@description('Container App managed identity principal ID (optional)')
param containerAppPrincipalId string = ''

@description('Storage account name for Container App blob/table access')
param storageAccountName string = ''

// Role definition IDs
var azureAiDeveloperRoleId = '64702f94-c441-49e6-a78b-ef80e0188fee'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageTableDataContributorRoleId = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'

// Reference existing resources
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = if (!empty(storageAccountName)) {
  name: storageAccountName
}

// Function App → Foundry: Azure AI Developer (evaluations data plane)
resource funcAiDeveloper 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, functionAppPrincipalId, azureAiDeveloperRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiDeveloperRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Function App → Foundry: Cognitive Services User (general API access)
resource funcCsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, functionAppPrincipalId, cognitiveServicesUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Container App → Foundry: Cognitive Services User (VoiceLive access)
resource caCSUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerAppPrincipalId)) {
  name: guid(foundryAccount.id, containerAppPrincipalId, cognitiveServicesUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Container App → Storage: Blob Data Contributor
resource caBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerAppPrincipalId) && !empty(storageAccountName)) {
  name: guid(storageAccount.id, containerAppPrincipalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Container App → Storage: Table Data Contributor
resource caTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(containerAppPrincipalId) && !empty(storageAccountName)) {
  name: guid(storageAccount.id, containerAppPrincipalId, storageTableDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Function App → Storage: Blob Data Contributor (dataset/results access)
resource funcBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountName)) {
  name: guid(storageAccount.id, functionAppPrincipalId, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Function App → Storage: Table Data Contributor (session configs, job status fallback)
resource funcTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(storageAccountName)) {
  name: guid(storageAccount.id, functionAppPrincipalId, storageTableDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageTableDataContributorRoleId)
    principalId: functionAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}
