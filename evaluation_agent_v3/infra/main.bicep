targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (used for resource naming)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Deploy the Container App runner for full evaluation support')
param deployRunner bool = false

@description('Enable Entra ID authentication on Function App')
param enableEntraAuth bool = false

@description('App Registration Client ID for Function App Entra ID auth')
param entraClientId string = ''

@description('AI Foundry project endpoint')
param projectEndpoint string = ''

@description('Voice Live API endpoint')
param voiceLiveEndpoint string = ''

@description('Voice Live model name')
param voiceLiveModel string = 'gpt-realtime'

@description('Voice Live API version')
param voiceLiveApiVersion string = '2025-10-01'

@description('Model deployment name')
param modelDeploymentName string = 'gpt-4o-mini'

@description('AOAI deployment name for metrics')
param aoaiDeploymentName string = 'gpt-4o-mini'

@description('AOAI reasoning deployment name')
param aoaiReasoningDeploymentName string = 'o4-mini'

// Generate unique suffix for resources
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

// Resource group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// Storage account for datasets and outputs
module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    name: 'st${resourceToken}'
    location: location
    tags: tags
  }
}

// Function App for tools API (Option A)
module functionApp 'modules/function-app.bicep' = {
  name: 'function-app'
  scope: rg
  params: {
    name: 'func-${resourceToken}'
    location: location
    tags: tags
    storageAccountName: storage.outputs.name
    enableEntraAuth: enableEntraAuth
    entraClientId: entraClientId
    appSettings: {
      AZURE_STORAGE_ACCOUNT: storage.outputs.name
      AZURE_STORAGE_DATASETS_CONTAINER: 'datasets'
      AZURE_STORAGE_OUTPUTS_CONTAINER: 'outputs'
      PROJECT_ENDPOINT: projectEndpoint
      AZURE_VOICE_LIVE_ENDPOINT: voiceLiveEndpoint
      AZURE_VOICE_LIVE_MODEL: voiceLiveModel
      AZURE_VOICE_LIVE_API_VERSION: voiceLiveApiVersion
      AOAI_DEPLOYMENT_NAME: aoaiDeploymentName
      AOAI_REASONING_DEPLOYMENT_NAME: aoaiReasoningDeploymentName
    }
  }
}

// Container App runner (Option B - optional)
module containerApp 'modules/container-app.bicep' = if (deployRunner) {
  name: 'container-app'
  scope: rg
  params: {
    name: 'ca-${resourceToken}'
    location: location
    tags: tags
    storageAccountName: storage.outputs.name
    appSettings: {
      AZURE_STORAGE_ACCOUNT: storage.outputs.name
      AZURE_STORAGE_DATASETS_CONTAINER: 'datasets'
      AZURE_STORAGE_OUTPUTS_CONTAINER: 'outputs'
      PROJECT_ENDPOINT: projectEndpoint
      MODEL_DEPLOYMENT_NAME: modelDeploymentName
      AZURE_VOICE_LIVE_ENDPOINT: voiceLiveEndpoint
      AZURE_VOICE_LIVE_MODEL: voiceLiveModel
      AZURE_VOICE_LIVE_API_VERSION: voiceLiveApiVersion
      AOAI_DEPLOYMENT_NAME: aoaiDeploymentName
      AOAI_REASONING_DEPLOYMENT_NAME: aoaiReasoningDeploymentName
      EVAL_AGENT_MODE: 'cloud'
    }
  }
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

// Storage outputs
output AZURE_STORAGE_ACCOUNT string = storage.outputs.name
output AZURE_STORAGE_ACCOUNT_ENDPOINT string = storage.outputs.primaryEndpoint

// Function App outputs
output AZURE_FUNCTION_APP_NAME string = functionApp.outputs.name
output AZURE_FUNCTION_APP_URL string = functionApp.outputs.url
output AZURE_FUNCTION_APP_PRINCIPAL_ID string = functionApp.outputs.principalId

// Container App outputs (if deployed)
output AZURE_CONTAINER_APP_NAME string = deployRunner ? containerApp.outputs.name! : ''
output AZURE_CONTAINER_APP_URL string = deployRunner ? containerApp.outputs.url! : ''
