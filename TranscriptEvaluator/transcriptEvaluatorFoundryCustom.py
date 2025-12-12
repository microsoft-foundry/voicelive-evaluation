import os
from posixpath import basename
from time import sleep
import time
from datetime import datetime, timezone
from xmlrpc import client
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
from pathlib import Path
import json
from pprint import pprint
from azure.core.paging import ItemPaged
from azure.ai.projects.models import DatasetVersion, EvaluatorVersion, EvaluatorCategory, EvaluatorDefinitionType
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
    SourceFileContent,
    SourceFileID,
    SourceFileContentContent,
)
import warnings

# Suppress Pydantic serialization warnings from Azure AI SDK
# The SDK returns "not applicable" strings for float fields which causes warnings
# Apply multiple filters to catch warnings from different Pydantic modules
warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
warnings.filterwarnings('ignore', message='.*Expected `float`.*')
warnings.filterwarnings('ignore', message='.*serialized value may not be as expected.*')

# Pretty print evaluation results
# Pretty print evaluation results
def print_eval_results(output_items, transcriptFilePath, referenceTranscriptFilePath, output_file_path):
    """Print the evaluation results in a formatted table"""
    
    if not output_items:
        print("No evaluation results found.")
        return
    
    # output_items is already a list, no need to parse JSON
    # If it's a string, parse it; otherwise use it directly
    if isinstance(output_items, str):
        json_data = json.loads(output_items)
        output_items = json_data.get("items", [])
    elif isinstance(output_items, dict):
        output_items = output_items.get("items", [])
    # else: output_items is already a list of Pydantic model objects

    # Aggregate metrics across all items
    metric_scores = {}
    metric_counts = {}
    
    for item in output_items:
        # Each item has a 'results' array containing metrics
        # Handle both dict and Pydantic model objects
        if hasattr(item, 'results'):
            results = item.results
        elif isinstance(item, dict):
            results = item.get("results", [])
        else:
            results = []
            
        for result in results:
            # Handle both dict and Pydantic model objects
            if hasattr(result, 'name'):
                metric_name = result.name
                score = result.score
            elif isinstance(result, dict):
                metric_name = result.get("name", "unknown")
                score = result.get("score")
            else:
                continue

            # Only aggregate numeric scores
            if isinstance(score, (int, float)):
                if metric_name not in metric_scores:
                    metric_scores[metric_name] = 0
                    metric_counts[metric_name] = 0
                metric_scores[metric_name] += score
                metric_counts[metric_name] += 1
    
    # Calculate averages
    metric_averages = {
        name: metric_scores[name] / metric_counts[name]
        for name in metric_scores
    }
    
    # Get the maximum length for formatting
    key_len = max(len(key) for key in metric_averages.keys()) + 5 if metric_averages else 20
    value_len = 20
    full_len = key_len + value_len + 5
    
    # Format the header
    print("\n" + "=" * full_len)
    print("Evaluation Results Summary".center(full_len))
    print("=" * full_len)
    print(f"Total Items Evaluated: {len(output_items)}")
    print("=" * full_len)
    
    # Print aggregated metrics
    print(f"{'Metric':<{key_len}} | {'Average Score'}")
    print("-" * (key_len) + "-+-" + "-" * value_len)
    
    for key in sorted(metric_averages.keys()):
        value = metric_averages[key]
        formatted_value = f"{value:.2f}"
        print(f"{key:<{key_len}} | {formatted_value}")
    
    print("=" * full_len + "\n")

    # Print additional information
    print(f"Generated Audio transcript: {transcriptFilePath}")
    print(f"Reference transcript: {referenceTranscriptFilePath}")
    print(f"Evaluation output: {output_file_path}")
    print(f"For detailed per-item results, see the output file.")

    print("\n" + "=" * full_len + "\n")

