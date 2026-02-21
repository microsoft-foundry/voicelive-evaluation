// Azure AI Foundry Account + Project
// Creates a Cognitive Services account (kind: AIServices) and a Foundry project.
// The project endpoint is used by Function App and Container App for evaluations.

@description('Name for the Cognitive Services account')
param accountName string

@description('Location for resources')
param location string = resourceGroup().location

@description('Tags for resources')
param tags object = {}

@description('Name for the Foundry project')
param projectName string

@description('SKU for the Cognitive Services account')
param skuName string = 'S0'

@description('Model deployments to create (name, model, version, capacity)')
param modelDeployments array = []

// Cognitive Services account (kind: AIServices)
resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: skuName
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
    allowProjectManagement: true
  }
}

// Model deployments (sequential to avoid parent resource conflicts)
@batchSize(1)
resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [
  for deployment in modelDeployments: {
    parent: aiAccount
    name: deployment.name
    sku: {
      name: deployment.?sku ?? 'Standard'
      capacity: deployment.?capacity ?? 1
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: deployment.model
        version: deployment.?version ?? ''
      }
    }
  }
]

// Foundry project under the account (depends on deployments to avoid conflicts)
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiAccount
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'VoiceLive Evaluation Agent project'
  }
  dependsOn: [deployments]
}

// Outputs
output accountId string = aiAccount.id
output accountName string = aiAccount.name
output accountEndpoint string = 'https://${accountName}.services.ai.azure.com/'
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output accountPrincipalId string = aiAccount.identity.principalId
