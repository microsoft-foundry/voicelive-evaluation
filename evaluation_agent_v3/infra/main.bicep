targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (used for resource naming)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Deploy the VoiceLive Container App processor')
param deployContainerApp bool = true

@description('Enable Entra ID authentication on Function App')
param enableEntraAuth bool = false

@description('App Registration Client ID for Function App Entra ID auth')
param entraClientId string = ''

@description('AI Foundry project endpoint')
param projectEndpoint string = ''

@description('Create a new Foundry account and project (default: true). Set to false to use an existing project via projectEndpoint.')
param createFoundry bool = true

@description('Foundry account name (used when createFoundry=true, or for RBAC when using existing)')
param foundryAccountName string = ''

@description('Foundry project name (used when createFoundry=true)')
param foundryProjectName string = ''

@description('Voice Live API endpoint')
param voiceLiveEndpoint string = ''

@description('Voice Live model name')
param voiceLiveModel string = 'gpt-realtime'

@description('Voice Live API version')
param voiceLiveApiVersion string = '2025-10-01'

@description('Model deployment name')
param modelDeploymentName string = 'gpt-4.1-mini'

@description('AOAI deployment name for metrics')
param aoaiDeploymentName string = 'gpt-4.1-mini'

@description('AOAI reasoning deployment name')
param aoaiReasoningDeploymentName string = 'o4-mini'

@description('AI Foundry project principal ID for tracing RBAC (auto-detected when createFoundry=true)')
param foundryProjectPrincipalId string = ''

@description('Enable Entra ID auth on Container App (requires App Registration)')
param enableContainerAppAuth bool = false

@description('App Registration Client ID for Container App Easy Auth')
param containerAppEntraClientId string = ''

@description('Shared API key for Container App authentication (alternative to Entra)')
@secure()
param containerAppApiKey string = ''

// Generate unique suffix for resources
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

// Resource group
resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// Storage account for datasets, outputs, and config tables
module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    name: 'st${resourceToken}'
    location: location
    tags: tags
    createTables: true
  }
}

// Azure AI Foundry account + project (optional - can use existing)
module foundry 'modules/foundry.bicep' = if (createFoundry) {
  name: 'foundry'
  scope: rg
  params: {
    accountName: !empty(foundryAccountName) ? foundryAccountName : 'ai-${resourceToken}'
    projectName: !empty(foundryProjectName) ? foundryProjectName : environmentName
    location: location
    tags: tags
    modelDeployments: [
      { name: modelDeploymentName, model: 'gpt-4.1-mini' }
      { name: aoaiReasoningDeploymentName, model: 'o4-mini' }
    ]
  }
}

// Resolve project endpoint: use Foundry module output if created, otherwise use parameter
var resolvedProjectEndpoint = createFoundry ? foundry.outputs.projectEndpoint : projectEndpoint
var resolvedVoiceLiveEndpoint = createFoundry && empty(voiceLiveEndpoint) ? foundry.outputs.accountEndpoint : voiceLiveEndpoint
var resolvedFoundryAccountId = createFoundry ? foundry.outputs.accountId : ''
var resolvedFoundryProjectPrincipalId = createFoundry ? foundry.outputs.projectPrincipalId : foundryProjectPrincipalId
var resolvedFoundryAccountName = createFoundry ? foundry.outputs.accountName : foundryAccountName

// Function App for tools API
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
      PROJECT_ENDPOINT: resolvedProjectEndpoint
      AZURE_VOICE_LIVE_ENDPOINT: resolvedVoiceLiveEndpoint
      AZURE_VOICE_LIVE_MODEL: voiceLiveModel
      AZURE_VOICE_LIVE_API_VERSION: voiceLiveApiVersion
      AOAI_DEPLOYMENT_NAME: aoaiDeploymentName
      AOAI_REASONING_DEPLOYMENT_NAME: aoaiReasoningDeploymentName
      // Container App proxy settings (URL set post-deployment via script)
      CONTAINER_APP_API_KEY: containerAppApiKey
    }
  }
}

