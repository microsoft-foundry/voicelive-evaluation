"""
Tracing and Logging Module for VoiceLive Evaluation Agent

Provides unified tracing compatible with:
- Local execution: Console output for development/debugging
- Cloud execution: Azure Monitor / Application Insights for production
- File logging: JSONL format compatible with Azure AI Foundry agent evaluation

Uses OpenTelemetry as the standard tracing protocol, with the Azure AI Agents
SDK's built-in instrumentation for automatic span creation.

Environment Variables:
    APPLICATIONINSIGHTS_CONNECTION_STRING: Azure Monitor connection string (optional)
        If set, traces go to Application Insights
        If not set, traces go to console (local development)
    
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT: Set to 'true' to include
        message content in traces (may contain PII - use carefully)
    
    EVAL_AGENT_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO
    
    EVAL_AGENT_LOG_DIR: Directory for log files (default: ./logs)

Log Files Created:
    - agent_traces_{date}.jsonl: OpenTelemetry-style traces for debugging
    - agent_conversations_{date}.jsonl: Foundry-compatible conversation format for evaluation

Usage:
    from tracing import setup_tracing, get_tracer, get_logger, ConversationLogger
    
    # Call once at startup
    setup_tracing()
    
    # Get tracer for custom spans
    tracer = get_tracer(__name__)
    
    # Get logger for standard logging
    logger = get_logger(__name__)
    
    # Log conversations for evaluation
    conv_logger = ConversationLogger()
    conv_logger.log_turn(user_message, assistant_response, tool_calls)
"""

import os
import sys
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from functools import wraps
from dataclasses import dataclass, field, asdict

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.trace import Span

# Azure Core tracing settings
from azure.core.settings import settings

# Module-level state
_tracing_initialized = False
_tracer_provider: Optional[TracerProvider] = None
_log_dir: Optional[Path] = None
_conversation_logger: Optional['ConversationLogger'] = None


# =============================================================================
# Foundry-Compatible Data Structures
# =============================================================================

@dataclass
class ToolCall:
    """Represents a tool/function call made by the agent."""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    status: str = "completed"  # completed, failed, pending
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Message:
    """Represents a message in the conversation (OpenAI-style format)."""
    role: str  # user, assistant, system, tool
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None  # For tool responses
    name: Optional[str] = None  # Tool name for tool responses
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> dict:
        d = {"role": self.role, "timestamp": self.timestamp}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() if isinstance(tc, ToolCall) else tc for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass 
