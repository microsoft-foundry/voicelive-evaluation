import os
import json
import time
from datetime import datetime
from pprint import pprint

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import DatasetVersion
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
    SourceFileID,
)

# Load environment variables from a .env file if present
load_dotenv()

# --- Configuration (Environment Variables) ---

# Example: https://<account>.services.ai.azure.com/api/projects/<project>
endpoint = os.environ["PROJECT_ENDPOINT"]

connection_name = os.environ.get("CONNECTION_NAME", "")
# Example: https://<account>.openai.azure.com
model_endpoint = os.environ.get("AOAI_ENDPOINT_EVALUATION", "")
model_api_key = os.environ.get("AOAI_API_KEY", "")
# Example: gpt-4o-mini
model_deployment_name = os.environ.get("AOAI_DEPLOYMENT_NAME", "")

dataset_name = os.environ.get("DATASET_NAME", "Eiffel_Tower_Visit_1")
dataset_version = os.environ.get("DATASET_VERSION", "2")

# --- Data paths ---

# Construct the paths to the data folder and data file used in this sample
script_dir = os.path.dirname(os.path.abspath(__file__))
data_folder = os.environ.get("DATA_FOLDER", os.path.join(script_dir, "data_folder"))
# data_file = os.path.join(data_folder, "sample_data_evaluation.jsonl")
data_file = "C:\\Localrepos\\voicelive-evaluation\\output\\2025-12-01_18-51-42\\2025-12-01_18-51-42_aggregate_Eiffel_Tower_Visit_1.jsonl"
# --- Client setup and workflow ---

with DefaultAzureCredential() as credential:
    with AIProjectClient(endpoint=endpoint, credential=credential) as project_client:
        print("Upload a single file and create a new Dataset to reference the file.")
        dataset: DatasetVersion = project_client.datasets.upload_file(
            name=dataset_name
            or f"eval-data-{datetime.utcnow().strftime('%Y-%m-%d_%H%M%S_UTC')}",
            version=dataset_version,
            file_path=data_file,
        )
        pprint(dataset)

        print("Creating an OpenAI client from the AI Project client")
        client = project_client.get_openai_client()

        data_source_config = {
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "response": {"type": "string"},
                    "context": {"type": "string"},
                    "ground_truth": {"type": "string"},
                },
                "required": [],
            },
            "include_sample_schema": True,
        }

        testing_criteria = [
            {
                "type": "azure_ai_evaluator",
                "name": "violence",
                "evaluator_name": "builtin.violence",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
                "initialization_parameters": {
                    "deployment_name": f"{model_deployment_name}"
                },
            },
            {
                "type": "azure_ai_evaluator",
                "name": "f1",
                "evaluator_name": "builtin.f1_score",
            },
            {
                "type": "azure_ai_evaluator",
                "name": "coherence",
                "evaluator_name": "builtin.coherence",
                "initialization_parameters": {
                    "deployment_name": f"{model_deployment_name}"
                },
            },
        ]

        print("Creating Eval Group")
        eval_object = client.evals.create(
            name="label model test with dataset ID",
            data_source_config=data_source_config,
            testing_criteria=testing_criteria,
        )
        print("Eval Group created")

        print("Get Eval Group by Id")
        eval_object_response = client.evals.retrieve(eval_object.id)
        print("Eval Group Response:")
        pprint(eval_object_response)

        print("Creating Eval Run with Dataset ID")
        eval_run_object = client.evals.runs.create(
            eval_id=eval_object.id,
            name="dataset_id_run",
            metadata={"team": "eval-exp", "scenario": "dataset-id-v1"},
            data_source=CreateEvalJSONLRunDataSourceParam(
                type="jsonl",
                source=SourceFileID(
                    type="file_id",
                    id=dataset.id if dataset.id else "",
                ),
            ),
        )

        print("Eval Run created")
        pprint(eval_run_object)

        print("Get Eval Run by Id")
        eval_run_response = client.evals.runs.retrieve(
            run_id=eval_run_object.id,
            eval_id=eval_object.id,
        )
        print("Eval Run Response:")
        pprint(eval_run_response)

        # Poll until the run completes or fails
        while True:
            run = client.evals.runs.retrieve(
                run_id=eval_run_response.id, eval_id=eval_object.id
            )
            if run.status in ("completed", "failed"):
                output_items = list(
                    client.evals.runs.output_items.list(
                        run_id=run.id, eval_id=eval_object.id
                    )
                )
                pprint(output_items)
                print(f"Eval Run Report URL: {run.report_url}")
                break

            time.sleep(5)
            print("Waiting for eval run to complete...")