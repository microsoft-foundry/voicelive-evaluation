// This module assigns the Azure AI User role to enable tracing
// NOTE: The Foundry account must be in the SAME resource group as this deployment
// For cross-resource-group scenarios, use the scripts/azd/configure-foundry-rbac.ps1 script

@description('The principal ID of the Foundry project managed identity')
param foundryProjectPrincipalId string

@description('The name of the Foundry account (Cognitive Services account) in the same resource group')
param foundryAccountName string

// Azure AI User role definition ID
// Grants access to manage AI projects and accounts
// https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/ai-machine-learning
var azureAiUserRoleId = 'e47c6f54-e4a2-4754-9501-8e0985b135e1'

// Reference the existing Foundry account (must be in same resource group)
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

// Assign Azure AI User role to the Foundry project's managed identity
// This enables tracing access for the project
resource azureAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, foundryProjectPrincipalId, azureAiUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUserRoleId)
    principalId: foundryProjectPrincipalId
    principalType: 'ServicePrincipal'
    description: 'Azure AI User role for Foundry project tracing'
  }
}

output roleAssignmentId string = azureAiUserRole.id


