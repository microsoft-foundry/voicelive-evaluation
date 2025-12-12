"""
Code-based Custom Evaluators for Transcript Quality Assessment

This script creates code-based evaluators for Word Error Rate (WER) and 
Token Error Rate (TER) metrics using the Azure AI Foundry evaluation framework.

WER (Word Error Rate): Measures the minimum number of word-level edits 
(insertions, deletions, substitutions) needed to transform the transcript 
into the ground truth, normalized by the ground truth length.

TER (Token Error Rate): Similar to WER but operates at the character/token level,
providing a more granular measure of transcription accuracy.

Input formats:
- Transcript: JSON file with 'phrases' array containing 'text' fields
- Reference: TSV file with audio filename in first column and ground truth text per line

Required Environment Variables (.env file):
- PROJECT_ENDPOINT: Azure AI Foundry project endpoint
- MODEL_DEPLOYMENT: Model deployment name (e.g., 'gpt-4o-mini') - required by service for evaluator configuration
"""

import os
from time import sleep
import time
from datetime import datetime, timezone
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from dotenv import load_dotenv
from pathlib import Path
import json
from pprint import pprint
from azure.ai.projects.models import DatasetVersion, EvaluatorVersion, EvaluatorCategory, EvaluatorDefinitionType
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
    SourceFileContent,
    SourceFileID,
    SourceFileContentContent,
)
import warnings

# Suppress Pydantic serialization warnings from Azure AI SDK
warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
warnings.filterwarnings('ignore', message='.*Expected `float`.*')
warnings.filterwarnings('ignore', message='.*serialized value may not be as expected.*')


# ============================================================================
# WER Evaluator Code (as string for code-based evaluator)
# ============================================================================
WER_EVALUATOR_CODE = '''
def grade(sample: dict, item: dict) -> float:
    """
    Calculate Word Error Rate (WER) between transcript and ground truth.
    
    WER = (S + D + I) / N
    Where:
        S = number of word substitutions
        D = number of word deletions
        I = number of word insertions
        N = number of words in ground truth
    
    Returns: 1.0 - WER (so higher is better, capped at 0.0 minimum)
    """
    transcript = item.get("transcript", "") if isinstance(item, dict) else ""
    ground_truth = item.get("ground_truth", "") if isinstance(item, dict) else ""
    
    def normalize(text):
        import re
        # Remove punctuation and convert to lowercase
        text = re.sub(r'[^\\w\\s]', '', text.lower())
        # Normalize whitespace and split into words
        return text.split()
    
    ref_words = normalize(ground_truth)
    hyp_words = normalize(transcript)
    
    if len(ref_words) == 0:
        return 1.0 if len(hyp_words) == 0 else 0.0
    
    # Dynamic programming for Levenshtein distance at word level
    n = len(ref_words)
    m = len(hyp_words)
    
    # Use two rows to save memory for long sequences
    prev_row = list(range(m + 1))
    curr_row = [0] * (m + 1)
    
    for i in range(1, n + 1):
        curr_row[0] = i
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                curr_row[j] = prev_row[j - 1]
            else:
                curr_row[j] = min(
                    prev_row[j] + 1,      # deletion
                    curr_row[j - 1] + 1,  # insertion
                    prev_row[j - 1] + 1   # substitution
                )
        prev_row, curr_row = curr_row, prev_row
    
    # Calculate WER
    wer = prev_row[m] / n
    
    # Return accuracy (1 - WER), capped at 0.0 minimum
    return round(max(0.0, 1.0 - wer), 4)
'''


