import argparse
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
load_dotenv()

def main(delete_search_string: str = ""):
    # Clean up: delete datasets
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.getenv("PROJECT_ENDPOINT")
    )
    client = project_client.get_openai_client()

    datasets = list(project_client.datasets.list())

    for dataset in datasets:
        print(f"\nFound dataset: {dataset.name} with id: {dataset.id}")
        dataset_versions = list(project_client.datasets.list_versions(name=dataset.name))
        # Get the current (highest) version number
        if dataset_versions:
            current_version = max(int(v.version) for v in dataset_versions)
            print(f"Latest version: {current_version}")
        else:
            print("No versions found")
            current_version = 0
        # Delete datasets matching the search string
        if delete_search_string:
            if delete_search_string in dataset.name:
                print(f"Deleting all versions of dataset: {dataset.name} with id: {dataset.id}")
                for version in dataset_versions:
                    project_client.datasets.delete(
                        name=dataset.name,
                        version=version.version
                    )
                print(f"Deleted dataset: {dataset.name} with id: {dataset.id}")
            else:
                print(f"Dataset: {dataset.name} does not match delete search string. Skipping deletion.")

    if not delete_search_string:
        print("\nNo delete search string provided. No datasets deleted.")
    else:
        print("\nFinished deleting datasets.")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Delete datasets based on a search string.")
    parser.add_argument("--delete-search-string", type=str, help="Optional search string to delete specific datasets. If not provided, no datasets will be deleted.")
    args = parser.parse_args()

    delete_search_string = args.delete_search_string if args.delete_search_string else None

    if args.delete_search_string:
        main(delete_search_string)
    else:
        main()