def create_dataset_from_transcripts(
    transcript_file_path: str,
    reference_transcript_file_path: str,
    output_folder: str = "output",
    dataset_appendix: str = ""
) -> str:
    """
    Create and upload a dataset from transcript files for evaluation.
    
    Args:
        transcript_file: Path to the generated transcript file
        reference_transcript_file: Path to the reference transcript file
        output_folder: Folder to save the dataset file
        dataset_appendix: Optional appendix to add to the dataset filename
    Returns:
        str: Path to the created dataset file
    """
    
    # Ensure output folder exists
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    # Ensure transcript file paths are valid
    if not Path(transcript_file_path).exists():
        raise FileNotFoundError(f"Transcript file path not found: {transcript_file_path}")
    if not Path(reference_transcript_file_path).exists():
        raise FileNotFoundError(f"Reference transcript file path not found: {reference_transcript_file_path}")
    
    # Create dataset file
    dataset_filename = f"transcript_eval_dataset_{Path(transcript_file_path).stem}{dataset_appendix}.jsonl"
    dataset_path = Path(output_folder) / dataset_filename
    
    # Read transcript files
    try:
        # For each file in the provided folder paths, read the content
        for transcript_file in Path(transcript_file_path).glob("*.md"):
            reference_transcript_file = Path(reference_transcript_file_path) / transcript_file.name
            # Check if reference transcript file exists
            if not reference_transcript_file.exists():
                print(f"Warning: Reference transcript file not found for {transcript_file.name}. Skipping this file.")
                continue
            else:
                transcript_content = ""
                reference_content = ""
                with open(transcript_file, 'r', encoding='utf-8') as transcript_f:
                    transcript_content += transcript_f.read() + "\n"
                transcript_f.close()
                with open(reference_transcript_file, 'r', encoding='utf-8') as reference_f:
                    reference_content += reference_f.read() + "\n"
                reference_f.close()
                # Create evaluation dataset item
                dataset_item = {
                    "transcript": transcript_content,
                    "ground_truth": reference_content,
                }
                # Write dataset to JSONL file
                with open(dataset_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(dataset_item) + '\n')
                f.close()
    except Exception as e:
        print(f"Error: {e}")
        raise e

    print(f"Dataset created: {dataset_path}")
    return str(dataset_path)

def upload_dataset_from_transcripts(dataset_path: str, project_client: AIProjectClient) -> DatasetVersion:
    """
    Upload the dataset file to the Foundry project.
    
    Args:
        dataset_path: Path to the dataset file
        project_client: Instance of AIProjectClient
        
    Returns:
        DatasetVersion: Uploaded dataset version
    """

    # Check if dataset file exists
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
    
    # Check if dataset file is not empty
    if Path(dataset_path).stat().st_size == 0:
        raise ValueError(f"Dataset file is empty: {dataset_path}")
    
    # Get existing datasets in the project and check the current version. If dataset with same name exists, increment version, else create version 1.
    datasets = list(project_client.datasets.list())
    dataset_name = Path(dataset_path).stem
    existing_versions = [d for d in datasets if d.name == dataset_name]
    if existing_versions:
        latest_version = max(d.version for d in existing_versions)
        new_version = int(latest_version) + 1
    else:
        new_version = 1

    # Upload the dataset file and create a new Dataset to reference the file.
    print("Upload dataset file and create a new Dataset for evaluation.")
    try:
        dataset: DatasetVersion = project_client.datasets.upload_file(
            name=dataset_name,
            version=str(new_version),
            file_path=dataset_path
        )
        pprint(dataset)
        print("Dataset uploaded for evaluation run.")
    except Exception as e:
        print(f"Error uploading dataset: {e}")
        raise e
    return dataset

