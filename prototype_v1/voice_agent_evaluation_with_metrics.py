"""
Voice Agent Evaluation with Voice Metrics - Foundry Integration Example

This script demonstrates how to integrate the voice metrics evaluators
(Transcription Latency, Response Latency, Audio Delivery, Turn Alignment)
with the main evaluation pipeline that runs in Azure AI Foundry.

This is an extended version of voice_agent_evaluation.py that includes:
1. All standard agent evaluators (task completion, tool calls, etc.)
2. Four separate voice metrics evaluators for granular pass rate visibility:
   - Transcription Latency Evaluator
   - Response Latency Evaluator
   - Audio Delivery Evaluator
   - Turn Alignment Evaluator

Usage:
    python voice_agent_evaluation_with_metrics.py

Configuration:
    Set the evaluation_scenario variable in __main__ to choose between:
    - 'VoiceMetricsDemo': Demonstrates voice metrics evaluation
    - 'Example1': Custom transcript evaluator (legacy)
    - 'Example2': Agent builtin evaluators only

Author: Voice Live Evaluation Team
Date: January 2026
"""

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

# Import voice metrics evaluator functions
from voice_metrics_evaluator import (
    create_all_voice_metrics_evaluators,
    get_all_voice_metrics_testing_criteria,
    analyze_voice_metrics_locally,
    print_voice_metrics_summary,
    EVALUATOR_CONFIGS,
)

# Suppress Pydantic serialization warnings from Azure AI SDK
warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
warnings.filterwarnings('ignore', message='.*Expected `float`.*')
warnings.filterwarnings('ignore', message='.*serialized value may not be as expected.*')


def print_eval_results(output_items, transcriptFilePath, referenceTranscriptFilePath, output_file_path):
    """Print the evaluation results in a formatted table"""
    
    if not output_items:
        print("No evaluation results found.")
        return
    
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
    
    key_len = max(len(key) for key in metric_averages.keys()) + 5 if metric_averages else 20
    value_len = 20
    full_len = key_len + value_len + 5
    
    print("\n" + "=" * full_len)
    print("Evaluation Results Summary".center(full_len))
    print("=" * full_len)
    print(f"Total Items Evaluated: {len(output_items)}")
    print("=" * full_len)
    
    # Separate voice metrics from agent metrics
    voice_metrics = ['transcriptionLatencyEvaluator', 'responseLatencyEvaluator', 
                     'audioDeliveryEvaluator', 'turnAlignmentEvaluator']
    
    # Print agent metrics first
    agent_metrics = {k: v for k, v in metric_averages.items() if k not in voice_metrics}
    if agent_metrics:
        print(f"\n{'Agent Evaluators'}")
        print("-" * (key_len) + "-+-" + "-" * value_len)
        print(f"{'Metric':<{key_len}} | {'Average Score'}")
        print("-" * (key_len) + "-+-" + "-" * value_len)
        for key in sorted(agent_metrics.keys()):
            value = agent_metrics[key]
            formatted_value = f"{value:.2f}"
            print(f"{key:<{key_len}} | {formatted_value}")
    
    # Print voice metrics
    voice_metric_results = {k: v for k, v in metric_averages.items() if k in voice_metrics}
    if voice_metric_results:
        print(f"\n{'Voice Metrics Evaluators'}")
        print("-" * (key_len) + "-+-" + "-" * value_len)
        print(f"{'Metric':<{key_len}} | {'Average Score'}")
        print("-" * (key_len) + "-+-" + "-" * value_len)
        for key in sorted(voice_metric_results.keys()):
            value = voice_metric_results[key]
            formatted_value = f"{value:.2f}"
            print(f"{key:<{key_len}} | {formatted_value}")
    
    print("=" * full_len + "\n")
    print(f"Generated Audio transcript: {transcriptFilePath}")
    print(f"Reference transcript: {referenceTranscriptFilePath}")
    print(f"Evaluation output: {output_file_path}")
    print(f"For detailed per-item results, see the output file.")
    print("\n" + "=" * full_len + "\n")


def upload_dataset_from_transcripts(dataset_path: str, project_client: AIProjectClient) -> DatasetVersion:
    """Upload the dataset file to the Foundry project."""
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")
    
    if Path(dataset_path).stat().st_size == 0:
        raise ValueError(f"Dataset file is empty: {dataset_path}")
    
    datasets = list(project_client.datasets.list())
    dataset_name = Path(dataset_path).stem
    existing_versions = [d for d in datasets if d.name == dataset_name]
    if existing_versions:
        latest_version = max(d.version for d in existing_versions)
        new_version = int(latest_version) + 1
    else:
        new_version = 1

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