# ============================================================================
# TER Evaluator Code (as string for code-based evaluator)
# ============================================================================
TER_EVALUATOR_CODE = '''
def grade(sample: dict, item: dict) -> float:
    """
    Calculate Token/Character Error Rate (TER) between transcript and ground truth.
    
    TER = (S + D + I) / N
    Where:
        S = number of character substitutions
        D = number of character deletions
        I = number of character insertions
        N = number of characters in ground truth (after normalization)
    
    Returns: 1.0 - TER (so higher is better, capped at 0.0 minimum)
    """
    transcript = item.get("transcript", "") if isinstance(item, dict) else ""
    ground_truth = item.get("ground_truth", "") if isinstance(item, dict) else ""
    
    def normalize(text):
        import re
        # Remove punctuation and convert to lowercase
        text = re.sub(r'[^\\w\\s]', '', text.lower())
        # Normalize whitespace (keep single spaces for character comparison)
        text = ' '.join(text.split())
        return text
    
    ref_chars = normalize(ground_truth)
    hyp_chars = normalize(transcript)
    
    if len(ref_chars) == 0:
        return 1.0 if len(hyp_chars) == 0 else 0.0
    
    # Dynamic programming for Levenshtein distance at character level
    n = len(ref_chars)
    m = len(hyp_chars)
    
    # Use two rows to save memory for long strings
    prev_row = list(range(m + 1))
    curr_row = [0] * (m + 1)
    
    for i in range(1, n + 1):
        curr_row[0] = i
        for j in range(1, m + 1):
            if ref_chars[i - 1] == hyp_chars[j - 1]:
                curr_row[j] = prev_row[j - 1]
            else:
                curr_row[j] = min(
                    prev_row[j] + 1,      # deletion
                    curr_row[j - 1] + 1,  # insertion
                    prev_row[j - 1] + 1   # substitution
                )
        prev_row, curr_row = curr_row, prev_row
    
    # Calculate TER
    ter = prev_row[m] / n
    
    # Return accuracy (1 - TER), capped at 0.0 minimum
    return round(max(0.0, 1.0 - ter), 4)
'''


def print_eval_results(output_items, transcript_json_path, reference_tsv_path, output_file_path):
    """Print the evaluation results in a formatted table"""
    
    if not output_items:
        print("No evaluation results found.")
        return
    
    # Handle different input types
    if isinstance(output_items, str):
        json_data = json.loads(output_items)
        output_items = json_data.get("items", [])
    elif isinstance(output_items, dict):
        output_items = output_items.get("items", [])

    # Aggregate metrics across all items
    metric_scores = {}
    metric_counts = {}
    
    for item in output_items:
        if hasattr(item, 'results'):
            results = item.results
        elif isinstance(item, dict):
            results = item.get("results", [])
        else:
            results = []
            
        for result in results:
            if hasattr(result, 'name'):
                metric_name = result.name
                score = result.score
            elif isinstance(result, dict):
                metric_name = result.get("name", "unknown")
                score = result.get("score")
            else:
                continue

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
    
    # Format output
    key_len = max(len(key) for key in metric_averages.keys()) + 5 if metric_averages else 20
    value_len = 20
    full_len = key_len + value_len + 5
    
    print("\n" + "=" * full_len)
    print("Evaluation Results Summary".center(full_len))
    print("=" * full_len)
    print(f"Total Items Evaluated: {len(output_items)}")
    print("=" * full_len)
    
    print(f"{'Metric':<{key_len}} | {'Average Score'}")
    print("-" * (key_len) + "-+-" + "-" * value_len)
    
    for key in sorted(metric_averages.keys()):
        value = metric_averages[key]
        # Convert accuracy back to error rate for display
        if 'WER' in key or 'TER' in key:
            error_rate = (1.0 - value) * 100
            formatted_value = f"{value:.4f} (Error Rate: {error_rate:.2f}%)"
        else:
            formatted_value = f"{value:.4f}"
        print(f"{key:<{key_len}} | {formatted_value}")
    
    print("=" * full_len + "\n")
    print(f"Transcript JSON: {transcript_json_path}")
    print(f"Reference TSV: {reference_tsv_path}")
    print(f"Evaluation output: {output_file_path}")
    print(f"For detailed per-item results, see the output file.")
    print("\n" + "=" * full_len + "\n")