def create_custom_evaluators(project_client: AIProjectClient, custom_evaluator_definition_file: str) -> EvaluatorVersion:
    """
    Creates a custom transcript evaluator for quality assessment using a prompt-based approach.
    
    This function reads a custom evaluator definition from a text file and creates a new
    evaluator version in the AI project. The evaluator is designed to assess transcript
    quality by comparing transcripts against ground truth data using a configurable
    threshold and deployment model.
    
    Args:
        project_client: The AI project client instance used to interact with the evaluators API
        custom_evaluator_definition_file: Path to the file containing the evaluator prompt definition
        
    Returns:
        EvaluatorVersion: The created evaluator version object
        
    Raises:
        FileNotFoundError: If the custom evaluator definition file is not found
        IOError: If there's an error reading the evaluator definition file
        Exception: If there's an error creating the evaluator in the project
        
    Note:
        The evaluator definition file must contain the prompt text for the custom evaluator logic.
        The function will automatically increment version numbers for evaluators with the same name.
    """

    print(f"Creating custom evaluator version for {custom_evaluator_definition_file}...")

    custom_evaluator_name = Path(custom_evaluator_definition_file).stem
    print(f"Custom evaluator name: {custom_evaluator_name}")

    try:
        with open(custom_evaluator_definition_file, 'r', encoding='utf-8') as f:
            custom_evaluator_definition = f.read()
        f.close()
    except FileNotFoundError as e:
        print(f"Error reading file: {custom_evaluator_definition_file}")
        raise e
    try:
        custom_evaluator = project_client.evaluators.create_version(
            name=f"{custom_evaluator_name}",
            evaluator_version={
                "name": f"custom{custom_evaluator_name}",
                "categories": [EvaluatorCategory.QUALITY],
                "display_name": f"{custom_evaluator_name}",
                "description": "Custom evaluator for audio transcript quality assessment using prompt-based approach.",
                "definition": {
                    "type": EvaluatorDefinitionType.PROMPT,
                    "prompt_text": custom_evaluator_definition,
                        "init_parameters": {
                            "type": "object",
                            "properties": {"deployment_name": {"type": "string"}, "threshold": {"type": "number"}},
                            "required": ["deployment_name", "threshold"],
                        },
                        "data_schema": {
                            "type": "object",
                            "properties": {
                                "transcript": {"type": "string"},
                                "ground_truth": {"type": "string"},
                            },
                            "required": ["transcript", "ground_truth"],
                        },
                        "metrics": {
                            "custom_prompt": {
                                "type": "ordinal",
                                "desirable_direction": "increase",
                                "min_value": 1,
                                "max_value": 5,
                            }
                        },
                    },
                },
            )
        print(f"Custom  evaluator {custom_evaluator.name} created successfully with Id {custom_evaluator.id}")
        return custom_evaluator
    except Exception as e:
        print(f"Error creating custom transcript evaluator: {e}")
        raise e

