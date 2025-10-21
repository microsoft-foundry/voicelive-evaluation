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
        QAEvaluator,
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
        self.reasoning_deployment_name = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
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
        
        if not all([self.azure_endpoint, self.api_key, self.deployment_name, self.reasoning_model_config]):
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

        # Reasoning model configuration (if available)
        if self.reasoning_deployment_name:
            self.reasoning_config = {
                "azure_deployment": self.reasoning_deployment_name,
                "api_key": self.api_key,
                "azure_endpoint": self.azure_endpoint,
                "api_version": self.api_version
            }
        else:
            self.reasoning_config = self.model_config
        
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
            if self.reasoning_deployment_name:
                model_config = self.reasoning_config
            self.evaluator = IntentResolutionEvaluator(
                model_config=model_config,
                is_reasoning_model=True if self.reasoning_deployment_name else False,
                threshold=self.threshold
            )
        elif self.metric_type == "tool_call_accuracy":
            if self.reasoning_deployment_name:
                model_config = self.reasoning_config
            self.evaluator = ToolCallAccuracyEvaluator(
                model_config=model_config,
                is_reasoning_model=True if self.reasoning_deployment_name else False,
                threshold=self.threshold
            )
        elif self.metric_type == "task_adherence":
            if self.reasoning_deployment_name:
                model_config = self.reasoning_config
            self.evaluator = TaskAdherenceEvaluator(
                model_config=model_config,
                is_reasoning_model=True if self.reasoning_deployment_name else False,
                threshold=self.threshold
            )
        elif self.metric_type == "response_completeness":
            if self.reasoning_deployment_name:
                model_config = self.reasoning_config
            self.evaluator = ResponseCompletenessEvaluator(
                model_config=model_config,
                is_reasoning_model=True if self.reasoning_deployment_name else False,
                threshold=self.threshold
            )
        elif self.metric_type == "qaevaluator":
            self.evaluator = QAEvaluator(
                model_config=self.model_config,
                threshold=self.threshold
            )
        else:
            raise ValueError(
                f"Unsupported metric type: {self.metric_type}. "
                f"Supported types: groundedness, coherence, fluency, relevance, "
                f"intent_resolution, tool_call_accuracy, task_adherence, response_completeness, qaevaluator"
            )
        
        logger.info(f"Initialized {self.metric_type} evaluator with threshold {self.threshold}")
    
    def _process_label(self, label) -> str:
        """
        Process label to handle both string and list formats.
        If label is a list of acceptable answers, join them with ' OR ' for better evaluation context.
        
        Args:
            label: Either a string or list of acceptable answer strings
            
        Returns:
            String representation suitable for Azure AI evaluation
        """
        if isinstance(label, list):
            if len(label) == 0:
                return ""
            elif len(label) == 1:
                return str(label[0])
            else:
                # Join multiple acceptable answers with OR for context
                # This helps the AI evaluator understand there are multiple valid answers
                return " OR ".join([str(item) for item in label])
        return str(label)
    
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
            # Generate output path using same pattern as recorder: timestamp_evaluatorname_evaluationname_results.json
            # Get output directory from kwargs if provided by pipeline, otherwise use default
            pipeline_output_dir = kwargs.get('output_directory', 'output')
            
            # Extract base filename (timestamp_evaluatorname) from recorder path if available
            recorder_filename = kwargs.get('recorder_filename', '')
            if recorder_filename:
                # Remove .jsonl extension to get base name
                base_name = os.path.splitext(os.path.basename(recorder_filename))[0]
                output_file_path = os.path.join(pipeline_output_dir, f"{base_name}_{self.evaluation_name}_results.json")
            else:
                # Fallback to subdirectory approach - only create directory in this fallback case
                output_dir = os.path.join(pipeline_output_dir, self.metric_type)
                os.makedirs(output_dir, exist_ok=True)
                output_file_path = os.path.join(output_dir, f"{self.evaluation_name}_results.json")
            
            # Ensure parent directory exists (Azure AI SDK requires it)
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
            
            logger.info(f"Evaluation results will be saved to: {output_file_path}")
            
            response = evaluate(
                data=temp_file_path,
                evaluation_name=self.evaluation_name,
                evaluators={self.metric_type: self.evaluator},
                azure_ai_project=self.azure_ai_project if self.upload_to_project else None,
                output_path=output_file_path
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
        
        # Handle list of acceptable answers by joining them or picking first one
        ground_truth_text = self._process_label(label)
        
        # Extract response text from pred
        # If pred is a dict (from VoiceLive with passthrough), extract the response field
        # Otherwise, use pred as-is (string response)
        if isinstance(pred, dict):
            response_text = pred.get("response", str(pred))
        else:
            response_text = str(pred)
        
        # Get query from dataset fields (standardized via col_aliases to 'question')
        # Priority: Question (capital for raw datasets) → question (lowercase standard) → query (fallback)
        # Datasets should use col_aliases to map their question fields to 'question' for consistency
        query_text = kwargs.get("Question", kwargs.get("question", kwargs.get("query", "")))
        
        # Base data required for all evaluators
        eval_data = {
            "response": response_text,
        }
        
        # Add metric-specific data
        if self.metric_type == "groundedness":
            # Groundedness requires query and context
            eval_data.update({
                "query": query_text,
                "context": kwargs.get("context", ground_truth_text)
            })
        elif self.metric_type in ["coherence", "fluency"]:
            # Coherence and fluency only need the response
            eval_data["query"] = query_text
        elif self.metric_type == "relevance":
            # Relevance needs query and response
            eval_data["query"] = query_text
        elif self.metric_type == "intent_resolution":
            # Intent resolution needs query and response
            eval_data["query"] = query_text
        elif self.metric_type == "tool_call_accuracy":
            # Tool call accuracy needs query, response, and tools configuration
            eval_data.update({
                "query": query_text,
                "tools": kwargs.get("tools", [])
            })
        elif self.metric_type == "task_adherence":
            # Task adherence needs query, response, and system message
            eval_data.update({
                "query": query_text,
                "system_message": kwargs.get("system_message", kwargs.get("system", ""))
            })
        elif self.metric_type == "response_completeness":
            # Response completeness needs query, response, and ground truth
            eval_data.update({
                "query": query_text,
                "ground_truth": kwargs.get("ground_truth", ground_truth_text)
            })
        elif self.metric_type == "qaevaluator":
            # QA evaluator needs query, response, and ground truth
            eval_data.update({
                "query": query_text,
                "ground_truth": ground_truth_text
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
                azure_ai_project=self.azure_ai_project if self.upload_to_project else None,
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
    
    def _process_label(self, label) -> str:
        """
        Process label to handle both string and list formats.
        If label is a list of acceptable answers, join them with ' OR ' for better evaluation context.
        
        Args:
            label: Either a string or list of acceptable answer strings
            
        Returns:
            String representation suitable for Azure AI evaluation
        """
        if isinstance(label, list):
            if len(label) == 0:
                return ""
            elif len(label) == 1:
                return str(label[0])
            else:
                # Join multiple acceptable answers with OR for context
                return " OR ".join([str(item) for item in label])
        return str(label)
    
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
            # Handle list of acceptable answers
            ground_truth_text = self._process_label(label)
            
            # Extract response text from pred if it's a dict (from VoiceLive with passthrough)
            if isinstance(pred, dict):
                response_text = pred.get("response", str(pred))
            else:
                response_text = str(pred)
            
            # Get query from dataset fields (standardized via col_aliases to 'question')
            # Priority: Question (capital for raw datasets) → question (lowercase standard) → query (fallback)
            # Datasets should use col_aliases to map their question fields to 'question' for consistency
            query_text = kwargs.get("Question", kwargs.get("question", kwargs.get("query", "")))
            
            # Create temporary file with single data point
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as temp_file:
                data_entry = {
                    "query": query_text,
                    "response": response_text,
                    "context": kwargs.get("context", ground_truth_text),
                    "ground_truth": ground_truth_text
                }
                temp_file.write(json.dumps(data_entry) + '\n')
                temp_file_path = temp_file.name
            
            # Setup Azure AI evaluators for the evaluate() function
            azure_evaluators = {}
            evaluator_config = {}
            
            # Get configuration from environment or parameters
            azure_endpoint = azure_endpoint or os.getenv("AOAI_ENDPOINT")
            api_key = api_key or os.getenv("AOAI_API_KEY")  
            deployment_name = deployment_name or os.getenv("AOAI_DEPLOYMENT_NAME")
            reasoning_deployment_name = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
            api_version = api_version or os.getenv("AOAI_API_VERSION", "2024-02-15-preview")

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
            if reasoning_deployment_name:
                reasoning_config = {
                    "azure_deployment": reasoning_deployment_name,
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
                        is_reasoning_model=bool(reasoning_deployment_name),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'task_adherence':
                    azure_evaluators['task_adherence'] = TaskAdherenceEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment_name),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'response_completeness':
                    azure_evaluators['response_completeness'] = ResponseCompletenessEvaluator(
                        model_config=reasoning_config,
                        is_reasoning_model=bool(reasoning_deployment_name),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                    # evaluator_config['response_completeness'] = {
                    #     "column_mapping": {
                    #         "ground_truth": "${data.ground_truth}",
                    #         "response": "${data.response}"
                    #     }
                    # }
                elif eval_name == 'groundedness':
                    azure_evaluators['groundedness'] = GroundednessEvaluator(
                        model_config=model_config,
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                    # evaluator_config['groundedness'] = {
                    #     "column_mapping": {
                    #         "query": "${data.query}",
                    #         "context": "${data.context}",
                    #         "response": "${data.response}"
                    #     }
                    # }
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
                        is_reasoning_model=bool(reasoning_deployment_name),
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                elif eval_name == 'qaevaluator':
                    azure_evaluators['qaevaluator'] = QAEvaluator(
                        model_config=model_config,
                        threshold=self.evaluator_configs[eval_name].get('threshold', 3)
                    )
                else:
                    logger.warning(f"Unknown evaluator name: {eval_name}. Skipping.")
            
            # Run Azure AI evaluate() function
            eval_name = f"{self.evaluation_name}-Single"
            logger.info(f"Running Azure AI evaluate() with {len(azure_evaluators)} evaluators")
            
            azure_ai_project = self.azure_ai_project if self.upload_enabled else None
            
            # Generate output path using evaluation name in proper output directory
            # Get output directory from kwargs if provided by pipeline, otherwise use default
            pipeline_output_dir = kwargs.get('output_directory', 'output')
            
            # Extract base filename from recorder if available to maintain consistent naming
            recorder_filename = kwargs.get('recorder_filename')
            if recorder_filename:
                # Extract base name (e.g., "20250116_123045_azure-ai-foundry" from full path)
                base_name = os.path.splitext(os.path.basename(recorder_filename))[0]
                # Append evaluation name to maintain pattern: timestamp_evaluatorname_evaluationname_results.json
                output_file_path = os.path.join(pipeline_output_dir, f"{base_name}_{eval_name}_results.json")
            else:
                # Fallback to subdirectory approach if recorder filename not available - only create in fallback case
                output_dir = os.path.join(pipeline_output_dir, "multi_evaluation")
                os.makedirs(output_dir, exist_ok=True)
                output_file_path = os.path.join(output_dir, f"{eval_name or 'combined_evaluation'}_results.json")
            
            # Ensure parent directory exists (Azure AI SDK requires it)
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
            
            logger.info(f"Combined evaluation results will be saved to: {output_file_path}")
            
            response = evaluate(
                data=temp_file_path,
                evaluation_name=eval_name,
                description=f"Combined Azure AI Foundry evaluation with {len(azure_evaluators)} metrics: {', '.join(azure_evaluators.keys())}",
                evaluators=azure_evaluators,
                evaluator_config=evaluator_config,
                azure_ai_project=azure_ai_project,
                output_path=output_file_path
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


class AzureAIBatchEvaluator(Evaluator):
    """Batch-aware evaluator that collects samples and evaluates them together"""
    
    def __init__(self, evaluator_name: str = 'azure-ai-combined-four', batch_size: int = 0, evaluation_name: Optional[str] = None, **kwargs):
        super().__init__()
        self.evaluator_name = evaluator_name
        self.batch_samples = []
        self.sample_metadata = []
        self.initial_batch_size = batch_size
        self.batch_size = batch_size  # Will be dynamically adjusted
        self.upload_to_project = os.getenv("AZURE_AI_FOUNDRY_UPLOAD", "false").lower() == "true"
        self.dataset_size_estimated = False
        self.max_azure_evaluate_size = 1000  # Conservative limit for Azure AI evaluate()
        self.output_directory = None  # Will be set by pipeline or finalize_evaluation
        
        # Set evaluation name with proper precedence
        self.evaluation_name = (
            evaluation_name or 
            os.getenv("AZURE_AI_EVALUATION_NAME") or 
            f"VoiceLive-{self.evaluator_name}-Batch"
        )
        
        # Parse evaluator configuration
        self.evaluators_config = self._parse_evaluator_config()
        
        logger.info(f"Initializing AzureAIBatchEvaluator for {self.evaluator_name} with initial batch size {self.batch_size}")
        logger.info(f"Batch evaluation name: {self.evaluation_name}")
        
    def _parse_evaluator_config(self) -> Dict[str, Dict[str, Any]]:
        """Parse evaluator configuration"""
        if self.evaluator_name == "azure-ai-combined-agent-base":
            return {
                'intent_resolution': {'threshold': 3},
                'task_adherence': {'threshold': 3},
                'response_completeness': {'threshold': 3}
            }
        elif self.evaluator_name == "azure-ai-combined-agent-full+tool":
            return {
                'intent_resolution': {'threshold': 3},
                'task_adherence': {'threshold': 3},
                'response_completeness': {'threshold': 3},
                'groundedness': {'threshold': 3},
                'coherence': {'threshold': 3},
                'fluency': {'threshold': 3},
                'tool_call_accuracy': {'threshold': 3}
            }
        elif self.evaluator_name.startswith("azure-ai-"):
            # Single evaluator
            evaluator_type = self.evaluator_name.replace("azure-ai-", "").replace("-", "_")
            return {evaluator_type: {'threshold': 3}}
        else:
            raise ValueError(f"Unknown evaluator config: {self.evaluator_name}")
    
    def _process_label(self, label) -> str:
        """
        Process label to handle both string and list formats.
        If label is a list of acceptable answers, join them with ' OR ' for better evaluation context.
        
        Args:
            label: Either a string or list of acceptable answer strings
            
        Returns:
            String representation suitable for Azure AI evaluation
        """
        if isinstance(label, list):
            if len(label) == 0:
                return ""
            elif len(label) == 1:
                return str(label[0])
            else:
                # Join multiple acceptable answers with OR for context
                return " OR ".join([str(item) for item in label])
        return str(label)
    
    def _eval(self, pred: str, label: str, **kwargs) -> Dict[str, Any]:
        """
        Collect sample for batch evaluation. Returns placeholder result.
        """
        # Auto-adjust batch size on first call if not set or set to 0
        if not self.dataset_size_estimated and (self.batch_size == 0 or self.initial_batch_size == 0):
            # Try to estimate dataset size from environment or use conservative default
            limit = kwargs.get('limit', 0) or int(os.getenv('EVAL_LIMIT', '0'))
            if limit > 0:
                # Set batch size to match limit (up to max supported)
                self.batch_size = min(limit, self.max_azure_evaluate_size)
                logger.info(f"Auto-adjusted batch size to {self.batch_size} based on limit {limit}")
            else:
                # Use conservative default
                self.batch_size = min(100, self.max_azure_evaluate_size)
                logger.info(f"Set default batch size to {self.batch_size}")
            self.dataset_size_estimated = True
        
        # Capture output directory from kwargs if provided by pipeline
        if 'output_directory' in kwargs and not self.output_directory:
            self.output_directory = kwargs['output_directory']
        
        # Handle list of acceptable answers
        ground_truth_text = self._process_label(label)
        
        # Extract response text from pred if it's a dict (from VoiceLive with passthrough)
        if isinstance(pred, dict):
            response_text = pred.get("response", str(pred))
        else:
            response_text = str(pred)
        
        # Get query from dataset fields (standardized via col_aliases to 'question')
        # Priority: Question (capital for raw datasets) → question (lowercase standard) → query (fallback)
        # Datasets should use col_aliases to map their question fields to 'question' for consistency
        query_text = kwargs.get("Question", kwargs.get("question", kwargs.get("query", "")))
        
        # Collect sample data
        sample_data = {
            "query": query_text,
            "response": response_text,
            "context": kwargs.get("context", ground_truth_text),
            "ground_truth": ground_truth_text
        }
        
        # Store sample metadata for result mapping
        sample_id = len(self.batch_samples)
        sample_metadata = {
            "id": sample_id,
            "pred": pred,
            "label": label,  # Keep original label for reference
            "ground_truth_text": ground_truth_text,  # Store processed version too
            "kwargs": kwargs
        }
        
        self.batch_samples.append(sample_data)
        self.sample_metadata.append(sample_metadata)
        
        # Return placeholder result that will be updated after batch processing
        placeholder_result = {
            "batch_placeholder": True,
            "sample_id": sample_id,
            "evaluator": self.evaluator_name,
            "message": f"Sample {sample_id + 1} collected for batch evaluation (batch size: {self.batch_size})"
        }
        
        # Check if we should process this batch
        if len(self.batch_samples) >= self.batch_size:
            logger.info(f"Processing batch of {len(self.batch_samples)} samples")
            batch_results = self._process_batch()
            # Clear the batch
            self.batch_samples = []
            self.sample_metadata = []
            
            # Return result with proper error handling
            if batch_results and len(batch_results) > sample_id:
                return batch_results[sample_id]
            elif batch_results:
                # Sample ID out of range, return first error if available
                logger.warning(f"Sample ID {sample_id} out of range for batch results (size: {len(batch_results)})")
                return batch_results[0] if batch_results else placeholder_result
            else:
                # Batch failed, return placeholder
                return placeholder_result
            
        return placeholder_result
    
    def _process_batch(self) -> List[Dict[str, Any]]:
        """Process collected batch of samples"""
        if not self.batch_samples:
            return []
            
        try:
            azure_evaluators, evaluator_config = self._setup_azure_evaluators()
            
            # Create temporary JSONL file with batch data
            with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as temp_file:
                for sample in self.batch_samples:
                    temp_file.write(json.dumps(sample) + '\n')
                temp_file_path = temp_file.name
                
            try:
                # Check for project upload configuration
                azure_ai_project = os.getenv("AZURE_AI_PROJECT") if self.upload_to_project else None
                
                logger.info(f"Running Azure AI batch evaluation on {len(self.batch_samples)} samples")
                
                # Determine output directory - use pipeline-provided directory or fallback to 'output'
                output_dir = self.output_directory if self.output_directory else "output"
                
                # Ensure output directory exists (Azure AI SDK requires it)
                # Only create if it doesn't exist - respect pipeline's directory structure
                os.makedirs(output_dir, exist_ok=True)
                
                # Generate output path for batch evaluation results in same directory as recorder
                # Extract base filename from recorder if available to maintain consistent naming
                if hasattr(self, 'recorder_filename') and self.recorder_filename:
                    # Extract base name (e.g., "20250116_123045_azure-ai-foundry" from full path)
                    base_name = os.path.splitext(os.path.basename(self.recorder_filename))[0]
                    # Append evaluation name to maintain pattern: timestamp_evaluatorname_evaluationname_results.json
                    eval_name = f"{self.evaluation_name}-Batch-{len(self.batch_samples)}"
                    batch_output_file = os.path.join(output_dir, f"{base_name}_{eval_name}_results.json")
                else:
                    # Fallback to old naming pattern if recorder filename not available
                    batch_output_file = os.path.join(output_dir, f"{self.evaluation_name}-Batch-{len(self.batch_samples)}_results.json")
                
                logger.info(f"Batch evaluation results will be saved to: {batch_output_file}")
                
                # Run Azure AI evaluate() function
                response = evaluate(
                    data=temp_file_path,
                    evaluation_name=f"{self.evaluation_name}-Batch-{len(self.batch_samples)}",
                    evaluators=azure_evaluators,
                    evaluator_config=evaluator_config,
                    azure_ai_project=azure_ai_project if self.upload_to_project else None,
                    output_path=batch_output_file
                )
                
                if response.get("studio_url"):
                    logger.info(f"Azure AI Foundry batch evaluation uploaded: {response['studio_url']}")
                
                # Process results for each sample
                rows = response.get('rows', [])
                batch_results = []
                
                for i, (row, metadata) in enumerate(zip(rows, self.sample_metadata)):
                    result = {
                        "azure_evaluate_response": {
                            "rows": [row],
                            "metrics": {k: v for k, v in row.items() if k.startswith('outputs.')},
                            "studio_url": response.get("studio_url")
                        },
                        "batch_processed": True,
                        "batch_size": len(self.batch_samples),  
                        "sample_index": i
                    }
                    batch_results.append(result)
                    
                return batch_results
                
            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)
                
        except Exception as e:
            logger.error(f"Batch evaluation failed: {e}")
            # Return placeholder results for all samples
            return [{"error": str(e), "batch_failed": True} for _ in self.batch_samples]
    
    def finalize_evaluation(self, recorder=None, output_directory: str = "output", recorder_filename: str = None, **kwargs):
        """Process any remaining samples in the batch and write batch results to JSONL"""
        # Store output directory and recorder filename for use in _process_batch
        # Use pipeline-provided directory if available, otherwise fallback to default
        self.output_directory = output_directory
        self.recorder_filename = recorder_filename
        
        if self.batch_samples:
            # If batch size was 0 or never set, process all collected samples at once
            if self.batch_size == 0 or not self.dataset_size_estimated:
                self.batch_size = len(self.batch_samples)
                logger.info(f"Setting batch size to total sample count: {self.batch_size}")
            
            logger.info(f"Processing final batch of {len(self.batch_samples)} samples")
            batch_results = self._process_batch()
            
            # Write batch evaluation results to the main JSONL file
            if recorder and batch_results:
                # Create a comprehensive batch evaluation summary
                batch_summary = {
                    "evaluator": self.evaluator_name,
                    "batch_size": len(self.batch_samples),
                    "samples_evaluated": len(batch_results),
                    "sample_ids": [meta['id'] for meta in self.sample_metadata] if self.sample_metadata else [],
                    "individual_results": batch_results,
                    "batch_metrics": self._calculate_batch_metrics(batch_results)
                }
                
                recorder.add({
                    "type": "batch_eval", 
                    "id": f"batch_{self.evaluator_name}_{len(self.batch_samples)}_samples", 
                    "data": batch_summary
                })
                logger.info(f"Added batch evaluation results for {len(self.batch_samples)} samples to JSONL")
            
            self.batch_samples = []
            self.sample_metadata = []
    
    def _calculate_batch_metrics(self, batch_results):
        """Calculate aggregate metrics from batch results"""
        if not batch_results:
            return {}
        
        # Extract numeric scores from results if available
        scores = []
        for result in batch_results:
            if isinstance(result, dict):
                # Look for common score field names
                for score_field in ['score', 'rating', 'value', 'intent_resolution_score']:
                    if score_field in result and isinstance(result[score_field], (int, float)):
                        scores.append(result[score_field])
                        break
        
        if scores:
            return {
                "mean_score": sum(scores) / len(scores),
                "min_score": min(scores),
                "max_score": max(scores),
                "total_samples": len(batch_results)
            }
        else:
            return {"total_samples": len(batch_results)}
    
    def _setup_azure_evaluators(self):
        """Setup Azure AI evaluators"""
        return self._create_azure_evaluators()
    
    def _create_azure_evaluators(self):
        """Create Azure AI evaluator instances"""
        # Get Azure OpenAI configuration
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("AOAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AOAI_API_KEY")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AOAI_DEPLOYMENT_NAME")
        reasoning_deployment = os.getenv("AOAI_REASONING_DEPLOYMENT_NAME")
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
                # evaluator_config['response_completeness'] = {
                #     "column_mapping": {
                #         "ground_truth": "${data.ground_truth}",
                #         "response": "${data.response}"
                #     }
                # }
            elif eval_name == 'groundedness':
                azure_evaluators['groundedness'] = GroundednessEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
                # evaluator_config['groundedness'] = {
                #     "column_mapping": {
                #         "query": "${data.query}",
                #         "context": "${data.context}",
                #         "response": "${data.response}"
                #     }
                # }
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
            elif eval_name == 'qaevaluator':
                azure_evaluators['qaevaluator'] = QAEvaluator(
                    model_config=model_config,
                    threshold=threshold
                )
            else:
                logger.warning(f"Unknown evaluator name: {eval_name}. Skipping.")
                
        return azure_evaluators, evaluator_config
    
