// VoiceLive Audio Processor - Container App Infrastructure
// Deploys Container App with required configuration

@description('Location for all resources')
param location string = resourceGroup().location

@description('Base name for resources')
param baseName string = 'voicelive-processor'

@description('Container image to deploy')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('VoiceLive endpoint URL')
param voiceliveEndpoint string

@description('VoiceLive model name')
param voiceliveModel string = 'gpt-realtime'

@description('Storage account name')
param storageAccountName string

@description('Log Analytics workspace ID (optional, creates new if not provided)')
param logAnalyticsWorkspaceId string = ''

// Variables
var uniqueSuffix = uniqueString(resourceGroup().id)
var containerAppEnvName = 'cae-${baseName}-${uniqueSuffix}'
var containerAppName = 'ca-${baseName}'
var logAnalyticsName = 'log-${baseName}-${uniqueSuffix}'

// Create Log Analytics workspace if not provided
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = if (empty(logAnalyticsWorkspaceId)) {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// Container App Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: empty(logAnalyticsWorkspaceId) ? logAnalytics.properties.customerId : reference(logAnalyticsWorkspaceId, '2022-10-01').customerId
        sharedKey: empty(logAnalyticsWorkspaceId) ? logAnalytics.listKeys().primarySharedKey : listKeys(logAnalyticsWorkspaceId, '2022-10-01').primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

// Container App
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      secrets: []
    }
    template: {
      containers: [
        {
          name: 'voicelive-processor'
          image: containerImage
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'AZURE_VOICELIVE_ENDPOINT'
              value: voiceliveEndpoint
            }
            {
              name: 'AZURE_VOICELIVE_MODEL'
              value: voiceliveModel
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT'
              value: storageAccountName
            }
            {
              name: 'AZURE_STORAGE_DATASETS_CONTAINER'
              value: 'datasets'
            }
            {
              name: 'AZURE_STORAGE_OUTPUTS_CONTAINER'
              value: 'outputs'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 10
        rules: [
          {
            name: 'http-scaling'
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

// Role assignment for Container App to access Storage
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

// Storage Blob Data Contributor role
resource storageBlobContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerApp.id, storageAccount.id, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Outputs
output containerAppName string = containerApp.name
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output containerAppPrincipalId string = containerApp.identity.principalId
output containerAppEnvName string = containerAppEnv.name
