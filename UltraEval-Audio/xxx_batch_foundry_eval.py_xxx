#!/usr/bin/env python3
"""
Azure AI Foundry Batch Evaluator

This script demonstrates how to run batch evaluation on completed results.
It reads a JSONL file with post-processed results and runs Azure AI Foundry evaluation on all samples at once.

Usage:
    python batch_foundry_eval.py --input results.jsonl --evaluator azure-ai-combined-four --output batch_results.jsonl
"""

import argparse
import json
import os
import tempfile
from typing import Dict, List, Any
import logging

# Import Azure AI evaluation components
try:
    from azure.ai.evaluation import evaluate
    from azure.ai.evaluation.evaluators import (
        IntentResolutionEvaluator, TaskAdherenceEvaluator, 
        ResponseCompletenessEvaluator, GroundednessEvaluator,
        CoherenceEvaluator, FluencyEvaluator, RelevanceEvaluator,
        ToolCallAccuracyEvaluator
    )
    from azure.ai.evaluation._model_configurations import AzureOpenAIModelConfiguration
    batch_evaluation_available = True
except ImportError:
    print("Azure AI evaluation SDK not available")
    batch_evaluation_available = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatchFoundryEvaluator:
    """Batch evaluator for Azure AI Foundry metrics"""
    
    def __init__(self, evaluator_config: str):
        self.evaluator_config = evaluator_config
        self.evaluators_config = self._parse_evaluator_config()
        
    def _parse_evaluator_config(self) -> Dict[str, Dict[str, Any]]:
        """Parse evaluator configuration"""
        if self.evaluator_config == "azure-ai-combined-four":
            return {
                'intent_resolution': {'threshold': 3},
                'task_adherence': {'threshold': 3},
                'response_completeness': {'threshold': 3},
                'groundedness': {'threshold': 3}
            }
        elif self.evaluator_config == "azure-ai-combined-agent":
            return {
                'intent_resolution': {'threshold': 3},
                'task_adherence': {'threshold': 3},
                'response_completeness': {'threshold': 3},
                'groundedness': {'threshold': 3},
                'tool_call_accuracy': {'threshold': 3}
            }
        elif self.evaluator_config == "azure-ai-combined-quality":
            return {
                'coherence': {'threshold': 3},
                'fluency': {'threshold': 3},
                'relevance': {'threshold': 3},
                'groundedness': {'threshold': 3}
            }
        elif self.evaluator_config.startswith("azure-ai-"):
            # Single evaluator
            evaluator_type = self.evaluator_config.replace("azure-ai-", "").replace("-", "_")
            return {evaluator_type: {'threshold': 3}}
        else:
            raise ValueError(f"Unknown evaluator config: {self.evaluator_config}")
    
    def _setup_azure_evaluators(self):
        """Setup Azure AI evaluators"""
        if not batch_evaluation_available:
            raise RuntimeError("Azure AI evaluation SDK not available")
            
        # Get Azure OpenAI configuration
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AOAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AOAI_API_KEY")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AOAI_DEPLOYMENT_NAME")
        reasoning_deployment = os.getenv("AZURE_OPENAI_REASONING_DEPLOYMENT") or os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION") or os.getenv("AOAI_API_VERSION", "2024-10-21")
        
        if not all([azure_endpoint, api_key, deployment_name]):
            raise ValueError("Azure OpenAI configuration missing")
            
        # Standard model configuration
        model_config = AzureOpenAIModelConfiguration(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            azure_deployment=deployment_name,
            api_version=api_version
        )
        
        # Reasoning model configuration (if available)
        if reasoning_deployment:
            reasoning_config = {
                "azure_deployment": reasoning_deployment,
                "api_key": api_key,
                "azure_endpoint": azure_endpoint,
                "api_version": api_version
            }
        else:
            reasoning_config = model_config
            
        azure_evaluators = {}
        evaluator_config = {}
        
        # Create Azure AI evaluator instances
        for eval_name, config in self.evaluators_config.items():
            threshold = config.get('threshold', 3)
            
            if eval_name == 'intent_resolution':
                azure_evaluators['intent_resolution'] = IntentResolutionEvaluator(
                    model_config=reasoning_config,
                    is_reasoning_model=bool(reasoning_deployment),
                    threshold=threshold
                )
            elif eval_name == 'task_adherence':
                azure_evaluators['task_adherence'] = TaskAdherenceEvaluator(
                    model_config=reasoning_config,
                    is_reasoning_model=bool(reasoning_deployment),
                    threshold=threshold
                )
            elif eval_name == 'response_completeness':
                azure_evaluators['response_completeness'] = ResponseCompletenessEvaluator(
                    model_config=reasoning_config,
                    is_reasoning_model=bool(reasoning_deployment),
                    threshold=threshold
                )
                evaluator_config['response_completeness'] = {
                    "column_mapping": {
                        "ground_truth": "${data.ground_truth}",
                        "response": "${data.response}"
                    }
                }
            elif eval_name == 'groundedness':
                azure_evaluators['groundedness'] = GroundednessEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
                evaluator_config['groundedness'] = {
                    "column_mapping": {
                        "query": "${data.query}",
                        "context": "${data.context}",
                        "response": "${data.response}"
                    }
                }
            elif eval_name == 'coherence':
                azure_evaluators['coherence'] = CoherenceEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
            elif eval_name == 'fluency':
                azure_evaluators['fluency'] = FluencyEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
            elif eval_name == 'relevance':
                azure_evaluators['relevance'] = RelevanceEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
            elif eval_name == 'tool_call_accuracy':
                azure_evaluators['tool_call_accuracy'] = ToolCallAccuracyEvaluator(
                    model_config=reasoning_config,
                    is_reasoning_model=bool(reasoning_deployment),
                    threshold=threshold
                )
                
        return azure_evaluators, evaluator_config
    
    def evaluate_batch(self, input_file: str, output_file: str):
        """Run batch evaluation on JSONL results file"""
        logger.info(f"Loading results from: {input_file}")
        
        # Read input JSONL file and extract post-processed results
        evaluation_data = []
        sample_metadata = []
        
        with open(input_file, 'r', encoding='utf-8') as f:
            current_sample = {}
            for line in f:
                entry = json.loads(line.strip())
                entry_type = entry.get('type')
                entry_id = entry.get('id')
                
                if entry_type == 'post_process':
                    # Extract post-processed content
                    response = entry['data']['content']
                    current_sample[entry_id] = {'response': response}
                elif entry_type == 'prompt':
                    # Extract query/context information
                    if entry_id not in current_sample:
                        current_sample[entry_id] = {}
                    prompt_content = entry['data']['content']
                    # Try to extract query from prompt (this may need adjustment based on prompt format)
                    current_sample[entry_id]['query'] = str(prompt_content)
                    
        # Convert to evaluation format
        for sample_id, sample_data in current_sample.items():
            if 'response' in sample_data:
                eval_entry = {
                    'query': sample_data.get('query', ''),
                    'response': sample_data['response'],
                    'context': sample_data.get('context', sample_data['response']),  # Use response as context if no context
                    'ground_truth': sample_data.get('ground_truth', sample_data['response'])  # Use response as ground truth if no GT
                }
                evaluation_data.append(eval_entry)
                sample_metadata.append(sample_id)
        
        logger.info(f"Prepared {len(evaluation_data)} samples for batch evaluation")
        
        # Create temporary JSONL file for Azure AI evaluation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as temp_file:
            for entry in evaluation_data:
                temp_file.write(json.dumps(entry) + '\n')
            temp_file_path = temp_file.name
            
        try:
            # Setup Azure evaluators
            azure_evaluators, evaluator_config = self._setup_azure_evaluators()
            
            logger.info(f"Running Azure AI batch evaluation with {len(azure_evaluators)} evaluators")
            
            # Check for project upload configuration
            azure_ai_project = os.getenv("AZURE_AI_PROJECT")
            upload_enabled = os.getenv("AZURE_AI_FOUNDRY_UPLOAD", "false").lower() == "true"
            evaluation_name = os.getenv("AZURE_AI_EVALUATION_NAME", "VoiceLive-Batch-Evaluation")
            
            # Run Azure AI evaluate() function
            response = evaluate(
                data=temp_file_path,
                evaluation_name=f"{evaluation_name}-Batch",
                description=f"Batch Azure AI Foundry evaluation with {len(azure_evaluators)} metrics: {', '.join(azure_evaluators.keys())}",
                evaluators=azure_evaluators,
                evaluator_config=evaluator_config,
                azure_ai_project=azure_ai_project if upload_enabled else None
            )
            
            logger.info("Azure AI batch evaluation completed successfully")
            if response.get("studio_url"):
                logger.info(f"View results at: {response['studio_url']}")
                
            # Process results and write to output file
            self._write_batch_results(response, sample_metadata, output_file)
            
        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)
    
    def _write_batch_results(self, azure_response: Dict, sample_metadata: List, output_file: str):
        """Write batch evaluation results to JSONL file"""
        logger.info(f"Writing batch results to: {output_file}")
        
        rows = azure_response.get('rows', [])
        
        with open(output_file, 'w', encoding='utf-8') as f:
            for i, (row, sample_id) in enumerate(zip(rows, sample_metadata)):
                # Create evaluation result entry
                eval_result = {
                    "type": "batch_eval",
                    "id": sample_id,
                    "data": {
                        "azure_evaluate_response": {
                            "rows": [row],
                            "metrics": {k: v for k, v in row.items() if k.startswith('outputs.')},
                            "studio_url": azure_response.get("studio_url")
                        }
                    }
                }
                f.write(json.dumps(eval_result) + '\n')
                
        # Also write summary
        summary_file = output_file.replace('.jsonl', '_summary.json')
        with open(summary_file, 'w', encoding='utf-8') as f:
            summary = {
                "total_samples": len(rows),
                "evaluators": list(self.evaluators_config.keys()),
                "metrics": azure_response.get('metrics', {}),
                "studio_url": azure_response.get("studio_url")
            }
            json.dump(summary, f, indent=2)
            
        logger.info(f"Batch evaluation completed: {len(rows)} samples processed")
        logger.info(f"Summary saved to: {summary_file}")


def main():
    parser = argparse.ArgumentParser(description="Batch Azure AI Foundry Evaluation")
    parser.add_argument("--input", required=True, help="Input JSONL file with post-processed results")
    parser.add_argument("--evaluator", required=True, help="Azure AI evaluator configuration (e.g., azure-ai-combined-four)")
    parser.add_argument("--output", required=True, help="Output JSONL file for batch evaluation results")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input file not found: {args.input}")
        
    # Create output directory if needed
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    # Run batch evaluation
    evaluator = BatchFoundryEvaluator(args.evaluator)
    evaluator.evaluate_batch(args.input, args.output)


if __name__ == "__main__":
    main()