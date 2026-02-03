// Container App for the VoiceLive Evaluation Agent

@description('Name of the Container App')
param name string

@description('Location for the Container App')
param location string

@description('Tags for the resource')
param tags object = {}

@description('Container Apps Environment ID')
param containerAppsEnvironmentId string

@description('Container Registry name')
param containerRegistryName string

@description('Azure AI Services endpoint')
param aiServicesEndpoint string

@description('Storage Account name')
param storageAccountName string

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'agent' })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          username: containerRegistry.listCredentials().username
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: [
        {
          name: 'registry-password'
          value: containerRegistry.listCredentials().passwords[0].value
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'agent'
          image: '${containerRegistry.properties.loginServer}/voicelive-evaluation-agent:latest'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'PROJECT_ENDPOINT'
              value: aiServicesEndpoint
            }
            {
              name: 'MODEL_DEPLOYMENT_NAME'
              value: 'gpt-4o-mini'
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
            {
              name: 'EVAL_AGENT_MODE'
              value: 'cloud'
            }
            {
              name: 'EVAL_AGENT_MAX_WORKERS'
              value: '8'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
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

output id string = containerApp.id
output name string = containerApp.name
output url string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output identityPrincipalId string = containerApp.identity.principalId
