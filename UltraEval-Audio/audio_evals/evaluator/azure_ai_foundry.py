"""
Azure AI Foundry evaluator integration for voice evaluation tasks.
Supports multiple evaluation metrics from Azure AI evaluation SDK.
Includes support for uploading results to Azure AI Foundry projects.
"""

from .base import Evaluator
from typing import Dict, Any, Optional, List
import os
import logging
from pathlib import Path
import json
import tempfile

logger = logging.getLogger(__name__)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env file in the UltraEval-Audio directory
    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from {env_path}")
    else:
        load_dotenv()  # Load from current directory or system env
except ImportError:
    logger.info("python-dotenv not available, using system environment variables only")

# Check if Azure AI evaluation SDK is available
azure_ai_available = True
batch_evaluation_available = True
try:
    from azure.ai.evaluation import (
        GroundednessEvaluator,
        CoherenceEvaluator,
        FluencyEvaluator,
        RelevanceEvaluator,
        IntentResolutionEvaluator,
        ToolCallAccuracyEvaluator,
        TaskAdherenceEvaluator,
        ResponseCompletenessEvaluator,
        AzureOpenAIModelConfiguration,
        evaluate
    )
except ImportError as e:
    logger.warning(f"Azure AI evaluation SDK not available: {e}")
    azure_ai_available = False
    batch_evaluation_available = False