def main(transcriptFilePath: str, referenceTranscriptFilePath: str, output_folder: str = "./output", eval_run_name: str = "", eval_group_name: str = "", eval_object_id: str = "", dataset_id: str = "", dataset_appendix: str = "", setupCustomEvaluators: bool = True, custom_evaluators_folder: str = ""):
    """ Main function to run the evaluation of voice agent sessions."""
    # Change to the directory where this script is located
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Load environment variables from .env file
    load_dotenv("./.env", override=True)

    # Check environment variables were loaded correctly
    aoai_deployment_name = os.getenv("AOAI_DEPLOYMENT_NAME")
    assert aoai_deployment_name is not None, "AOAI_DEPLOYMENT_NAME is not set in .env file"
    assert os.getenv("AOAI_REASONING_DEPLOYMENT_NAME") is not None, "AOAI_REASONING_DEPLOYMENT_NAME is not set in .env file"
    aoai_reasoning_deployment_name = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
    assert os.getenv("PROJECT_ENDPOINT") is not None, "PROJECT_ENDPOINT is not set in .env file"
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    
    # Check if output folder exists, if not create it
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {output_folder}")

    # Setup connections and prepare tools
    ## Create the AIProjectClient with the necessary parameters
    try:
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
    except Exception as e:
        print(f"Error creating AIProjectClient: {e}")
        exit(1)
    ## Set model deployment names and create OpenAI client
    model_deployment_name = aoai_reasoning_deployment_name
    try:
        client = project_client.get_openai_client()
    except Exception as e:
        print(f"Error creating OpenAI client: {e}")
        exit(1)

    ## Create custom evaluator in Foundry project
    if setupCustomEvaluators:
        # Check if custom evaluators folder exists and contains custom evaluator definition files
        if not Path(custom_evaluators_folder).exists() or not any(Path(custom_evaluators_folder).glob("*.txt")):
            print(f"Custom evaluators folder not found or empty: {custom_evaluators_folder}")
            exit(1)
        else:
            # Create custom evaluators
            custom_evaluators_list = []
            testing_criteria = []
            print("Creating custom evaluators...")
            for evaluator_file in Path(custom_evaluators_folder).glob("*.txt"):
                custom_evaluator_result = create_custom_evaluators(project_client, evaluator_file)
                custom_evaluators_list.append(custom_evaluator_result.name)

    ## Setup eval group
    if eval_object_id == "" or eval_object_id is None:
        print("Preparing Eval Group...")
        ## Create testing criteria for eval group setup
        for evaluator_name in custom_evaluators_list:
            testing_criteria.append(
                {
                    "type": "azure_ai_evaluator",
                    "name": evaluator_name,
                    "evaluator_name": evaluator_name,
                    "data_mapping": {
                        "transcript": "{{item.transcript}}",
                        "ground_truth": "{{item.ground_truth}}",
                    },
                    "initialization_parameters": {"deployment_name": f"{model_deployment_name}", "is_reasoning_model": True if model_deployment_name == aoai_reasoning_deployment_name else False, "threshold": 4},
                }
            )   
        ## Create data source config for eval group setup
        data_source_config = {
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string"},
                    "ground_truth": {"type": "string"},
                },
                "required": ["transcript", "ground_truth"],
            },
            "include_sample_schema": True,
        }
        sleeptimer = 120
        print(f"Waiting {sleeptimer} seconds for evaluators to be ready...")
        sleep(sleeptimer)  # wait for evaluators to be ready and available
        # Create Eval Group
        try:
            print("Creating Eval Group...")
            eval_object = client.evals.create(
                name=eval_group_name,
                data_source_config=data_source_config,
                testing_criteria=testing_criteria,
            )
        except Exception as e:
            print(f"Error creating eval group: {e}")
            exit(1)
        try:
            eval_object_response = client.evals.retrieve(eval_object.id)
            print(f"Eval Group created with Id : {eval_object.id}")
            print("Eval Run Response:")
            pprint(eval_object_response)
            eval_id = eval_object.id
        except Exception as e:
            print(f"Error retrieving eval group id: {e}")
            exit(1)
    else:
        print("Using existing Eval Group!")
        eval_id = eval_object_id
    print(f"\nUsing Eval ID: {eval_id}")

    # Prepare data and upload to Foundry
    if dataset_id == "" or dataset_id is None:
        ## Create dataset from transcripts
        print("Creating dataset from transcripts...")
        dataset_path = create_dataset_from_transcripts(
            transcript_file_path=transcriptFilePath,
            reference_transcript_file_path=referenceTranscriptFilePath,
            output_folder=output_folder,
            dataset_appendix=dataset_appendix
        )
        print(f"Dataset created at: {dataset_path}")
        print("\nUploading dataset to Foundry project...")
        ## Upload dataset to Foundry project
        print("Uploading dataset to Foundry project...")
        dataset = upload_dataset_from_transcripts(
            dataset_path=dataset_path,
            project_client=project_client
        )
        print(f"Dataset uploaded with ID: {dataset.id} and Version: {dataset.version}")
        dataset_id=dataset.id

    ## Create data source config for eval run
    data_source = CreateEvalJSONLRunDataSourceParam(
        type="jsonl",
        source=SourceFileID(
            type="file_id",
            id=dataset_id if dataset_id else "",
        ),
    )

    # Create Eval Run and get run Id
    try:
        print("Creating Eval Run with Inline Data...")
        eval_run_object = client.evals.runs.create(
            eval_id=eval_id,
            name=eval_run_name,
            metadata={"team": "Audio-Evaluation", "scenario": f"{eval_run_name}"},
            data_source=data_source
        )
        print(f"Eval Run created with Id : {eval_run_object.id}")
        pprint(eval_run_object)
    except Exception as e:
        print(f"Error creating eval run: {e}")
        exit(1)
    try:
        print("Get Eval Run by Id")
        eval_run_response = client.evals.runs.retrieve(run_id=eval_run_object.id, eval_id=eval_id)
        print("Eval Run Response:")
        pprint(eval_run_response)
    except Exception as e:
        print(f"Error retrieving eval run id: {e}")
        exit(1)

    print("\n\n----Eval Run Output Items----\n\n")

    while True:
        run = client.evals.runs.retrieve(run_id=eval_run_response.id, eval_id=eval_id)
        if run.status == "completed" or run.status == "failed":
            try:
                output_items = list(client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_id))
                # write the output items to a jsonl file
                output_file_path = Path(output_folder) / f"{run.id}_eval_output.json"
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    for item in output_items:
                        f.write(json.dumps(item.model_dump(), indent=4) + '\n')
                f.close()
                print(f"\nOUTPUT ITEMS (Total: {len(output_items)})")
            except Exception as e:
                print(f"Error retrieving output items: {e}")
                exit(1)

            # Format and print the evaluation results
            print(f"{'-'*60}")
            print_eval_results(output_items, transcriptFilePath, referenceTranscriptFilePath, output_file_path)
            print(f"{'-'*60}")
            print(f"Eval Run Status: {run.status}")
            print(f"Eval Run Report URL: {run.report_url}")
            break
        sleep(5)
        time.sleep(5)
        print("Waiting for eval run to complete...")
    
    if setupCustomEvaluators:
        # Clean up: delete evaluator versions before the latest one
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=os.getenv("PROJECT_ENDPOINT")
        )
        for evaluator in custom_evaluators_list:
            versions = list(project_client.evaluators.list_versions(
                name=f"{evaluator}"
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
                if version.version == str(current_version):
                    print(f"Skipping deletion of latest version {version.id} of the created evaluator")
                    continue
                print(f"Deleting version {version.id} of the created evaluator")
                result = project_client.evaluators.delete_version(
                    name=f"{evaluator}",
                    version=version.version,
                )
                print(f"Delete evaluator version result: {result}")        

if __name__ == "__main__":

    transcriptFilePath = ".\\local_datasets\\unhcr\\transcripts_optimized\\"
    referenceTranscriptFilePath = ".\\local_datasets\\unhcr\\reference_transcripts_optimized\\"
    dataset_appendix = f"_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    eval_object_id = "eval_ba6c7c9768144dffb8c6438dc116dbe3" # replace with your eval id if needed
    # dataset_id='azureai://accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/data/transcript_eval_dataset_transcripts/versions/8'
    # dataset_id="azureai://accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/data/transcript_eval_dataset_transcripts_unhcr_sample7/versions/1"
    dataset_id="azureai://accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/data/transcript_eval_dataset_transcripts_optimized_unhcr_optimized/versions/1"
    # dataset_id="azureai://accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/data/transcript_eval_dataset_transcripts_unhcr_sample8/versions/1"

    main(
        transcriptFilePath,
        referenceTranscriptFilePath,
        output_folder="./output",
        eval_group_name="UNHCR Transcript Evaluator Group o4-mini",
        eval_object_id="eval_5940113e27f1484b9a09321a86e36522",
        eval_run_name = "Sample7+8",
        dataset_id=dataset_id,
        dataset_appendix="_unhcr_optimized",
        setupCustomEvaluators=False,
        custom_evaluators_folder="./evaluatorPromptsOptimized"
    )