def setup_voice_metrics_evaluators(project_client: AIProjectClient) -> bool:
    """
    Create all four voice metrics evaluators in Foundry.
    
    Args:
        project_client: AIProjectClient instance
        
    Returns:
        True if all evaluators created successfully
    """
    print("\n" + "="*60)
    print("SETTING UP VOICE METRICS EVALUATORS")
    print("="*60)
    
    try:
        create_all_voice_metrics_evaluators(project_client)
        print("\n✓ All voice metrics evaluators created successfully")
        return True
    except Exception as e:
        print(f"\n✗ Error creating voice metrics evaluators: {e}")
        return False


def main(
    eval_input_path: str,
    referenceTranscriptFilePath: str = "",
    output_folder: str = "./output",
    eval_run_name: str = f"Run {datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
    eval_run_scenario: str = "",
    eval_group_name: str = "",
    eval_object_id: str = "",
    dataset_id: str = "",
    dataset_appendix: str = "",
    include_voice_metrics: bool = True,
    include_agent_evaluators: bool = True,
    setup_evaluators: bool = False,
    run_local_preview: bool = True
):
    """
    Main function to run the evaluation of voice agent sessions.
    
    Args:
        eval_input_path: Path to the evaluation dataset (JSONL)
        referenceTranscriptFilePath: Path to reference transcripts (for custom evaluator)
        output_folder: Folder to save evaluation outputs
        eval_run_name: Name for this evaluation run
        eval_run_scenario: Description of the evaluation scenario
        eval_group_name: Name for the evaluation group
        eval_object_id: Existing eval group ID (empty to create new)
        dataset_id: Existing dataset ID (empty to upload new)
        dataset_appendix: Appendix for dataset naming
        include_voice_metrics: Whether to include voice metrics evaluators
        include_agent_evaluators: Whether to include agent evaluators
        setup_evaluators: Whether to create/update custom evaluators
        run_local_preview: Whether to run local preview before Foundry evaluation
    """
    # Change to the directory where this script is located
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv("./.env", override=True)

    # Check environment variables
    aoai_deployment_name = os.getenv("AOAI_DEPLOYMENT_NAME")
    assert os.getenv("AOAI_REASONING_DEPLOYMENT_NAME") is not None, "AOAI_REASONING_DEPLOYMENT_NAME is not set"
    aoai_reasoning_deployment_name = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
    assert os.getenv("PROJECT_ENDPOINT") is not None, "PROJECT_ENDPOINT is not set"
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {output_folder}")

    # Setup connections
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=project_endpoint
    )
    model_deployment_name = aoai_deployment_name
    reasoning_model_deployment_name = aoai_reasoning_deployment_name
    client = project_client.get_openai_client()

    # Run local preview if requested
    if run_local_preview and include_voice_metrics:
        print("\n" + "="*60)
        print("LOCAL PREVIEW: Voice Metrics Analysis")
        print("="*60)
        try:
            stats = analyze_voice_metrics_locally(eval_input_path)
            print_voice_metrics_summary(stats)
        except Exception as e:
            print(f"Warning: Could not run local preview: {e}")

    # Setup voice metrics evaluators if requested
    if setup_evaluators and include_voice_metrics:
        setup_voice_metrics_evaluators(project_client)

    # Build data source config with metrics fields
    data_source_config = {
        "type": "custom",
        "item_schema": {
            "type": "object",
            "properties": {
                "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
                "tool_definitions": {
                    "anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]
                },
                "tool_calls": {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]},
                "response": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
                # Voice metrics fields
                "metrics": {"type": "object"},
            },
            "required": ["query", "response"],
        },
        "include_sample_schema": True,
    }

    # Build testing criteria
    testing_criteria = []
    
    # Add agent evaluators if requested
    if include_agent_evaluators:
        agent_criteria = [
            # Intent Resolution
            {
                "type": "azure_ai_evaluator",
                "name": "intent_resolution",
                "evaluator_name": "builtin.intent_resolution",
                "initialization_parameters": {
                    "deployment_name": f"{reasoning_model_deployment_name}",
                    "is_reasoning_model": True
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                },
            },
            # Task Adherence
            {
                "type": "azure_ai_evaluator",
                "name": "task_adherence",
                "evaluator_name": "builtin.task_adherence",
                "initialization_parameters": {
                    "deployment_name": f"{reasoning_model_deployment_name}",
                    "is_reasoning_model": True
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                },
            },
            # Task Completion
            {
                "type": "azure_ai_evaluator",
                "name": "task_completion",
                "evaluator_name": "builtin.task_completion",
                "initialization_parameters": {
                    "deployment_name": f"{reasoning_model_deployment_name}",
                    "is_reasoning_model": True
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                },
            },
            # Groundedness
            {
                "type": "azure_ai_evaluator",
                "name": "groundedness",
                "evaluator_name": "builtin.groundedness",
                "initialization_parameters": {
                    "deployment_name": f"{model_deployment_name}",
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                    "response": "{{item.response}}",
                },
            },
            # Relevance
            {
                "type": "azure_ai_evaluator",
                "name": "relevance",
                "evaluator_name": "builtin.relevance",
                "initialization_parameters": {
                    "deployment_name": f"{reasoning_model_deployment_name}",
                    "is_reasoning_model": True
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                },
            },
            # Tool Call Accuracy
            {
                "type": "azure_ai_evaluator",
                "name": "tool_call_accuracy",
                "evaluator_name": "builtin.tool_call_accuracy",
                "initialization_parameters": {
                    "deployment_name": f"{reasoning_model_deployment_name}",
                    "is_reasoning_model": True
                },
                "data_mapping": {
                    "query": "{{item.query}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                    "tool_calls": "{{item.tool_calls}}",
                    "response": "{{item.response}}",
                },
            },
        ]
        testing_criteria.extend(agent_criteria)
        print(f"Added {len(agent_criteria)} agent evaluators")
    
    # Add voice metrics evaluators if requested
    if include_voice_metrics:
        voice_criteria = get_all_voice_metrics_testing_criteria()
        testing_criteria.extend(voice_criteria)
        print(f"Added {len(voice_criteria)} voice metrics evaluators")
    
    print(f"\nTotal evaluators: {len(testing_criteria)}")
    for tc in testing_criteria:
        print(f"  - {tc['name']}")

    # Setup eval group
    if eval_object_id == "" or eval_object_id is None:
        print("\nPreparing Eval Group...")
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

    # Prepare and upload dataset
    if dataset_id == "" or dataset_id is None:
        dataset_path = eval_input_path
        print("Uploading dataset to Foundry project...")
        dataset = upload_dataset_from_transcripts(
            dataset_path=dataset_path,
            project_client=project_client
        )
        print(f"Dataset uploaded with ID: {dataset.id}")
        dataset_id = dataset.id

    # Create data source for eval run
    data_source = CreateEvalJSONLRunDataSourceParam(
        type="jsonl",
        source=SourceFileID(
            type="file_id",
            id=dataset_id if dataset_id else "",
        ),
    )

    # Create and run evaluation
    try:
        print("Creating Eval Run...")
        eval_run_object = client.evals.runs.create(
            eval_id=eval_id,
            name=eval_run_name,
            metadata={
                "team": "Audio-Evaluation",
                "scenario": f"{eval_run_scenario}",
                "includes_voice_metrics": str(include_voice_metrics),
            },
            data_source=data_source
        )
        print(f"Eval Run created with Id: {eval_run_object.id}")
        pprint(eval_run_object)
    except Exception as e:
        print(f"Error creating eval run: {e}")
        exit(1)

    # Wait for completion
    print("\n----Waiting for Eval Run to complete----\n")
    while True:
        run = client.evals.runs.retrieve(run_id=eval_run_object.id, eval_id=eval_id)
        if run.status == "completed" or run.status == "failed":
            try:
                output_items = list(client.evals.runs.output_items.list(run_id=run.id, eval_id=eval_id))
                output_file_path = Path(output_folder) / f"{run.id}_eval_output.jsonl"
                with open(output_file_path, 'w', encoding='utf-8') as f:
                    for item in output_items:
                        f.write(json.dumps(item.model_dump(), indent=4) + '\n')
                print(f"\nOUTPUT ITEMS (Total: {len(output_items)})")
            except Exception as e:
                print(f"Error retrieving output items: {e}")
                exit(1)

            print(f"{'-'*60}")
            print_eval_results(output_items, eval_input_path, referenceTranscriptFilePath, output_file_path)
            print(f"{'-'*60}")
            print(f"Eval Run Status: {run.status}")
            print(f"Eval Run Report URL: {run.report_url}")
            break
        sleep(5)
        print("Waiting for eval run to complete...")
    
    return run.status, run.report_url


