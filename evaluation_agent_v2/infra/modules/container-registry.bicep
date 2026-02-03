// Container Registry for storing agent container images

@description('Name of the container registry')
param name string

@description('Location for the container registry')
param location string

@description('Tags for the resource')
param tags object = {}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true  // Required for Container Apps to pull images
    publicNetworkAccess: 'Enabled'
  }
}

output name string = containerRegistry.name
output id string = containerRegistry.id
output loginServer string = containerRegistry.properties.loginServer
