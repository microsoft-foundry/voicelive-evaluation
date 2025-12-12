import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
load_dotenv()

# Clean up: delete evaluator versions before the latest one
project_client = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=os.getenv("PROJECT_ENDPOINT")
)

evaluators = list(project_client.evaluators.list_latest_versions(type="custom"))

for evaluator in evaluators:
    print(f"Found evaluator: {evaluator.name}")
    versions = list(project_client.evaluators.list_versions(
        name=f"{evaluator.name}"
    ))    
    # Get the current (highest) version number
    if versions:
        current_version = max(int(v.version) for v in versions)
        print(f"Current version: {current_version}")
    else:
        print("No versions found")
        current_version = 0
    print(f"Found {current_version} versions of the custom evaluator to delete.")
    # loop through versions and try to delete the evaluator
    for version in versions:
        print(f"Deleting version {version.id} of the created evaluator")
        result = project_client.evaluators.delete_version(
            name=f"{evaluator.name}",
            version=version.version,
        )
        print(f"Delete evaluator version result: {result}")     
    print(f"Finished deleting versions for evaluator: {evaluator.name}")

print("All custom evaluator versions deleted.")