class ConversationTurn:
    """
    A single conversation turn in Foundry-compatible format.
    
    This format is compatible with Azure AI Foundry's agent evaluation SDK.
    Use AIAgentConverter or parse directly into evaluator inputs.
    """
    id: str
    thread_id: str
    run_id: Optional[str] = None
    context: List[Message] = field(default_factory=list)  # Previous messages
    input: Optional[str] = None  # Current user input
    output: Optional[str] = None  # Agent's response
    expected_output: Optional[str] = None  # Ground truth (if available)
    tool_calls: List[ToolCall] = field(default_factory=list)
    system_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "context": [m.to_dict() if isinstance(m, Message) else m for m in self.context],
            "input": self.input,
            "output": self.output,
            "expected_output": self.expected_output,
            "tool_calls": [tc.to_dict() if isinstance(tc, ToolCall) else tc for tc in self.tool_calls],
            "system_message": self.system_message,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class TraceSpan:
    """OpenTelemetry-style trace span for debugging."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    start_time: str
    end_time: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"  # ok, error
    
    def to_dict(self) -> dict:
        return asdict(self)


# =============================================================================
# Conversation Logger (Foundry-Compatible)
# =============================================================================

class ConversationLogger:
    """
    Logs agent conversations in Azure AI Foundry evaluation-compatible format.
    
    Creates JSONL files that can be used with:
    - AIAgentConverter for Microsoft Foundry agent evaluation
    - Direct input to evaluators (IntentResolution, TaskAdherence, ToolCallAccuracy)
    
    File format: One JSON object per line, each representing a conversation turn.
    """
    
    def __init__(self, log_dir: Path = None, thread_id: str = None):
        self.log_dir = log_dir or _log_dir or Path("./logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.thread_id = thread_id or str(uuid.uuid4())
        self.run_id: Optional[str] = None
        self.context: List[Message] = []
        self.system_message: Optional[str] = None
        
        # File paths
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.conversation_file = self.log_dir / f"agent_conversations_{date_str}.jsonl"
        self.trace_file = self.log_dir / f"agent_traces_{date_str}.jsonl"
    
    def set_system_message(self, message: str):
        """Set the agent's system message/instructions."""
        self.system_message = message
    
    def start_run(self, run_id: str = None):
        """Start a new agent run within the thread."""
        self.run_id = run_id or str(uuid.uuid4())
        return self.run_id
    
    def log_turn(
        self,
        user_input: str,
        assistant_output: str,
        tool_calls: List[ToolCall] = None,
        expected_output: str = None,
        metadata: Dict[str, Any] = None,
    ):
        """
        Log a conversation turn in Foundry-compatible format.
        
        Args:
            user_input: The user's message
            assistant_output: The agent's response
            tool_calls: List of tool calls made during this turn
            expected_output: Ground truth response (for evaluation)
            metadata: Additional metadata (e.g., latency, model info)
        """
        turn = ConversationTurn(
            id=str(uuid.uuid4()),
            thread_id=self.thread_id,
            run_id=self.run_id,
            context=[m.to_dict() for m in self.context[-10:]],  # Last 10 messages for context
            input=user_input,
            output=assistant_output,
            expected_output=expected_output,
            tool_calls=tool_calls or [],
            system_message=self.system_message,
            metadata=metadata or {},
        )
        
        # Write to JSONL file
        with open(self.conversation_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
        
        # Update context for next turn
        self.context.append(Message(role="user", content=user_input))
        self.context.append(Message(role="assistant", content=assistant_output, tool_calls=tool_calls))
        
        return turn
    
    def log_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str = None,
        status: str = "completed",
        duration_ms: float = None,
    ) -> ToolCall:
        """
        Log a tool call with its result.
        
        Returns a ToolCall object that can be included in log_turn().
        """
        tool_call = ToolCall(
            id=str(uuid.uuid4()),
            name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            start_time=datetime.now(timezone.utc).isoformat(),
        )
        
        if duration_ms:
            tool_call.end_time = datetime.now(timezone.utc).isoformat()
        
        return tool_call
    
    def log_trace(self, span: TraceSpan):
        """Log a trace span to the trace file."""
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")
    
    def new_thread(self):
        """Start a new conversation thread."""
        self.thread_id = str(uuid.uuid4())
        self.run_id = None
        self.context = []
        return self.thread_id


# =============================================================================
# JSONL File Span Exporter
# =============================================================================

class JSONLSpanExporter(SpanExporter):
    """
    OpenTelemetry span exporter that writes to JSONL files.
    
    Creates trace files compatible with analysis tools and
    can be correlated with conversation logs.
    """
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.trace_file = self.log_dir / f"agent_traces_{date_str}.jsonl"
    
    def export(self, spans) -> SpanExportResult:
        try:
            with open(self.trace_file, "a", encoding="utf-8") as f:
                for span in spans:
                    span_dict = {
                        "trace_id": format(span.context.trace_id, '032x'),
                        "span_id": format(span.context.span_id, '016x'),
                        "parent_span_id": format(span.parent.span_id, '016x') if span.parent else None,
                        "name": span.name,
                        "start_time": datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc).isoformat(),
                        "end_time": datetime.fromtimestamp(span.end_time / 1e9, tz=timezone.utc).isoformat() if span.end_time else None,
                        "attributes": dict(span.attributes) if span.attributes else {},
                        "events": [
                            {
                                "name": event.name,
                                "timestamp": datetime.fromtimestamp(event.timestamp / 1e9, tz=timezone.utc).isoformat(),
                                "attributes": dict(event.attributes) if event.attributes else {},
                            }
                            for event in span.events
                        ],
                        "status": span.status.status_code.name if span.status else "UNSET",
                    }
                    f.write(json.dumps(span_dict, ensure_ascii=False) + "\n")
            return SpanExportResult.SUCCESS
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to export spans to JSONL: {e}")
            return SpanExportResult.FAILURE
    
    def shutdown(self):
        pass