def create_dataset_from_json_and_tsv(
    transcript_json_path: str,
    reference_tsv_path: str,
    output_folder: str = "output",
    dataset_appendix: str = ""
) -> str:
    """
    Create evaluation dataset from transcript JSON and reference TSV files.
    
    Args:
        transcript_json_path: Path to the JSON file with transcription results
                             (contains 'phrases' array with 'text' fields)
        reference_tsv_path: Path to the TSV file with ground truth
                           (first column: audio filename, subsequent columns: ground truth text)
        output_folder: Folder to save the dataset file
        dataset_appendix: Optional appendix to add to the dataset filename
        
    Returns:
        str: Path to the created dataset JSONL file
    """
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    if not Path(transcript_json_path).exists():
        raise FileNotFoundError(f"Transcript JSON file not found: {transcript_json_path}")
    if not Path(reference_tsv_path).exists():
        raise FileNotFoundError(f"Reference TSV file not found: {reference_tsv_path}")
    
    # Read transcript JSON
    with open(transcript_json_path, 'r', encoding='utf-8') as f:
        transcript_data = json.load(f)
    
    # Extract phrases from JSON
    phrases = transcript_data.get("phrases", [])
    transcript_texts = [phrase.get("text", "") for phrase in phrases]
    
    # Read reference TSV
    reference_texts = []
    audio_filename = Path(transcript_json_path).stem  # Get base filename for reference
    
    with open(reference_tsv_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Split by tab - first column is audio file, rest is ground truth
            parts = line.split('\t')
            if len(parts) >= 2:
                # Combine all parts after filename as ground truth (in case of tabs in text)
                ground_truth = '\t'.join(parts[1:])
                reference_texts.append(ground_truth)
            elif len(parts) == 1:
                # If no tab, treat entire line as ground truth
                reference_texts.append(parts[0])
    
    # Validate lengths match
    if len(transcript_texts) != len(reference_texts):
        print(f"Warning: Transcript has {len(transcript_texts)} phrases, reference has {len(reference_texts)} lines.")
        print(f"Using minimum of both: {min(len(transcript_texts), len(reference_texts))} utterances.")
    
    # Create dataset file
    dataset_filename = f"wer_ter_eval_dataset_{Path(transcript_json_path).stem}{dataset_appendix}.jsonl"
    dataset_path = Path(output_folder) / dataset_filename
    
    # Write JSONL dataset
    with open(dataset_path, 'w', encoding='utf-8') as f:
        for i in range(min(len(transcript_texts), len(reference_texts))):
            dataset_item = {
                "audio": f"{audio_filename}_utterance_{i}",
                "transcript": transcript_texts[i],
                "ground_truth": reference_texts[i]
            }
            f.write(json.dumps(dataset_item) + '\n')
    
    print(f"Dataset created: {dataset_path}")
    print(f"Total utterances: {min(len(transcript_texts), len(reference_texts))}")
    return str(dataset_path)


def upload_dataset(dataset_path: str, project_client: AIProjectClient) -> DatasetVersion:
    """
    Upload the dataset file to the Foundry project.
    """
    import re
    
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
    
    if Path(dataset_path).stat().st_size == 0:
        raise ValueError(f"Dataset file is empty: {dataset_path}")
    
    datasets = list(project_client.datasets.list())
    # Sanitize dataset name: only alphanumeric, dashes, underscores allowed
    raw_name = Path(dataset_path).stem
    dataset_name = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_name)[:255]
    
    existing_versions = [d for d in datasets if d.name == dataset_name]
    if existing_versions:
        latest_version = max(d.version for d in existing_versions)
        new_version = int(latest_version) + 1
    else:
        new_version = 1

    print(f"Uploading dataset with name: {dataset_name}")
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


def create_code_based_evaluator(
    project_client: AIProjectClient, 
    evaluator_name: str, 
    evaluator_code: str,
    description: str
) -> EvaluatorVersion:
    """
    Creates a code-based evaluator for transcript quality assessment.
    
    Args:
        project_client: The AI project client instance
        evaluator_name: Name for the evaluator
        evaluator_code: Python code string containing the grade function
        description: Description of the evaluator
        
    Returns:
        EvaluatorVersion: The created evaluator version object
    """
    print(f"Creating code-based evaluator: {evaluator_name}...")
    
    try:
        code_evaluator = project_client.evaluators.create_version(
            name=evaluator_name,
            evaluator_version={
                "name": evaluator_name,
                "categories": [EvaluatorCategory.QUALITY],
                "display_name": evaluator_name,
                "description": description,
                "definition": {
                    "type": EvaluatorDefinitionType.CODE,
                    "code_text": evaluator_code,
                    "init_parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
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
                        "result": {
                            "type": "ordinal",
                            "desirable_direction": "increase",
                            "min_value": 0.0,
                            "max_value": 1.0,
                        }
                    },
                },
            },
        )
        print(f"Evaluator {code_evaluator.name} created successfully with Id {code_evaluator.id}")
        return code_evaluator
    except Exception as e:
        print(f"Error creating evaluator {evaluator_name}: {e}")
        raise e


