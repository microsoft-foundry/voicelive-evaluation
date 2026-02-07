@description('Storage account name')
param name string

@description('Location for the storage account')
param location string = resourceGroup().location

@description('Tags for the resources')
param tags object = {}

@description('Create Azure Tables for config management')
param createTables bool = true

// Storage Account
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

// Blob service
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

// Datasets container
resource datasetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'datasets'
  properties: {
    publicAccess: 'None'
  }
}

// Outputs container
resource outputsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'outputs'
  properties: {
    publicAccess: 'None'
  }
}

// Table service
resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-01-01' = if (createTables) {
  parent: storageAccount
  name: 'default'
}

// Session configs table
resource sessionConfigsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = if (createTables) {
  parent: tableService
  name: 'sessionconfigs'
}

// Config journal table
resource configJournalTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-01-01' = if (createTables) {
  parent: tableService
  name: 'configjournal'
}

// Outputs
output name string = storageAccount.name
output id string = storageAccount.id
output primaryEndpoint string = storageAccount.properties.primaryEndpoints.blob
output tableEndpoint string = storageAccount.properties.primaryEndpoints.table