# =============================================================================
# Setup Functions
# =============================================================================

def setup_tracing(
    service_name: str = "voicelive-evaluation-agent",
    service_version: str = "1.0.0",
    force_console: bool = False,
    enable_content_capture: bool = False,
    log_dir: str = None,
) -> bool:
    """
    Initialize tracing for the agent.
    
    Automatically selects the appropriate exporter:
    - Azure Monitor if APPLICATIONINSIGHTS_CONNECTION_STRING is set
    - Console + JSONL file if no connection string (local development)
    
    Args:
        service_name: Service name for traces (appears in Application Map)
        service_version: Service version for traces
        force_console: If True, use console tracing even if Azure Monitor configured
        enable_content_capture: If True, capture message content (may contain PII)
        log_dir: Directory for log files (default: ./logs or EVAL_AGENT_LOG_DIR)
    
    Returns:
        True if Azure Monitor tracing is enabled, False if console/file tracing
    """
    global _tracing_initialized, _tracer_provider, _log_dir, _conversation_logger
    
    if _tracing_initialized:
        return os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") is not None
    
    # Set up log directory
    _log_dir = Path(log_dir or os.environ.get("EVAL_AGENT_LOG_DIR", "./logs"))
    _log_dir.mkdir(parents=True, exist_ok=True)
    
    # Enable Azure SDK tracing integration
    settings.tracing_implementation = "opentelemetry"
    
    # Set content capture environment variable if requested
    if enable_content_capture:
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"
    
    # Create resource with service information
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })
    
    # Check for Azure Monitor connection string
    app_insights_conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    
    if app_insights_conn_str and not force_console:
        # Use Azure Monitor tracing (also write to file for local analysis)
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            
            configure_azure_monitor(
                connection_string=app_insights_conn_str,
                resource=resource,
            )
            
            # Also add JSONL exporter for local file logging
            tracer_provider = trace.get_tracer_provider()
            if hasattr(tracer_provider, 'add_span_processor'):
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(JSONLSpanExporter(_log_dir))
                )
            
            # Instrument Azure AI Agents
            try:
                from azure.ai.agents.telemetry import AIAgentsInstrumentor
                AIAgentsInstrumentor().instrument()
            except ImportError:
                pass  # Instrumentor not available in this SDK version
            
            _tracing_initialized = True
            _setup_logging(cloud_mode=True)
            _conversation_logger = ConversationLogger(_log_dir)
            
            logging.getLogger(__name__).info(
                f"Azure Monitor tracing enabled for {service_name} (logs: {_log_dir})"
            )
            return True
            
        except ImportError as e:
            logging.getLogger(__name__).warning(
                f"azure-monitor-opentelemetry not installed, falling back to console: {e}"
            )
    
    # Use console + file tracing (local development)
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    
    _tracer_provider = TracerProvider(resource=resource)
    
    # Add JSONL file exporter (always)
    _tracer_provider.add_span_processor(BatchSpanProcessor(JSONLSpanExporter(_log_dir)))
    
    # Add console exporter for visibility (if DEBUG level)
    log_level = os.environ.get("EVAL_AGENT_LOG_LEVEL", "INFO").upper()
    if log_level == "DEBUG":
        _tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    
    trace.set_tracer_provider(_tracer_provider)
    
    # Instrument Azure AI Agents for tracing
    try:
        from azure.ai.agents.telemetry import AIAgentsInstrumentor
        AIAgentsInstrumentor().instrument()
    except ImportError:
        pass  # Instrumentor not available in this SDK version
    
    _tracing_initialized = True
    _setup_logging(cloud_mode=False)
    _conversation_logger = ConversationLogger(_log_dir)
    
    logging.getLogger(__name__).info(
        f"File tracing enabled for {service_name} (logs: {_log_dir})"
    )
    return False


def _setup_logging(cloud_mode: bool = False):
    """Configure logging with appropriate handlers."""
    global _log_dir
    
    log_level_str = os.environ.get("EVAL_AGENT_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Configure root logger for the evaluation agent
    logger = logging.getLogger("evaluation_agent")
    logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Console handler for local visibility
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    if cloud_mode:
        # Structured JSON format for cloud logging
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        # Human-readable format for local development
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%H:%M:%S'
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler for persistent logging
    if _log_dir:
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = _log_dir / f"agent_{date_str}.log"
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # Capture all levels in file
        
        # Always use structured JSON in file for easier parsing
        file_formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)


