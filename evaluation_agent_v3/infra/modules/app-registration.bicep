@description('App Registration name')
param name string

@description('Tags for resources')
param tags object = {}

// Note: App Registrations cannot be created via Bicep directly.
// They must be created via Azure CLI, PowerShell, or Azure Portal.
// This module serves as documentation and outputs placeholders.

// To create the App Registration, run:
// az ad app create --display-name "${name}" --sign-in-audience AzureADMyOrg
// az ad sp create --id <app-id>

// The App Registration should be created with:
// - Single tenant (AzureADMyOrg)
// - App ID URI: api://<app-id>
// - No redirect URIs needed (service-to-service auth)

// Outputs (these would be populated after manual creation)
output appId string = ''
output objectId string = ''
output appIdUri string = ''
