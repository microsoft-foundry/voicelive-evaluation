// Main Bicep orchestration for VoiceLive Evaluation Agent
// Deploys: AI Services (Foundry), Storage Account, Container Apps Environment

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, staging, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Name of the existing Azure AI Foundry project (optional - creates new if empty)')
param existingFoundryProject string = ''

// Tags for all resources
var tags = {
  'azd-env-name': environmentName
  'application': 'voicelive-evaluation-agent'
}

// Resource naming
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var abbrs = {
  resourceGroup: 'rg-'
  storageAccount: 'st'
  aiServices: 'ai-'
  containerAppsEnvironment: 'cae-'
  containerApp: 'ca-'
  containerRegistry: 'cr'
  logAnalytics: 'log-'
}

// Resource Group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: '${abbrs.resourceGroup}${environmentName}'
  location: location
  tags: tags
}

// Log Analytics Workspace (required for Container Apps)
module logAnalytics 'modules/log-analytics.bicep' = {
  scope: rg
  name: 'logAnalytics'
  params: {
    name: '${abbrs.logAnalytics}${resourceToken}'
    location: location
    tags: tags
  }
}

// AI Services (Azure OpenAI / Foundry)
module aiServices 'modules/ai-services.bicep' = {
  scope: rg
  name: 'aiServices'
  params: {
    name: '${abbrs.aiServices}${resourceToken}'
    location: location
    tags: tags
  }
}

// Storage Account for datasets and outputs
module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    name: '${abbrs.storageAccount}${resourceToken}'
    location: location
    tags: tags
  }
}

// Container Registry
module containerRegistry 'modules/container-registry.bicep' = {
  scope: rg
  name: 'containerRegistry'
  params: {
    name: '${abbrs.containerRegistry}${resourceToken}'
    location: location
    tags: tags
  }
}

// Container Apps Environment
module containerAppsEnvironment 'modules/container-apps-environment.bicep' = {
  scope: rg
  name: 'containerAppsEnvironment'
  params: {
    name: '${abbrs.containerAppsEnvironment}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
  }
}

// Container App for the agent
module containerApp 'modules/container-app.bicep' = {
  scope: rg
  name: 'containerApp'
  params: {
    name: '${abbrs.containerApp}${resourceToken}'
    location: location
    tags: tags
    containerAppsEnvironmentId: containerAppsEnvironment.outputs.id
    containerRegistryName: containerRegistry.outputs.name
    aiServicesEndpoint: aiServices.outputs.endpoint
    storageAccountName: storage.outputs.name
  }
}

// RBAC: Grant Container App access to Storage
module storageRbac 'modules/storage-rbac.bicep' = {
  scope: rg
  name: 'storageRbac'
  params: {
    storageAccountName: storage.outputs.name
    principalId: containerApp.outputs.identityPrincipalId
  }
}

// RBAC: Grant Container App access to AI Services
module aiServicesRbac 'modules/ai-services-rbac.bicep' = {
  scope: rg
  name: 'aiServicesRbac'
  params: {
    aiServicesName: aiServices.outputs.name
    principalId: containerApp.outputs.identityPrincipalId
  }
}

// Outputs for azd
output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_STORAGE_ACCOUNT string = storage.outputs.name
output AZURE_FOUNDRY_ENDPOINT string = aiServices.outputs.endpoint
output AZURE_CONTAINER_REGISTRY string = containerRegistry.outputs.name
output AZURE_CONTAINER_APP_URL string = containerApp.outputs.url
output AZURE_CONTAINER_APP_NAME string = containerApp.outputs.name