// VoiceLive Container App processor
module containerApp 'modules/container-app.bicep' = if (deployContainerApp) {
  name: 'container-app'
  scope: rg
  params: {
    name: 'ca-voicelive-${resourceToken}'
    location: location
    tags: tags
    storageAccountName: storage.outputs.name
    appInsightsConnectionString: functionApp.outputs.appInsightsConnectionString
    enableEntraAuth: enableContainerAppAuth
    entraClientId: containerAppEntraClientId
    containerAppApiKey: containerAppApiKey
    appSettings: {
      AZURE_STORAGE_ACCOUNT: storage.outputs.name
      AZURE_STORAGE_DATASETS_CONTAINER: 'datasets'
      AZURE_STORAGE_OUTPUTS_CONTAINER: 'outputs'
      PROJECT_ENDPOINT: resolvedProjectEndpoint
      MODEL_DEPLOYMENT_NAME: modelDeploymentName
      AZURE_VOICELIVE_ENDPOINT: resolvedVoiceLiveEndpoint
      AZURE_VOICELIVE_MODEL: voiceLiveModel
      AZURE_VOICELIVE_API_VERSION: voiceLiveApiVersion
      EVAL_AGENT_MODE: 'cloud'
    }
  }
}

// RBAC: Assign Azure AI User role to Foundry project for tracing
// When createFoundry=true, use the created project's principal ID
// When using existing, use the manually provided principal ID + account name
module foundryRbac 'modules/foundry-rbac.bicep' = if (createFoundry || (!empty(foundryProjectPrincipalId) && !empty(foundryAccountName))) {
  name: 'foundry-rbac'
  scope: rg
  params: {
    foundryProjectPrincipalId: createFoundry ? foundry.outputs.projectPrincipalId : foundryProjectPrincipalId
    foundryAccountName: createFoundry ? foundry.outputs.accountName : foundryAccountName
  }
}

// NOTE: Function App and Container App RBAC (AI Developer, CS User, Storage roles)
// is handled by scripts/azd/postprovision.ps1 for idempotency.
// ARM role assignments fail on re-provision if they already exist.

// Outputs for azd
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name

// Storage outputs
output AZURE_STORAGE_ACCOUNT string = storage.outputs.name
output AZURE_STORAGE_ACCOUNT_NAME string = storage.outputs.name  // For scripts
output AZURE_STORAGE_ACCOUNT_ENDPOINT string = storage.outputs.primaryEndpoint
output AZURE_STORAGE_TABLE_ENDPOINT string = storage.outputs.tableEndpoint

// Function App outputs
output AZURE_FUNCTION_APP_NAME string = functionApp.outputs.name
output AZURE_FUNCTION_APP_URL string = functionApp.outputs.url
output AZURE_FUNCTION_APP_PRINCIPAL_ID string = functionApp.outputs.principalId
output AZURE_APPINSIGHTS_CONNECTION_STRING string = functionApp.outputs.appInsightsConnectionString

// Container App outputs (if deployed)
output AZURE_CONTAINER_APP_NAME string = deployContainerApp ? containerApp.outputs.name : ''
output AZURE_CONTAINER_APP_URL string = deployContainerApp ? containerApp.outputs.url : ''
output AZURE_ACR_NAME string = deployContainerApp ? containerApp.outputs.acrName : ''
output AZURE_ACR_LOGIN_SERVER string = deployContainerApp ? containerApp.outputs.acrLoginServer : ''

// Foundry outputs
output PROJECT_ENDPOINT string = resolvedProjectEndpoint
output FOUNDRY_ACCOUNT_RESOURCE_ID string = resolvedFoundryAccountId
output FOUNDRY_ACCOUNT_NAME string = resolvedFoundryAccountName
output AZURE_VOICE_LIVE_ENDPOINT string = resolvedVoiceLiveEndpoint
