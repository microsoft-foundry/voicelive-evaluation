import os
from posixpath import basename
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.projects import AIProjectClient
from azure.ai.evaluation import IntentResolutionEvaluator, ToolCallAccuracyEvaluator, TaskAdherenceEvaluator, ResponseCompletenessEvaluator, AzureOpenAIModelConfiguration, evaluate, GroundednessEvaluator, CoherenceEvaluator, FluencyEvaluator, RelevanceEvaluator
from dotenv import load_dotenv
from pathlib import Path
import json

# Operational Metrics Into Results Injector
class OperationalMetricsEvaluator:
    """Propagate operational metrics to the final evaluation results"""
    def __init__(self):
        pass
    def __call__(self, *, metrics: dict, **kwargs):
        return metrics

# Pretty print evaluation results
def print_eval_results(results, input_path, output_path):
    """Print the evaluation results in a formatted table"""    
    metrics = results.get("metrics", {})

    # Get the maximum length for formatting
    key_len = max(len(key) for key in metrics.keys()) + 5
    value_len = 20
    full_len = key_len + value_len + 5
    
    # Format the header
    print("\n" + "=" * full_len)
    print("Evaluation Results".center(full_len))
    print("=" * full_len)
    
    # Print all metrics, see evaluation output file for full details
    print(f"{'Metric':<{key_len}} | {'Value'}")
    print("-" * (key_len) + "-+-" + "-" * value_len)
    
    for key, value in sorted(metrics.items()):
        if isinstance(value, float):
            formatted_value = f"{value:.2f}"
        else:
            formatted_value = str(value)
        
        print(f"{key:<{key_len}} | {formatted_value}")
    
    print("=" * full_len + "\n")

    # Print additional information
    print(f"Evaluation input: {input_path}")
    print(f"Evaluation output: {output_path}")
    if results.get("studio_url") is not None:
        print(f"AI Foundry URL: {results['studio_url']}")

    print("\n" + "=" * full_len + "\n")

# Custom Class for Speech Evaluation // MOCK UP!
class TranscriptionQualityEvaluator():
    """Evaluate the quality of speech transcription."""
    def __init__(self):
        pass
    def __call__(self, *, query: list, **kwargs):

        transcription_quality = {
            "transcription_quality_wer": 0.1,
            "transcription_quality_result": "pass",
            "transcription_quality_threshold": 0.2
        }
        return transcription_quality

