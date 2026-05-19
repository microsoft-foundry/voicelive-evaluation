@description('Function App name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Tags for resources')
param tags object = {}

@description('Storage account name for Function App')
param storageAccountName string

@description('App settings for the Function App')
param appSettings object = {}

@description('Entra ID tenant ID for authentication')
param tenantId string = subscription().tenantId

@description('Enable Entra ID authentication')
param enableEntraAuth bool = false

@description('App Registration Client ID for Entra ID auth (required if enableEntraAuth is true)')
param entraClientId string = ''

@description('Allowed principal IDs that can call the Function App via RBAC')
param allowedCallerPrincipalIds array = []

@description('Optional: Foundry agent name for agent mode')
param agentName string = ''

@description('Optional: Foundry project name for agent mode')
param agentProjectName string = ''

@description('Optional: Foundry resource override for cross-resource agent connections')
param foundryResourceOverride string = ''

// App Service Plan (Consumption)
resource appServicePlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${name}-plan'
  location: location
  tags: tags
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true  // Linux
  }
}

// Application Insights
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    Request_Source: 'rest'
  }
}

// Reference existing storage account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Build app settings array
var baseAppSettings = [
  {
    name: 'AzureWebJobsStorage'
    value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'
  }
  {
    name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
    value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${storageAccount.listKeys().keys[0].value}'
  }
  {
    name: 'WEBSITE_CONTENTSHARE'
    value: toLower(name)
  }
  {
    name: 'FUNCTIONS_EXTENSION_VERSION'
    value: '~4'
  }
  {
    name: 'FUNCTIONS_WORKER_RUNTIME'
    value: 'python'
  }
  {
    name: 'APPINSIGHTS_INSTRUMENTATIONKEY'
    value: appInsights.properties.InstrumentationKey
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsights.properties.ConnectionString
  }
  {
    name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
    value: 'true'
  }
  {
    name: 'ENABLE_ORYX_BUILD'
    value: 'true'
  }
]

var customAppSettings = [for setting in items(appSettings): {
  name: setting.key
  value: setting.value
}]

var agentAppSettings = [
  {
    name: 'AGENT_NAME'
    value: agentName
  }
  {
    name: 'PROJECT_NAME'
    value: agentProjectName
  }
  {
    name: 'FOUNDRY_RESOURCE_OVERRIDE'
    value: foundryResourceOverride
  }
]

var allAppSettings = concat(baseAppSettings, customAppSettings, agentAppSettings)

// Function App
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'tools-api' })
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      pythonVersion: '3.11'
      linuxFxVersion: 'Python|3.11'
      appSettings: allAppSettings
    }
  }
}

// Entra ID Authentication for Function App (Easy Auth v2)
resource functionAppAuth 'Microsoft.Web/sites/config@2023-01-01' = if (enableEntraAuth && !empty(entraClientId)) {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://sts.windows.net/${tenantId}/v2.0'
          clientId: entraClientId
        }
        validation: {
          allowedAudiences: [
            'api://${entraClientId}'
            entraClientId
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
    }
  }
}

// RBAC role assignments are handled by postprovision.ps1 for idempotency
// and broader subscription compatibility. See scripts/azd/postprovision.ps1.
// Inline Bicep role assignments require User Access Administrator permission
// which is not available on many team subscriptions.

// Outputs
output name string = functionApp.name
output url string = 'https://${functionApp.properties.defaultHostName}/api'
output hostname string = functionApp.properties.defaultHostName
output principalId string = functionApp.identity.principalId
output resourceId string = functionApp.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
