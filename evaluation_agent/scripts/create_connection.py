"""
Create a Custom Key Connection in Azure AI Foundry for Function Key authentication.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.ml import MLClient
from azure.ai.ml.entities import WorkspaceConnection
from azure.ai.ml.entities._credentials import ApiKeyConfiguration

# Load environment
SCRIPT_DIR = Path(__file__).parent.parent
load_dotenv(SCRIPT_DIR / ".env")

def create_api_key_connection(connection_name: str, api_key: str, target_url: str = None):
    """Create a Custom Key connection in the AI Foundry workspace."""
    
    credential = DefaultAzureCredential()
    subscription_id = "2c2e6d10-4e48-40fd-8f4d-d9fb770d0c6d"
    
    # Find the workspace
    from azure.mgmt.machinelearningservices import AzureMachineLearningWorkspaces
    ml_mgmt = AzureMachineLearningWorkspaces(credential, subscription_id)
    
    workspace_name = None
    resource_group = None
    
    print("Looking for AI Foundry workspace...")
    for ws in ml_mgmt.workspaces.list_by_subscription():
        if "voicelive-sec" in ws.name.lower():
            workspace_name = ws.name
            # Extract resource group from ID
            resource_group = ws.id.split("/")[4]
            print(f"  Found: {workspace_name} in {resource_group}")
            break
    
    if not workspace_name:
        print("ERROR: Could not find workspace")
        sys.exit(1)
    
    # Create ML client
    ml_client = MLClient(
        credential=credential,
        subscription_id=subscription_id,
        resource_group_name=resource_group,
        workspace_name=workspace_name,
    )
    
    # Check if connection already exists
    try:
        existing = ml_client.connections.get(connection_name)
        print(f"Connection '{connection_name}' already exists. Deleting...")
        ml_client.connections.delete(connection_name)
    except Exception:
        pass  # Connection doesn't exist
    
    # Create Custom Key connection
    # For API key in header, we use CustomKeys type
    connection = WorkspaceConnection(
        name=connection_name,
        type="custom",  # Custom connection type
        target=target_url or "https://func-v3g7ywvldzjeo.azurewebsites.net/api",
        credentials=ApiKeyConfiguration(key=api_key),
        metadata={
            "x-functions-key": api_key,  # Store key with the header name
        }
    )
    
    print(f"\nCreating connection '{connection_name}'...")
    result = ml_client.connections.create_or_update(connection)
    print(f"  Connection created: {result.name}")
    
    return result.name


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Create API Key connection in Foundry")
    parser.add_argument("--name", default="voicelive-eval-api-key", help="Connection name")
    parser.add_argument("--key", required=True, help="API key value")
    parser.add_argument("--url", help="Target URL (optional)")
    args = parser.parse_args()
    
    create_api_key_connection(args.name, args.key, args.url)
