import argparse
import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
load_dotenv()

def main(delete_search_string: str = ""):
    # Clean up: delete evaluator groups
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=os.getenv("PROJECT_ENDPOINT")
    )
    client = project_client.get_openai_client()

    evaluation_groups = list(client.evals.list())

    for evaluation_group in evaluation_groups:
        print(f"\nFound evaluation group: {evaluation_group.name} with id: {evaluation_group.id}")

        if delete_search_string:
            if delete_search_string in evaluation_group.name:
                print(f"Deleting evaluation group: {evaluation_group.name} with id: {evaluation_group.id}")
                client.evals.delete(
                    eval_id=evaluation_group.id
                )
                print(f"Deleted evaluation group: {evaluation_group.name} with id: {evaluation_group.id}")
            else:
                print(f"Evaluation group: {evaluation_group.name} does not match delete search string. Skipping deletion.")        

    if delete_search_string:
        print("\nFinished deleting evaluation groups.")
    else:
        print("\nNo delete search string provided. No evaluation groups deleted.")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Delete evaluation groups based on a search string.")
    parser.add_argument("--delete-search-string", type=str, help="Optional search string to delete specific evaluation groups. If not provided, no groups will be deleted.")
    args = parser.parse_args()

    delete_search_string = args.delete_search_string if args.delete_search_string else None

    if args.delete_search_string:
        main(delete_search_string)
    else:
        main()