def main(
    transcript_json_path: str,
    reference_tsv_path: str,
    output_folder: str = "./output",
    eval_run_name: str = "",
    eval_group_name: str = "",
    eval_object_id: str = "",
    dataset_id: str = "",
    dataset_appendix: str = "",
    setup_evaluators: bool = True
):
    """Main function to run WER/TER evaluation of transcripts."""
    
    # Change to the directory where this script is located
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv("./.env", override=True)

    # Check environment variables
    assert os.getenv("PROJECT_ENDPOINT") is not None, "PROJECT_ENDPOINT is not set in .env file"
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {output_folder}")

    # Setup connections
    try:
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
    except Exception as e:
        print(f"Error creating AIProjectClient: {e}")
        exit(1)
    
    try:
        client = project_client.get_openai_client()
    except Exception as e:
        print(f"Error creating OpenAI client: {e}")
        exit(1)

    # Create code-based evaluators
    evaluators_list = []
    if setup_evaluators:
        print("Creating code-based evaluators...")
        
        # Create WER evaluator
        wer_evaluator = create_code_based_evaluator(
            project_client,
            evaluator_name="code_WER_evaluator",
            evaluator_code=WER_EVALUATOR_CODE,
            description="Word Error Rate (WER) evaluator for transcript quality assessment. Returns 1-WER (accuracy)."
        )
        evaluators_list.append(wer_evaluator.name)
        
        # Create TER evaluator
        ter_evaluator = create_code_based_evaluator(
            project_client,
            evaluator_name="code_TER_evaluator",
            evaluator_code=TER_EVALUATOR_CODE,
            description="Token/Character Error Rate (TER) evaluator for transcript quality assessment. Returns 1-TER (accuracy)."
        )
        evaluators_list.append(ter_evaluator.name)

    # Setup eval group
    if eval_object_id == "" or eval_object_id is None:
        print("Preparing Eval Group...")
        
        # Get model configuration for the evaluators
        # Note: Code-based evaluators don't actually use the model, but the service
        # requires a model_config in initialization_parameters for the grader converter
        model_deployment = os.getenv("MODEL_DEPLOYMENT", "gpt-4o-mini")
        
        # Pass threshold configuration for WER/TER evaluators
        # This determines when an utterance is considered "passed" based on accuracy score (1 - error_rate)
        # Common threshold levels:
        #   - 0.9 (strict):   ≤10% error rate - high quality transcription required
        #   - 0.8 (moderate): ≤20% error rate - acceptable for most use cases
        #   - 0.5 (lenient):  ≤50% error rate - permissive, only flags severe errors
        pass_threshold = 0.9  # strict
        
        testing_criteria = []
        for evaluator_name in evaluators_list:
            testing_criteria.append({
                "type": "azure_ai_evaluator",
                "name": evaluator_name,
                "evaluator_name": evaluator_name,
                "data_mapping": {
                    "transcript": "{{item.transcript}}",
                    "ground_truth": "{{item.ground_truth}}",
                },
                "initialization_parameters": {
                    "deployment_name": model_deployment,
                    "pass_threshold": pass_threshold,
                },
            })
        
        data_source_config = {
            "type": "custom",
            "item_schema": {
                "type": "object",
                "properties": {
                    "audio": {"type": "string"},
                    "transcript": {"type": "string"},
                    "ground_truth": {"type": "string"},
                },
                "required": ["transcript", "ground_truth"],
            },
            "include_sample_schema": True,
        }
        
        sleeptimer = 120
        print(f"Waiting {sleeptimer} seconds for evaluators to be ready...")
        sleep(sleeptimer)
        
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
            print(f"Eval Group created with Id: {eval_object.id}")
            pprint(eval_object_response)
            eval_id = eval_object.id
        except Exception as e:
            print(f"Error retrieving eval group id: {e}")
            exit(1)
    else:
        print("Using existing Eval Group!")
        eval_id = eval_object_id
    
    print(f"\nUsing Eval ID: {eval_id}")

    # Prepare data and upload
    if dataset_id == "" or dataset_id is None:
        print("Creating dataset from JSON transcript and TSV reference...")
        dataset_path = create_dataset_from_json_and_tsv(
            transcript_json_path=transcript_json_path,
            reference_tsv_path=reference_tsv_path,
            output_folder=output_folder,
            dataset_appendix=dataset_appendix
        )
        print(f"Dataset created at: {dataset_path}")
        
        print("\nUploading dataset to Foundry project...")
        dataset = upload_dataset(
            dataset_path=dataset_path,
            project_client=project_client
        )
        print(f"Dataset uploaded with ID: {dataset.id} and Version: {dataset.version}")
        dataset_id = dataset.id

    # Create data source config for eval run
    data_source = CreateEvalJSONLRunDataSourceParam(
        type="jsonl",
        source=SourceFileID(
            type="file_id",
            id=dataset_id if dataset_id else "",
        ),
    )

    # Create Eval Run
    try:
        print("Creating Eval Run...")
        eval_run_object = client.evals.runs.create(
            eval_id=eval_id,
            name=eval_run_name,
            metadata={"team": "Audio-Evaluation", "scenario": f"{eval_run_name}"},
            data_source=data_source
        )
        print(f"Eval Run created with Id: {eval_run_object.id}")
        pprint(eval_run_object)
    except Exception as e:
        print(f"Error creating eval run: {e}")
        exit(1)
    
    try:
        print("Get Eval Run by Id")
        eval_run_response = client.evals.runs.retrieve(run_id=eval_run_object.id, eval_id=eval_id)
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
                output_file_path = Path(output_folder) / f"{run.id}_wer_ter_eval_output.json"
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    for item in output_items:
                        f.write(json.dumps(item.model_dump(), indent=4) + '\n')
                print(f"\nOUTPUT ITEMS (Total: {len(output_items)})")
            except Exception as e:
                print(f"Error retrieving output items: {e}")
                exit(1)

            print(f"{'-'*60}")
            print_eval_results(output_items, transcript_json_path, reference_tsv_path, output_file_path)
            print(f"{'-'*60}")
            print(f"Eval Run Status: {run.status}")
            print(f"Eval Run Report URL: {run.report_url}")
            break
        sleep(5)
        time.sleep(5)
        print("Waiting for eval run to complete...")
    
    # Cleanup old evaluator versions
    if setup_evaluators:
        print("\nCleaning up old evaluator versions...")
        for evaluator_name in evaluators_list:
            try:
                versions = list(project_client.evaluators.list_versions(name=evaluator_name))
                if versions:
                    current_version = max(int(v.version) for v in versions)
                    print(f"Found {current_version} versions of {evaluator_name}")
                    for version in range(1, current_version):
                        print(f"Deleting version {version} of {evaluator_name}")
                        project_client.evaluators.delete_version(
                            name=evaluator_name,
                            version=version,
                        )
            except Exception as e:
                print(f"Error cleaning up {evaluator_name}: {e}")


if __name__ == "__main__":
    # Example usage - update these paths for your data
    transcript_json_path = ".\\sampleTranscriptEvalDataset\\sample1 - Insurance - Customer calls about cancelation of service_transcribe.json"
    reference_tsv_path = ".\\sampleTranscriptEvalDataset\\sample1_reference.tsv"
    dataset_appendix = f"_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    main(
        transcript_json_path=transcript_json_path,
        reference_tsv_path=reference_tsv_path,
        output_folder="./output",
        eval_group_name="WER_TER_Transcript_Evaluator_Group",
        eval_object_id="",  # Leave empty to create new, or provide existing eval ID
        eval_run_name="WER TER Evaluation Run",
        dataset_id="",  # Leave empty to create new, or provide existing dataset ID
        dataset_appendix=dataset_appendix,
        setup_evaluators=True
    )