class AzureAIFoundryEvaluator(Evaluator):
    """
    Azure AI Foundry evaluator that supports multiple evaluation metrics.
    
    Supported metrics:
    - groundedness: Measures how grounded the response is in the provided context
    - coherence: Measures logical flow and consistency of the response
    - fluency: Measures grammatical correctness and naturalness
    - relevance: Measures how relevant the response is to the query
    - intent_resolution: Measures how well the agent identifies the correct intent from a user query
    - tool_call_accuracy: Evaluates the agent's ability to select appropriate tools and process correct parameters
    - task_adherence: Measures how well the agent's response adheres to the task based on system message
    - response_completeness: Measures how complete and comprehensive the agent's response is
    """
    
    def __init__(
        self,
        metric_type: str = "relevance",
        threshold: float = 3.0,
        azure_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_version: Optional[str] = None,
        azure_ai_project: Optional[str] = None,
        upload_to_project: bool = False,
        evaluation_name: Optional[str] = None
    ):
        """
        Initialize the Azure AI Foundry evaluator.
        
        Args:
            metric_type: Type of evaluation metric ('groundedness', 'coherence', 'fluency', 'relevance')
            threshold: Threshold for evaluation scoring
            azure_endpoint: Azure OpenAI endpoint (optional, can be set via env var AOAI_ENDPOINT)
            api_key: API key (optional, can be set via env var AOAI_API_KEY)  
            deployment_name: Deployment name (optional, can be set via env var AOAI_DEPLOYMENT_NAME)
            api_version: API version (optional, can be set via env var AOAI_API_VERSION)
            azure_ai_project: Azure AI Foundry project URL (optional, can be set via env var AZURE_AI_PROJECT)
            upload_to_project: Whether to upload results to Azure AI Foundry project (default: False)
            evaluation_name: Name for the evaluation run when uploading to project (optional)
        """
        if not azure_ai_available:
            raise ImportError("Azure AI evaluation SDK is required. Install with: pip install azure-ai-evaluation")
        
        self.metric_type = metric_type.lower()
        self.threshold = int(threshold)
        
        # Get configuration from environment or parameters
        self.azure_endpoint = azure_endpoint or os.getenv("AOAI_ENDPOINT")
        self.api_key = api_key or os.getenv("AOAI_API_KEY")  
        self.deployment_name = deployment_name or os.getenv("AOAI_DEPLOYMENT_NAME")
        self.api_version = api_version or os.getenv("AOAI_API_VERSION", "2024-02-15-preview")
        
        # Azure AI Foundry project configuration
        self.azure_ai_project = azure_ai_project or os.getenv("AZURE_AI_PROJECT") or os.getenv("PROJECT_ENDPOINT")
        
        # Auto-enable upload if project is configured and upload flag is set
        upload_enabled = os.getenv("AZURE_AI_FOUNDRY_UPLOAD", "false").lower() in ["true", "1", "yes", "on"]
        self.upload_to_project = upload_to_project or upload_enabled
        
        # Use custom evaluation name or generate one
        self.evaluation_name = (
            evaluation_name or 
            os.getenv("AZURE_AI_EVALUATION_NAME") or 
            f"VoiceLive-{self.metric_type}-evaluation"
        )
        
        # Track collected results for batch upload
        self.collected_results = []
        
        # Log project upload configuration
        if self.upload_to_project and self.azure_ai_project:
            logger.info(f"Azure AI Foundry project upload enabled: {self.azure_ai_project}")
            logger.info(f"Evaluation name: {self.evaluation_name}")
        elif self.upload_to_project and not self.azure_ai_project:
            logger.warning("Upload enabled but no Azure AI project configured. Set AZURE_AI_PROJECT environment variable.")
            self.upload_to_project = False
        
        if not all([self.azure_endpoint, self.api_key, self.deployment_name]):
            raise ValueError(
                "Azure OpenAI configuration required. Set AOAI_ENDPOINT, AOAI_API_KEY, "
                "and AOAI_DEPLOYMENT_NAME environment variables or pass as parameters."
            )
        
        # Create model configuration
        self.model_config = AzureOpenAIModelConfiguration(
            azure_endpoint=str(self.azure_endpoint),
            api_key=str(self.api_key),
            azure_deployment=str(self.deployment_name),
            api_version=str(self.api_version)
        )
        
        # Initialize the appropriate evaluator
        self.evaluator = None
        self._initialize_evaluator()
    
    def _initialize_evaluator(self):
        """Initialize the appropriate Azure AI evaluator based on metric type."""
        if self.metric_type == "groundedness":
            self.evaluator = GroundednessEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "coherence":
            self.evaluator = CoherenceEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "fluency":
            self.evaluator = FluencyEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "relevance":
            self.evaluator = RelevanceEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "intent_resolution":
            self.evaluator = IntentResolutionEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "tool_call_accuracy":
            self.evaluator = ToolCallAccuracyEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "task_adherence":
            self.evaluator = TaskAdherenceEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        elif self.metric_type == "response_completeness":
            self.evaluator = ResponseCompletenessEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        else:
            raise ValueError(
                f"Unsupported metric type: {self.metric_type}. "
                f"Supported types: groundedness, coherence, fluency, relevance, "
                f"intent_resolution, tool_call_accuracy, task_adherence, response_completeness"
            )
        
        logger.info(f"Initialized {self.metric_type} evaluator with threshold {self.threshold}")
    
    def _eval(self, pred: str, label: str, **kwargs) -> Dict[str, Any]:
        """
        Evaluate prediction against reference using Azure AI evaluation.
        
        Args:
            pred: Predicted/generated response
            label: Reference/ground truth response
            **kwargs: Additional arguments (query, context, etc.)
            
        Returns:
            Dictionary containing evaluation results with complete Azure AI response
        """
        try:
            # Prepare evaluation data for Azure AI evaluate()
            eval_data = self._prepare_eval_data(pred, label, **kwargs)
            
            # Create temporary JSONL file with single data point
            temp_file_path = None
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
                temp_file_path = f.name
                f.write(json.dumps(eval_data) + '\n')
            
            logger.info(f"Running Azure AI evaluate() with {self.metric_type} evaluator")
            
            # Use Azure AI's evaluate() function for consistent results
            response = evaluate(
                data=temp_file_path,
                evaluation_name=self.evaluation_name,
                evaluators={self.metric_type: self.evaluator},
                azure_ai_project=self.azure_ai_project if self.upload_to_project else None
            )
            
            logger.info(f"Azure AI evaluate() completed successfully")
            if response.get("studio_url"):
                logger.info(f"View results at: {response['studio_url']}")
            
            # Return the complete Azure AI evaluate() response as the result
            # This preserves all the detailed evaluation data, metrics, and reasoning
            logger.info(f"Returning complete Azure AI evaluate() response for {self.metric_type} evaluator")
            
            # Clean up temporary file
            os.unlink(temp_file_path)
            
            # Convert EvaluationResult to dict to match expected return type
            return {
                "azure_evaluate_response": response,
                "rows": response.get("rows", []),
                "metrics": response.get("metrics", {}),
                "studio_url": response.get("studio_url", "")
            }
            
        except Exception as e:
            logger.error(f"Azure AI evaluate() failed: {e}")
            # Clean up temporary file on error
            try:
                if temp_file_path:
                    os.unlink(temp_file_path)
            except:
                pass
            return {
                "error": str(e),
                "azure_evaluate_response": None
            }
    
    def _prepare_eval_data(self, pred: str, label: str, **kwargs) -> Dict[str, Any]:
        """Prepare evaluation data based on the metric type."""
        
        # Base data required for all evaluators
        eval_data = {
            "response": str(pred),
        }
        
        # Add metric-specific data
        if self.metric_type == "groundedness":
            # Groundedness requires query and context
            eval_data.update({
                "query": kwargs.get("query", kwargs.get("question", "")),
                "context": kwargs.get("context", str(label))
            })
        elif self.metric_type in ["coherence", "fluency"]:
            # Coherence and fluency only need the response
            eval_data["query"] = kwargs.get("query", kwargs.get("question", ""))
        elif self.metric_type == "relevance":
            # Relevance needs query and response
            eval_data["query"] = kwargs.get("query", kwargs.get("question", ""))
        elif self.metric_type == "intent_resolution":
            # Intent resolution needs query and response
            eval_data["query"] = kwargs.get("query", kwargs.get("question", ""))
        elif self.metric_type == "tool_call_accuracy":
            # Tool call accuracy needs query, response, and tools configuration
            eval_data.update({
                "query": kwargs.get("query", kwargs.get("question", "")),
                "tools": kwargs.get("tools", [])
            })
        elif self.metric_type == "task_adherence":
            # Task adherence needs query, response, and system message
            eval_data.update({
                "query": kwargs.get("query", kwargs.get("question", "")),
                "system_message": kwargs.get("system_message", kwargs.get("system", ""))
            })
        elif self.metric_type == "response_completeness":
            # Response completeness needs query, response, and ground truth
            eval_data.update({
                "query": kwargs.get("query", kwargs.get("question", "")),
                "ground_truth": kwargs.get("ground_truth", str(label))
            })
        
        return eval_data
    
    def _process_results(self, result: Dict[str, Any], pred: str, label: str) -> Dict[str, Any]:
        """Process and standardize the evaluation results."""
        
        # Extract score and rating from result
        score = result.get(f"{self.metric_type}_score", result.get("score", 0.0))
        rating = result.get(f"{self.metric_type}", result.get("rating", 1))
        
        # Convert to standard format
        processed_result = {
            "score": float(score) if score is not None else 0.0,
            "rating": int(rating) if rating is not None else 1,
            "metric_type": self.metric_type,
            "threshold": self.threshold,
            "pred": pred,
            "ref": label
        }
        
        # Add pass/fail based on threshold
        processed_result["pass"] = processed_result["rating"] >= self.threshold
        
        # Add any additional metadata from the result
        for key, value in result.items():
            if key not in processed_result and not key.startswith("_"):
                processed_result[f"azure_{key}"] = value
        
        return processed_result

    def __del__(self):
        """Destructor to ensure results are uploaded when the evaluator is destroyed."""
        try:
            if hasattr(self, 'upload_to_project') and self.upload_to_project and hasattr(self, 'collected_results') and self.collected_results:
                logger.info(f"Auto-uploading {len(self.collected_results)} results to Azure AI Foundry project on evaluator cleanup")
                self.finalize_evaluation()
        except:
            pass  # Ignore errors in destructor

    def collect_result(self, pred: str, label: str, query: str = "", context: str = "", **kwargs):
        """Collect evaluation result for batch upload to Azure AI Foundry project."""
        if self.upload_to_project:
            # Store the data for batch evaluation
            result_entry = {
                "response": pred,
                "ground_truth": label,
                "query": query,
                "context": context
            }
            # Add any additional fields
            for key, value in kwargs.items():
                if key not in result_entry:
                    result_entry[key] = value
            
            self.collected_results.append(result_entry)

    def upload_batch_results(self, output_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Upload collected results to Azure AI Foundry project using batch evaluation.
        
        Args:
            output_path: Optional path to save evaluation results locally
            
        Returns:
            Evaluation result dictionary with project URL if successful, None if failed
        """
        if not self.upload_to_project or not self.azure_ai_project or not self.collected_results:
            logger.info("No results to upload or project upload not enabled")
            return None
            
        if not batch_evaluation_available:
            logger.warning("Batch evaluation not available. Install azure-ai-evaluation>=1.0.0")
            return None
            
        try:
            # Create temporary JSONL file with collected results
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
                temp_file = f.name
                for result in self.collected_results:
                    f.write(json.dumps(result) + '\n')
            
            logger.info(f"Created temporary data file: {temp_file}")
            logger.info(f"Uploading {len(self.collected_results)} results to Azure AI Foundry project")
            
            # Create evaluator for batch evaluation
            evaluator_instance = self.evaluator
            
            # Run batch evaluation with project upload
            result = evaluate(
                data=temp_file,
                evaluation_name=self.evaluation_name,
                evaluators={self.metric_type: evaluator_instance},
                azure_ai_project=self.azure_ai_project,
                output_path=output_path
            )
            
            # Clean up temporary file
            try:
                os.unlink(temp_file)
            except:
                pass
            
            logger.info(f"Successfully uploaded evaluation results to Azure AI Foundry project")
            if result.get("studio_url"):
                logger.info(f"View results at: {result['studio_url']}")
                
            return result
            
        except Exception as e:
            logger.error(f"Failed to upload results to Azure AI Foundry project: {e}")
            return None

    def finalize_evaluation(self, output_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Finalize evaluation by uploading collected results to Azure AI Foundry project.
        Call this after all individual evaluations are complete.
        
        Args:
            output_path: Optional path to save evaluation results locally
            
        Returns:
            Evaluation result dictionary with project URL if successful, None if failed
        """
        if self.upload_to_project and self.collected_results:
            return self.upload_batch_results(output_path)
        return None


class AzureAIMultiEvaluator(Evaluator):
    """Multi-evaluator that runs multiple Azure AI Foundry evaluators and combines their results.
    
    This evaluator uses existing individual evaluator classes and combines their outputs
    into a comprehensive evaluation result with optional project upload functionality.
    """
    
    def __init__(self, evaluators: Dict[str, Dict[str, Any]] = None, **kwargs):
        """Initialize the multi-evaluator.
        
        Args:
            evaluators: Dictionary mapping evaluator names to their class and configuration
                       e.g., {"intent_resolution": {"class": "...", "threshold": 3}}
        """
        super().__init__()
        
        self.evaluator_configs = evaluators or {}
        self.collected_results = []
        
        # Check for environment variable-based project upload configuration
        self.upload_enabled = os.getenv("AZURE_AI_FOUNDRY_UPLOAD", "false").lower() == "true"
        self.azure_ai_project = os.getenv("AZURE_AI_PROJECT")
        self.evaluation_name = os.getenv("AZURE_AI_EVALUATION_NAME", "VoiceLive-Combined-Evaluation")
        
        if self.upload_enabled:
            if self.azure_ai_project:
                logger.info(f"Azure AI Foundry project upload enabled: {self.azure_ai_project}")
                logger.info(f"Evaluation name: {self.evaluation_name}")
            else:
                logger.warning("AZURE_AI_FOUNDRY_UPLOAD=true but AZURE_AI_PROJECT not set. Upload disabled.")
                self.upload_enabled = False
    
    
    def _eval(self, pred: str, label: str, **kwargs) -> Dict[str, Any]:
        """Evaluate using Azure AI's evaluate() function with all configured evaluators.
        
        Args:
            pred: Predicted/generated response text
            label: Ground truth or reference text
            **kwargs: Additional context including query, context, etc.
            
        Returns:
            Dictionary with combined evaluation results from all configured evaluators
        """
        if not batch_evaluation_available:
            logger.error("Azure AI batch evaluation not available")
            return {"error": "Azure AI batch evaluation not available", "combined_average_score": 0, "combined_all_pass": False}
        
        logger.info(f"Running Azure AI evaluate() with {len(self.evaluator_configs)} evaluators: {list(self.evaluator_configs.keys())}")
        
        try:
            # Create temporary file with single data point
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as temp_file:
                data_entry = {
                    "query": kwargs.get("query", kwargs.get("question", "")),
                    "response": pred,
                    "context": kwargs.get("context", label),
                    "ground_truth": label
                }
                temp_file.write(json.dumps(data_entry) + '\n')
                temp_file_path = temp_file.name
            
            # Setup Azure AI evaluators for the evaluate() function
            azure_evaluators = {}
            evaluator_config = {}
            
            # Get Azure OpenAI configuration from environment
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
            
            # Create Azure AI evaluator instances based on configuration
            for eval_name in self.evaluator_configs.keys():
                if eval_name == 'intent_resolution':
                    azure_evaluators['intent_resolution'] = IntentResolutionEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'task_adherence':
                    azure_evaluators['task_adherence'] = TaskAdherenceEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'response_completeness':
                    azure_evaluators['response_completeness'] = ResponseCompletenessEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
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
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
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
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'fluency':
                    azure_evaluators['fluency'] = FluencyEvaluator(
                        model_config=model_config,
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'relevance':
                    azure_evaluators['relevance'] = RelevanceEvaluator(
                        model_config=model_config,
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'tool_call_accuracy':
                    azure_evaluators['tool_call_accuracy'] = ToolCallAccuracyEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
            
            # Run Azure AI evaluate() function
            eval_name = f"{self.evaluation_name}-Single"
            logger.info(f"Running Azure AI evaluate() with {len(azure_evaluators)} evaluators")
            
            azure_ai_project = self.azure_ai_project if self.upload_enabled else None
            
            response = evaluate(
                data=temp_file_path,
                evaluation_name=eval_name,
                description=f"Combined Azure AI Foundry evaluation with {len(azure_evaluators)} metrics: {', '.join(azure_evaluators.keys())}",
                evaluators=azure_evaluators,
                evaluator_config=evaluator_config,
                azure_ai_project=azure_ai_project
            )
            
            logger.info(f"Azure AI evaluate() completed successfully")
            if response.get("studio_url"):
                logger.info(f"View results at: {response['studio_url']}")
            
            # Return the complete Azure AI evaluate() response as the result
            # This preserves all the detailed evaluation data, metrics, and reasoning
            logger.info(f"Returning complete Azure AI evaluate() response with {len(azure_evaluators)} evaluators")
            
            # Clean up temporary file
            os.unlink(temp_file_path)
            
            # Convert EvaluationResult to dict to match expected return type
            return {
                "azure_evaluate_response": response,
                "rows": response.get("rows", []),
                "metrics": response.get("metrics", {}),
                "studio_url": response.get("studio_url", "")
            }
            
        except Exception as e:
            logger.error(f"Azure AI evaluate() failed: {e}")
            # Clean up temporary file on error
            try:
                os.unlink(temp_file_path)
            except:
                pass
            return {
                "error": str(e),
                "azure_evaluate_response": None
            }
    