def main(eval_input_path: str, eval_name: str, eval_description: str, output_folder: str):
    """ Main function to run the evaluation of voice agent sessions."""
    #Change to the directory where this script is located
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Load environment variables from .env file
    load_dotenv("./.env", override=True)

    # Check environment variables were loaded correctly
    assert os.getenv("AOAI_ENDPOINT") is not None, "AOAI_ENDPOINT is not set in .env file"
    aoai_endpoint = os.getenv("AOAI_ENDPOINT")
    assert os.getenv("AOAI_API_KEY") is not None, "AOAI_API_KEY is not set in .env file"
    aoai_api_key = os.getenv("AOAI_API_KEY")
    assert os.getenv("AOAI_DEPLOYMENT_NAME") is not None, "AOAI_DEPLOYMENT_NAME is not set in .env file"
    aoai_deployment_name = os.getenv("AOAI_DEPLOYMENT_NAME")
    assert os.getenv("AOAI_REASONING_DEPLOYMENT_NAME") is not None, "AOAI_REASONING_DEPLOYMENT_NAME is not set in .env file"
    aoai_reasoning_deployment_name = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
    assert os.getenv("AOAI_API_VERSION") is not None, "AOAI_API_VERSION is not set in .env file"
    aoai_api_version = os.getenv("AOAI_API_VERSION")
    assert os.getenv("AZURE_SUBSCRIPTION_ID") is not None, "AZURE_SUBSCRIPTION_ID is not set in .env file"
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    assert os.getenv("PROJECT_NAME") is not None, "PROJECT_NAME is not set in .env file"
    project_name = os.getenv("PROJECT_NAME")
    assert os.getenv("PROJECT_ENDPOINT") is not None, "PROJECT_ENDPOINT is not set in .env file"
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    assert os.getenv("RESOURCE_GROUP_NAME") is not None, "RESOURCE_GROUP_NAME is not set in .env file"
    resource_group_name = os.getenv("RESOURCE_GROUP_NAME")
    assert os.getenv("HUB_RESOURCE_GROUP_NAME") is not None, "HUB_RESOURCE_GROUP_NAME is not set in .env file"
    hub_resource_group_name = os.getenv("HUB_RESOURCE_GROUP_NAME")
    assert os.getenv("HUB_PROJECT_NAME") is not None, "HUB_PROJECT_NAME is not set in .env file"
    hub_project_name = os.getenv("HUB_PROJECT_NAME")
    assert os.getenv("HUB_PROJECT_CONNECTION_STRING") is not None, "HUB_PROJECT_CONNECTION_STRING is not set in .env file"
    hub_project_connection_string = os.getenv("HUB_PROJECT_CONNECTION_STRING")
    
    # Setup connections and prepare tools
    # Create the AIProjectClient with the necessary parameters
    project_client = AIProjectClient(
        credential=DefaultAzureCredential(),
        endpoint=project_endpoint
    )

    # Foundry project config (uncomment depending on type of Foundry setup used)
    # Foundry FDP setup project config:
    azure_ai_project = project_endpoint

    # # Foundry HUB setup project config:
    # azure_ai_project = {
    #     "subscription_id": subscription_id,
    #     "project_name": hub_project_name,
    #     "resource_group_name": hub_resource_group_name
    # }

    ## Create the model configuration for the evaluators
    model_config = AzureOpenAIModelConfiguration(
        azure_endpoint=aoai_endpoint,
        api_key=aoai_api_key,
        azure_deployment=aoai_deployment_name,
        api_version=aoai_api_version
    )

    reasoning_model_config = {
        "azure_deployment": aoai_reasoning_deployment_name,
        "api_key": aoai_api_key,
        "azure_endpoint": aoai_endpoint,
        "api_version": aoai_api_version
    }

    # Initialize evaluators with the model configuration
    ## Reasoning model evaluators for agents
    intent_resolution_evaluator = IntentResolutionEvaluator(model_config=reasoning_model_config, is_reasoning_model=True, threshold=3) # measures the extent of which an agent identifies the correct intent from a user query. Scale: integer 1-5. Higher is better.
    task_adherence_evaluator = TaskAdherenceEvaluator(model_config=reasoning_model_config, is_reasoning_model=True, threshold=1) # measures the extent of which an agent’s final response adheres to the task based on its system message and a user query. Scale: integer 1-5. Higher is better.
    response_completeness_evaluator = ResponseCompletenessEvaluator(model_config=reasoning_model_config, is_reasoning_model=True, threshold=3) # measures the extent of which an agent’s response is complete and addresses the user query. Scale: integer 1-5. Higher is better.
    ### Requires tool configuration to be provided in the conversation data
    tool_call_accuracy_evaluator = ToolCallAccuracyEvaluator(model_config=reasoning_model_config, is_reasoning_model=True, threshold=3) # evaluates the agent’s ability to select the appropriate tools, and process correct parameters from previous steps. Scale: float 0-1. Higher is better.
    ## Non-reasoning model evaluators
    coherence_evaluator = CoherenceEvaluator(model_config=model_config, threshold=3) # measures the extent of which an agent’s response is coherent and logically consistent. Scale: integer 1-5. Higher is better.
    fluency_evaluator = FluencyEvaluator(model_config=model_config, threshold=3) # measures the extent of which an agent’s response is fluent and grammatically correct. Scale: integer 1-5. Higher is better.
    relevance_evaluator = RelevanceEvaluator(model_config=model_config, threshold=3) # measures the extent of which an agent’s response is relevant to the user query. Scale: integer 1-5. Higher is better.
    ### Requires context to be provided in the conversation data
    groundedness_evaluator = GroundednessEvaluator(model_config=model_config, threshold=3) # measures the extent of which an agent’s response is grounded in the context provided by the user. Scale: integer 1-5. Higher is better.
    ## Operational Metrics Injection for custom metrics
    operational_metrics_evaluator = OperationalMetricsEvaluator()

    # Create output folder if it does not exist and set output file name
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    eval_output_path = os.path.join(
        output_folder,
        os.path.splitext(os.path.basename(eval_input_path))[0] + "_results.json"
    )

    response = evaluate(
        data=eval_input_path,
        evaluation_name=eval_name,
        description=eval_description,
        evaluators={
            # Agent quality evaluators
            # "transcription_quality": TranscriptionQualityEvaluator(),
            "operational_metrics": operational_metrics_evaluator,
            "intent_resolution": intent_resolution_evaluator,
            "task_adherence": task_adherence_evaluator,
            # "response_completeness": response_completeness_evaluator,
            # "tool_call_accuracy": tool_call_accuracy_evaluator,
            # Other evaluators
            # "groundedness": groundedness_evaluator,
            # "coherence": coherence_evaluator,
            # "fluency": fluency_evaluator,
            # "relevance": relevance_evaluator
        },
        evaluator_config={
            "response_completeness": {
                "column_mapping": {
                    "ground_truth": "${data.ground_truth}",
                    "response": "${data.response}"
                }
            },
            "groundedness": {
                "column_mapping": {
                    "query": "${data.query}",
                    "context": "${data.ground_truth}",
                    "response": "${data.response}"
                } 
            },
        },
        azure_ai_project=azure_ai_project,
        # Optionally, provide an output path to dump a JSON file of metric summary, row-level data, and the metric and Azure AI project URL.
        output_path=eval_output_path
    )

    # Format and print the evaluation results
    print_eval_results(response, eval_input_path, eval_output_path)

# Main entry point for the script
if __name__ == "__main__":
    try:
        ## Change the eval_input_path to point to your evaluation data file
        eval_input_path = f"./sample_outputs/2025-09-16_18-29-39_eiffel_conversation/evaluation_2025-09-16_18-29-39.jsonl"
        eval_name = "VL eval dataset 3.4" #"evaluation_sess_5VcrO46hIexnJoctwZ3tbj",
        eval_description = f"Evaluation of Voice Live API agent: {basename(eval_input_path)}"
        ## Set output folder as a parameter
        output_folder = "./output"
        # Run the main evaluation function
        main(
            eval_input_path=eval_input_path,
            eval_name=eval_name,
            eval_description=eval_description,
            output_folder=output_folder
        )
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        exit(0)