if __name__ == "__main__":
    
    # ==========================================================================
    # CONFIGURATION
    # ==========================================================================
    
    evaluation_scenario = 'VoiceMetricsDemo'
    
    if evaluation_scenario == 'VoiceMetricsDemo':
        # Voice Metrics Evaluation Demo
        # This configuration demonstrates the voice metrics evaluators
        # using the DataOcean Demo1 aggregate dataset
        
        eval_input_path = "./local_datasets/DataOcean/Demo1-20251230/results_2026-01-06_14-50-42/2026-01-06_14-50-42_aggregate_Demo1-20251230.jsonl"
        referenceTranscriptFilePath = ""
        dataset_id = ""  # Leave empty to upload new dataset
        eval_object_id = ""  # Leave empty to create new eval group
        eval_group_name = "Voice Agent Evaluation with Metrics"
        eval_run_scenario = "Voice Metrics Demo Run"
        
        # Configuration options
        include_voice_metrics = True  # Include the 4 voice metrics evaluators
        include_agent_evaluators = True  # Include standard agent evaluators
        setup_evaluators = True  # Create/update voice metrics evaluators in Foundry
        run_local_preview = True  # Run local analysis before Foundry evaluation
        
    elif evaluation_scenario == 'VoiceMetricsOnly':
        # Voice Metrics Only - No agent evaluators
        # Useful for quick voice quality checks
        
        eval_input_path = "./local_datasets/DataOcean/Demo1-20251230/results_2026-01-06_14-50-42/2026-01-06_14-50-42_aggregate_Demo1-20251230.jsonl"
        referenceTranscriptFilePath = ""
        dataset_id = ""
        eval_object_id = ""
        eval_group_name = "Voice Metrics Only Evaluation"
        eval_run_scenario = "Voice Metrics Only Run"
        
        include_voice_metrics = True
        include_agent_evaluators = False  # Skip agent evaluators
        setup_evaluators = True
        run_local_preview = True
        
    elif evaluation_scenario == 'AgentOnly':
        # Agent Evaluators Only - No voice metrics
        # Standard agent evaluation without voice metrics
        
        eval_input_path = "./sample_outputs/2025-11-26_16-53-40_Eiffel_Tower_Visit_1/2025-11-26_16-53-40_Eiffel_Tower_Visit_1.jsonl"
        referenceTranscriptFilePath = ""
        dataset_id = ""
        eval_object_id = ""
        eval_group_name = "Agent Evaluation Only"
        eval_run_scenario = "Agent Only Run"
        
        include_voice_metrics = False  # Skip voice metrics
        include_agent_evaluators = True
        setup_evaluators = False
        run_local_preview = False
        
    else:
        # Default/Example configuration
        eval_input_path = "./sample_outputs/2025-11-26_16-53-40_Eiffel_Tower_Visit_1/2025-11-26_16-53-40_Eiffel_Tower_Visit_1.jsonl"
        referenceTranscriptFilePath = ""
        dataset_id = ""
        eval_object_id = ""
        eval_group_name = "Default Evaluation Group"
        eval_run_scenario = "Default Run"
        include_voice_metrics = True
        include_agent_evaluators = True
        setup_evaluators = True
        run_local_preview = True

    # ==========================================================================
    # RUN EVALUATION
    # ==========================================================================
    
    print("\n" + "="*70)
    print("VOICE AGENT EVALUATION WITH METRICS")
    print("="*70)
    print(f"Scenario: {evaluation_scenario}")
    print(f"Input: {eval_input_path}")
    print(f"Voice Metrics: {'Enabled' if include_voice_metrics else 'Disabled'}")
    print(f"Agent Evaluators: {'Enabled' if include_agent_evaluators else 'Disabled'}")
    print("="*70 + "\n")
    
    status, report_url = main(
        eval_input_path=eval_input_path,
        referenceTranscriptFilePath=referenceTranscriptFilePath,
        output_folder="./output",
        eval_group_name=eval_group_name,
        eval_object_id=eval_object_id,
        eval_run_name=f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')} {eval_run_scenario}",
        eval_run_scenario=eval_run_scenario,
        dataset_id=dataset_id,
        include_voice_metrics=include_voice_metrics,
        include_agent_evaluators=include_agent_evaluators,
        setup_evaluators=setup_evaluators,
        run_local_preview=run_local_preview,
    )
    
    print("\n" + "="*70)
    print("EVALUATION COMPLETE")
    print("="*70)
    print(f"Status: {status}")
    print(f"Report: {report_url}")
    print("="*70 + "\n")
