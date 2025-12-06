## Added
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

## Added End


import os

# Azure AI Project endpoint
# Example: https://<account_name>.services.ai.azure.com/api/projects/<project_name>
endpoint = os.environ["PROJECT_ENDPOINT"]

# Model deployment name
# Example: gpt-4o-mini
model_deployment_name = os.environ.get("AOAI_DEPLOYMENT_NAME", "")

# Dataset details
dataset_name = os.environ.get("DATASET_NAME", "Eiffel_Tower_Visit_1_Uploaded4")
dataset_version = os.environ.get("DATASET_VERSION", "2")

from azure.identity import DefaultAzureCredential 
from azure.ai.projects import AIProjectClient 

# Create the project client (Foundry project and credentials): 

project_client = AIProjectClient( 
    endpoint=endpoint, 
    credential=DefaultAzureCredential(), 
)

# Upload a local JSONL file. Skip this step if you already have a dataset registered.
response = project_client.datasets.upload_file(
    name=dataset_name,
    version=dataset_version,
    file_path="C:\\Localrepos\\voicelive-evaluation\\output\\2025-12-01_18-51-42\\2025-12-01_18-51-42_aggregate_Eiffel_Tower_Visit_1.jsonl",
)

# Print the full response
print(response)
print("\n")
# Print the dataset ID
data_id = response.id
print(data_id)