def get_tracer(name: str = __name__) -> trace.Tracer:
    """
    Get an OpenTelemetry tracer for creating custom spans.
    
    Args:
        name: Name for the tracer (typically __name__)
    
    Returns:
        OpenTelemetry Tracer instance
    """
    if not _tracing_initialized:
        setup_tracing()
    return trace.get_tracer(name)


def get_logger(name: str = __name__) -> logging.Logger:
    """
    Get a logger configured for the evaluation agent.
    
    Args:
        name: Name for the logger (typically __name__)
    
    Returns:
        Logger instance
    """
    if not _tracing_initialized:
        setup_tracing()
    return logging.getLogger(name)


def get_conversation_logger() -> ConversationLogger:
    """
    Get the conversation logger for Foundry-compatible logging.
    
    Returns:
        ConversationLogger instance
    """
    global _conversation_logger
    if not _tracing_initialized:
        setup_tracing()
    if _conversation_logger is None:
        _conversation_logger = ConversationLogger(_log_dir)
    return _conversation_logger


def trace_tool_function(func):
    """
    Decorator to trace tool function execution with custom attributes.
    
    Creates a span for the function call and records:
    - Function name
    - Arguments
    - Return status
    - Duration
    
    Usage:
        @trace_tool_function
        def my_tool_function(arg1: str) -> str:
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        tracer = get_tracer(func.__module__)
        
        with tracer.start_as_current_span(f"tool.{func.__name__}") as span:
            # Record function arguments as attributes
            span.set_attribute("tool.name", func.__name__)
            
            # Sanitize and record args (limit size for safety)
            if args:
                args_str = str(args)[:500]
                span.set_attribute("tool.args", args_str)
            if kwargs:
                kwargs_str = str(kwargs)[:500]
                span.set_attribute("tool.kwargs", kwargs_str)
            
            try:
                result = func(*args, **kwargs)
                span.set_attribute("tool.status", "success")
                
                # Record result summary (not full content for privacy)
                if isinstance(result, str) and result.startswith('{'):
                    try:
                        parsed = json.loads(result)
                        span.set_attribute("tool.result.status", parsed.get("status", "unknown"))
                        span.set_attribute("tool.result.action", parsed.get("action", "unknown"))
                    except:
                        pass
                
                return result
                
            except Exception as e:
                span.set_attribute("tool.status", "error")
                span.set_attribute("tool.error", str(e)[:200])
                span.record_exception(e)
                raise
    
    return wrapper


def trace_agent_session(session_id: str = None):
    """
    Context manager for tracing an entire agent session.
    
    Usage:
        with trace_agent_session("user-session-123") as span:
            # Run agent conversation
            pass
    """
    tracer = get_tracer("evaluation_agent.session")
    span = tracer.start_as_current_span("agent.session")
    
    if session_id:
        span.set_attribute("session.id", session_id)
    
    return span


def log_tool_execution(tool_name: str, status: str, details: dict = None):
    """
    Log a tool execution event with structured data.
    
    Args:
        tool_name: Name of the tool being executed
        status: Execution status (started, completed, failed)
        details: Additional details to log
    """
    logger = get_logger("evaluation_agent.tools")
    
    log_data = {
        "tool": tool_name,
        "status": status,
    }
    if details:
        log_data.update(details)
    
    if status == "failed":
        logger.error(f"Tool execution: {log_data}")
    else:
        logger.info(f"Tool execution: {log_data}")
    
    # Also add to current span if tracing is active
    span = trace.get_current_span()
    if span and span.is_recording():
        span.add_event(
            f"tool.{status}",
            attributes={"tool.name": tool_name, **(details or {})}
        )


# Convenience function for checking if cloud tracing is active
def is_cloud_tracing_enabled() -> bool:
    """Check if Azure Monitor tracing is enabled."""
    return (
        _tracing_initialized and 
        os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING") is not None
    )


def get_log_directory() -> Path:
    """Get the current log directory path."""
    return _log_dir or Path("./logs")
