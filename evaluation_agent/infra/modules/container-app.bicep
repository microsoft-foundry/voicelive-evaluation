@description('Container App name')
param name string

@description('Location for resources')
param location string = resourceGroup().location

@description('Tags for resources')
param tags object = {}

@description('Storage account name')
param storageAccountName string

@description('App settings for the Container App')
param appSettings object = {}

@description('Application Insights connection string')
param appInsightsConnectionString string = ''

@description('Function App managed identity appId (for Container App EasyAuth allowedApplications)')
param functionAppMiAppId string = ''

@description('Container Registry name (will create if not exists)')
param acrName string = ''

@description('Container image to deploy')
param containerImage string = ''

@description('Enable Entra ID authentication (Easy Auth)')
param enableEntraAuth bool = true

@description('App Registration Client ID for Container App Easy Auth')
param entraClientId string = ''

@description('Optional: Foundry agent name for agent mode')
param agentName string = ''

@description('Optional: Foundry project name for agent mode')
param agentProjectName string = ''

// Generate ACR name if not provided
var effectiveAcrName = !empty(acrName) ? acrName : 'acr${uniqueString(resourceGroup().id)}'

// Log Analytics Workspace
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${name}-logs'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Application Insights for Container App
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-insights'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// Container Registry
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: effectiveAcrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

// Container Apps Environment
resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${name}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// Reference existing storage account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Build environment variables with App Insights
var baseEnvVars = [for setting in items(appSettings): {
  name: setting.key
  value: setting.value
}]

var appInsightsEnvVar = !empty(appInsightsConnectionString) ? [
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsightsConnectionString
  }
] : [
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsights.properties.ConnectionString
  }
]

var agentEnvVars = [
  {
    name: 'AGENT_NAME'
    value: agentName
  }
  {
    name: 'PROJECT_NAME'
    value: agentProjectName
  }
]

var allEnvVars = concat(baseEnvVars, appInsightsEnvVar, agentEnvVars)

// Container App
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'voicelive-processor' })  // Match service name in azure.yaml
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: [
        {
          server: acr.properties.loginServer
          username: acr.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      secrets: [
        {
          name: 'acr-password'
          value: acr.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'voicelive-processor'
          // Use provided image or placeholder
          image: !empty(containerImage) ? containerImage : 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: allEnvVars
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 5
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

// Storage Blob Data Contributor role for Container App
resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, containerApp.id, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Table Data Contributor role for Container App
resource storageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, containerApp.id, 'Storage Table Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Easy Auth configuration for Container App
// Requires an App Registration to be created first (via Azure Portal or script)
// The entraClientId should be the Application (client) ID of the App Registration
resource authConfig 'Microsoft.App/containerApps/authConfigs@2023-05-01' = if (enableEntraAuth && !empty(entraClientId)) {
  name: 'current'
  parent: containerApp
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: 'https://login.microsoftonline.com/${subscription().tenantId}/v2.0'
          clientId: entraClientId
        }
        validation: {
          allowedAudiences: [
            'api://${entraClientId}'
            entraClientId
          ]
          defaultAuthorizationPolicy: {
            allowedApplications: !empty(functionAppMiAppId) ? [functionAppMiAppId] : []
          }
        }
      }
    }
  }
}

// Outputs
output name string = containerApp.name
output url string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output principalId string = containerApp.identity.principalId
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output entraAuthEnabled bool = enableEntraAuth && !empty(entraClientId)
output entraClientId string = entraClientId
