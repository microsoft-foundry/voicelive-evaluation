#speech example to test the Azure Voice Live API with file input
import os
import uuid
import json
import time
import base64
import logging
import threading
import numpy as np
import sounddevice as sd
import queue
import signal
import sys
import wave
import argparse
import filelock  # For cross-process file locking
from datetime import datetime, timezone
from collections import deque
from dotenv import load_dotenv
from azure.core.credentials import TokenCredential
from azure.identity import DefaultAzureCredential
from typing import Dict, Union, Literal, Set, List, Optional, Any
from typing_extensions import Iterator, TypedDict, Required
import websocket
from websocket import WebSocketApp

# System instruction constant - single source of truth
SYSTEM_INSTRUCTION = "You are a helpful agent assisting users with their questions."

# Global variables for thread coordination
stop_event = threading.Event()
connection_queue = queue.Queue()
response_complete_event = threading.Event()
audio_transcript_complete_event = threading.Event()  # Track when response.audio_transcript.done is received
all_files_processed_event = threading.Event()
current_output_file = None
response_output_dir = None
evaluation_output_file = None
evaluation_enabled = False
current_user_input = None  # Track the current user input for multi-utterance handling
current_turn_number = 0  # Global turn counter for output file naming
expected_turns = 0  # Track how many input files we expect to process
actual_turns = 0  # Track how many actual turns were created due to VAD
turns_with_audio_response = 0  # Track how many turns received audio responses
turns_with_text_only_response = 0  # Track how many turns had text but no audio
session_timestamp_global = None  # Base timestamp for all outputs (no per-file uniqueness when aggregating)
session_suffix_global = None  # Holds current session suffix like session-1, session-2
pending_tool_followup_event = threading.Event()  # Track when a tool call follow-up response is expected
followup_created_event = threading.Event()  # Track when a follow-up response has actually started
tool_output_sent = False  # Track when we've sent a function_call_output and are awaiting the incorporating response

def reset_session_state(system_prompt: Optional[str] = None):
    """Reset global state between per-file sessions when running in per-file session mode.
    
    Args:
        system_prompt: Optional custom system prompt from dataset JSONL. If provided, replaces
                      the default SYSTEM_INSTRUCTION for this session.
    """
    global stop_event, connection_queue, response_complete_event, audio_transcript_complete_event, all_files_processed_event
    global current_output_file, response_output_dir, evaluation_output_file, evaluation_enabled
    global current_user_input, current_turn_number, expected_turns, actual_turns, session_timestamp_global
    global turns_with_audio_response, turns_with_text_only_response
    global pending_tool_followup_event, followup_created_event, session_suffix_global, tool_output_sent
    global current_metrics  # CRITICAL: Must declare global to reset the actual global variable

    # Recreate events to ensure no lingering set() state
    stop_event = threading.Event()
    connection_queue = queue.Queue()
    response_complete_event = threading.Event()
    audio_transcript_complete_event = threading.Event()
    all_files_processed_event = threading.Event()
    pending_tool_followup_event = threading.Event()
    followup_created_event = threading.Event()
    tool_output_sent = False

    # Reset counters / globals
    current_output_file = None
    response_output_dir = None
    evaluation_output_file = None
    # evaluation_enabled will be re-set inside main() depending on provided dir
    evaluation_enabled = False
    current_user_input = None
    current_turn_number = 0
    expected_turns = 0
    actual_turns = 0
    turns_with_audio_response = 0
    turns_with_text_only_response = 0
    session_timestamp_global = None
    session_suffix_global = None

    # Fresh metrics tracker - use custom system_prompt if provided, otherwise default
    effective_instruction = system_prompt if system_prompt else SYSTEM_INSTRUCTION
    current_metrics = ConversationMetrics(system_instruction=effective_instruction)


def write_evaluation_data_safe(file_path: str, evaluation_data: dict) -> bool:
    """
    Write evaluation data to file with cross-process locking.
    This ensures safe concurrent writes when running in batch mode with multiple subprocesses.
    
    Args:
        file_path: Path to the evaluation JSONL file
        evaluation_data: Dictionary containing the evaluation data
    
    Returns:
        True if write was successful, False otherwise
    """
    lock_path = file_path + '.lock'
    try:
        lock = filelock.FileLock(lock_path, timeout=30)
        with lock:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(evaluation_data) + '\n')
        return True
    except filelock.Timeout:
        logger.error(f"Timeout acquiring lock for {file_path}")
        print(f"ERROR: Timeout acquiring lock for evaluation file")
        return False
    except Exception as e:
        logger.error(f"Error writing evaluation data: {e}")
        print(f"ERROR: Failed to write evaluation data: {e}")
        return False


# Class for tracking conversation metrics for evaluation
class ConversationMetrics:
    def __init__(self, system_instruction: Optional[str] = None):
        self.audio_send_end_time = None
        self.first_text_response_time = None
        self.first_audio_response_time = None
        self.transcription_complete_time = None
        self.system_message = system_instruction if system_instruction else SYSTEM_INSTRUCTION
        self.user_content = []
        self.assistant_content = []
        self.tool_content = []  # Track tool call/results for the current logical turn
        self.tool_calls_array = []  # Track tool calls in Azure AI Evaluation SDK format
        self._tool_buffers = {}  # Accumulate delta content for tool messages
        self.current_turn_complete = True  # Flag to track if a turn is complete
        self.conversation_topic = None     # Track the current conversation topic across files
        self.conversation_history = []     # Full conversation history for context
        self.logical_turn_number = 0       # Track logical turns (not split by VAD)
        self.ground_truth = None           # Track expected answer for ResponseCompleteness evaluation
        self.tool_definitions = []         # Track tool definitions from input dataset (defaults to empty)
        self.audio_response_received = False  # Track if audio response was received (vs text-only)
        # Snapshot of metadata captured when audio file is loaded (prevents overwrites)
        self.turn_ground_truth = None
        self.turn_tool_definitions = []

    def calculate_metrics(self):
        metrics = {}
        if self.audio_send_end_time and self.first_audio_response_time:
            metrics["turn-audio-resonse-latency-in-seconds"] = (
                self.first_audio_response_time - self.audio_send_end_time
            ).total_seconds()
        if self.audio_send_end_time and self.first_text_response_time:
            metrics["turn-text-resonse-latency-in-seconds"] = (
                self.first_text_response_time - self.audio_send_end_time
            ).total_seconds()
        if self.audio_send_end_time and self.transcription_complete_time:
            metrics["turn-audio-transcription-latency-in-seconds"] = (
                self.transcription_complete_time - self.audio_send_end_time
            ).total_seconds()
        return metrics

    def get_current_turn_user_inputs(self):
        """Get all user inputs for the current logical turn"""
        current_turn_inputs = []
        for content in self.user_content:
            if content.get("content", [{}])[0].get("text") != "[Awaiting transcription]":
                current_turn_inputs.append(content)
        return current_turn_inputs

    def get_current_turn_assistant_responses(self):
        """Get all assistant responses for the current logical turn"""
        return self.assistant_content.copy()

    def get_current_turn_tool_messages(self):
        return self.tool_content.copy()

    def finalize_turn_and_get_evaluation_data(self):
        """Create evaluation data for the completed turn and add to conversation history"""
        metrics = self.calculate_metrics()
        # Increment logical turn number
        self.logical_turn_number += 1

        # Get current turn data
        current_user_inputs = self.get_current_turn_user_inputs()
        current_assistant_responses = self.get_current_turn_assistant_responses()
        current_tool_messages = self.get_current_turn_tool_messages()

        if not current_user_inputs:
            return None  # No valid turn to process

        # Create the evaluation data structure for this specific turn
        # Merge former turn_info fields directly into metrics per new requirement
        metrics["logical_turn_number"] = self.logical_turn_number
        metrics["conversation_topic"] = self.conversation_topic
        metrics["inputs_in_turn"] = len(current_user_inputs)
        metrics["responses_in_turn"] = len(current_assistant_responses)
        metrics["audio_response_received"] = self.audio_response_received

        evaluation_data = {
            "query": [
                {"role": "system", "content": self.system_message}
            ],
            "response": current_assistant_responses,
            "metrics": metrics
        }

        # Add tool_calls array for ToolCallAccuracyEvaluator
        # IMPORTANT: Make a copy of the list to prevent clear() from emptying the evaluation_data
        if self.tool_calls_array:
            evaluation_data["tool_calls"] = list(self.tool_calls_array)  # Copy, not reference
        else:
            evaluation_data["tool_calls"] = []

        # Use tool definitions from turn start snapshot
        evaluation_data["tool_definitions"] = self.turn_tool_definitions if isinstance(self.turn_tool_definitions, list) else []
        
        # Add ground_truth from turn start snapshot
        if self.turn_ground_truth:
            evaluation_data["ground_truth"] = self.turn_ground_truth

        # Add conversation history for context (previous turns) including user, assistant, and tool roles
        for historical_turn in self.conversation_history:
            combined_msgs = []
            combined_msgs.extend(historical_turn.get("user_inputs", []))
            combined_msgs.extend(historical_turn.get("assistant_responses", []))
            combined_msgs.extend(historical_turn.get("tool_messages", []))
            try:
                combined_msgs.sort(key=lambda m: m.get("createdAt", ""))
            except Exception:
                pass
            evaluation_data["query"].extend(combined_msgs)

        # Add only current turn USER inputs to query to avoid duplicating assistant response in the same turn
        current_user_msgs = list(current_user_inputs)
        try:
            current_user_msgs.sort(key=lambda m: m.get("createdAt", ""))
        except Exception:
            pass
        evaluation_data["query"].extend(current_user_msgs)

        # Append any tool call / tool result messages from this turn to the query context
        # so evaluators see the sequence of tool usage inline (tool calls appear as assistant role with type tool_call; tool outputs as tool role)
        if current_tool_messages:
            try:
                # Ensure chronological ordering if timestamps exist
                sorted_tools = sorted(current_tool_messages, key=lambda m: m.get("createdAt", ""))
            except Exception:
                sorted_tools = current_tool_messages
            # Normalize to required shape: if a message already has required fields, pass through.
            normalized = []
            for tm in sorted_tools:
                entry = dict(tm)  # shallow copy
                # If this represents a tool invocation but missing content wrapper for arguments, add one.
                # We assume tool invocation messages (assistant deciding to call) are captured elsewhere; here we mostly have tool results.
                # If future: capture assistant tool call intents, inject here with type tool_call.
                normalized.append(entry)
            evaluation_data["query"].extend(normalized)

        # Set default metrics if they're not available
        if not metrics:
            evaluation_data["metrics"] = {
                "turn-audio-resonse-latency-in-seconds": 0,
                "turn-audio-transcription-latency-in-seconds": 0
            }

        # Add this turn to conversation history for future turns (include tools)
        self.conversation_history.append({
            "turn_number": self.logical_turn_number,
            "user_inputs": current_user_inputs,
            "assistant_responses": current_assistant_responses,
            "tool_messages": current_tool_messages,
            "topic": self.conversation_topic
        })

        # Clear current turn data but keep conversation context
        self.user_content.clear()
        self.assistant_content.clear()
        self.tool_content.clear()
        self.tool_calls_array.clear()  # Reset tool calls for new turn
        self._tool_buffers.clear()
        # Don't set current_turn_complete to True here - let the next speech event reset it

        # Reset timing and response tracking metrics for next turn
        self.audio_send_end_time = None
        self.audio_response_received = False
        self.first_text_response_time = None
        self.first_audio_response_time = None
        self.transcription_complete_time = None
        
        # DO NOT clear snapshot variables here - they persist across multiple turns from the same file
        # Snapshot is only updated when a new file is loaded in send_audio_from_files()

        return evaluation_data
        
# Global metrics object
current_metrics = ConversationMetrics(system_instruction=SYSTEM_INSTRUCTION)

# Tool functions
def get_horoscope(sign):
    return f"{sign}: Next Tuesday you will befriend a baby otter."

def fetchWeather(location):
    return f"The weather in {location} is sunny with a high of 75°F."

# Map tool names to callables for execution
TOOL_REGISTRY = {
    "get_horoscope": get_horoscope,
    "fetchWeather": fetchWeather
}

# This is the main function to run the Voice Live API client.
def main(test_files_path: str = None, output_dir: str = None, evaluation_dir: str = None, session_timestamp: str = None, evaluation_output_file_override: str | None = None, session_suffix: str | None = None, file_metadata: Dict[str, str] = None) -> None: 
    # Create a single session timestamp for all outputs
    print(f"Session timestamp: {session_timestamp}")
    
    # Log batch mode parameters if provided
    if evaluation_output_file_override:
        print(f"Using aggregate evaluation file: {evaluation_output_file_override}")
    if session_suffix:
        print(f"Using session suffix: {session_suffix}")
    
    # Set up evaluation if requested
    global evaluation_enabled, evaluation_output_file, session_timestamp_global, session_suffix_global
    session_timestamp_global = session_timestamp  # Base timestamp reused across sessions
    session_suffix_global = session_suffix  # Track current session suffix
    if evaluation_dir:
        # When an override file is provided we aggregate all per-file sessions into one evaluation file
        if evaluation_output_file_override:
            if not os.path.exists(os.path.dirname(evaluation_output_file_override)):
                os.makedirs(os.path.dirname(evaluation_output_file_override), exist_ok=True)
            evaluation_enabled = True
            evaluation_output_file = evaluation_output_file_override
            print(f"Using AGGREGATE evaluation file: {evaluation_output_file}")
        else:
            evaluation_enabled = True
            # Single session or non-aggregate: place inside <evaluation_dir>/<timestamp>/
            root_eval_dir = os.path.join(evaluation_dir, session_timestamp_global) if session_timestamp_global else evaluation_dir
            os.makedirs(root_eval_dir, exist_ok=True)
            print(f"Using evaluation directory (timestamp root): {root_eval_dir}")
            # Extract dataset name from test_files_path (remove .jsonl extension)
            dataset_name = os.path.splitext(os.path.basename(test_files_path))[0] if test_files_path else "dataset"
            evaluation_output_file = os.path.join(root_eval_dir, f"{session_timestamp}_{dataset_name}.jsonl")
    # Set environment variables or edit the corresponding values here.
    endpoint = os.environ.get("AZURE_VOICE_LIVE_ENDPOINT") or "https://your-endpoint.azure.com/"
    model = os.environ.get("AZURE_VOICE_LIVE_MODEL") or "your_model"
    api_version = os.environ.get("AZURE_VOICE_LIVE_API_VERSION") or "2025-05-01-preview"
    api_key = os.environ.get("AZURE_VOICE_LIVE_API_KEY") or "your_api_key"
    
    # For the recommended keyless authentication, get and
    # use the Microsoft Entra token instead of api_key:
    scopes = "https://ai.azure.com/.default"
    credential = DefaultAzureCredential()
    token = credential.get_token(scopes)

    client = AzureVoiceLive(
        azure_endpoint = endpoint,
        api_version = api_version,
        token = token.token,
        # api_key = api_key,
    )
    
    connection = client.connect(model = model)
    
    # Use system_prompt from file_metadata if provided, otherwise fall back to default
    if file_metadata and file_metadata.get('system_prompt'):
        instructions = file_metadata.get('system_prompt')
        print(f"Using custom system_prompt from dataset: {instructions[:100]}...")
    else:
        instructions = SYSTEM_INSTRUCTION
        print(f"Using default SYSTEM_INSTRUCTION: {instructions}")
    
    turn_detection = {
        "type": "azure_semantic_vad",  # server_vad is based on volume and is the default. azure_semantic_vad is based on semantic meaning.
        "threshold": 0.3,
        "prefix_padding_ms": 300,
        "speech_duration_ms":80,
        "silence_duration_ms": 500,
        "remove_filler_words": False,
        "interrupt_responses": False,
        "remove_filler_words": True,  # Remove filler words like "um", "uh", etc.
        "end_of_utterance_detection": {
            "model": "semantic_detection_v1",
            "threshold_level": "default",
            "timeout_ms": 1000
        }        
    }
    if model == "gpt-4o-realtime-preview" or model == "gpt-4o-mini-realtime-preview":  # gpt-4o realtime models do not support end_of_utterance_detection
        if model == "gpt-4o-realtime-preview":
            transcription_model = "gpt-4o-transcribe" # Use gpt-4o-transcribe for gpt-4o-realtime-preview
        elif model == "gpt-4o-mini-realtime-preview":
            transcription_model = "gpt-4o-mini-transcribe" # Use gpt-4o-mini-transcribe for gpt-4o-mini-realtime-preview
        else:
            transcription_model = "whisper-1"  # Default to whisper-1 for other models.
        print(f'Using model: {model} (no end_of_utterance_detection supported) and transcription model: {transcription_model}')
    else:
        transcription_model = "azure-fast-transcription"  # Currently "azure-fast-transcription" is supported for for non gpt models. Custom Speech will be supported in the future.
        print(f'Using model: {model} (end_of_utterance_detection supported) and transcription model: {transcription_model}')
        turn_detection["end_of_utterance_detection"] = {
            "model": "semantic_detection_v1",
            "threshold": 0.1,  # Default threshold for semantic detection is 0.1
            "timeout": 4,      # Default timeout for semantic detection is 4 seconds
        }

    # Get tool definitions from dataset (file_metadata) or use empty list
    # In per-conversation mode: uses first file's tool_definitions for entire conversation
    # In per-file mode: uses each file's tool_definitions for its session
    # In single mode: uses first file's tool_definitions for the entire session
    if file_metadata and file_metadata.get('tool_definitions'):
        tools = file_metadata.get('tool_definitions')
        print(f"Using tool_definitions from dataset: {len(tools)} tool(s) configured")
        for tool in tools:
            print(f"  - {tool.get('name', 'unnamed')}: {tool.get('description', 'no description')[:50]}...")
    else:
        tools = []  # No tools configured - VoiceLive session will not have function calling
        print("No tool_definitions in dataset - session will run without function calling tools")

    # Expose tool definitions globally for evaluation logging (tool_call accuracy, etc.)
    global SESSION_TOOL_DEFINITIONS
    SESSION_TOOL_DEFINITIONS = tools

    modalities = ["audio"] # You can only set "audio" in combination with tool calling! Specify modalities for the session, e.g., ["text", "audio"] for text and audio input/output.
    
    # Build session configuration
    session_config = {
        "turn_detection": turn_detection,
        "input_audio_noise_reduction": {
            "type": "azure_deep_noise_suppression"
        },
        "input_audio_echo_cancellation": {
            "type": "server_echo_cancellation"
        },
        "input_audio_transcription": {
            "model": f"{transcription_model}",
            # "prompt": "<your-prompt-for-gpt-transcribe-or-whisper-model>", # Optional prompt for gpt-4o-transcribe or whisper models.
            # "phrase_list": ["Jan", "Goergen", "Jan Goergen", "Neo QLED TV", "TUF Gaming", "AutoQuote Explorer"] # Does not support gpt-4o-realtime-preview, gpt-4o-mini-realtime-preview, and phi4-mm-realtime
        },
        "voice": {
            "name": "en-US-Steffan:DragonHDLatestNeural", #en-US-Aria:DragonHDLatestNeural
            "type": "azure-standard", # azure-standard or azure-custom
            # "endpoint_id": "your-endpoint-id", # Custom Voice endpoint id
            "temperature": 0.8,
        },
        "output_audio_timestamp_types": ["word"], 
        "modalities": modalities,
        "instructions": instructions if not tools else f"{instructions} Use available tools when appropriate.",
    }
    
    # Only add tools to session if tool_definitions are provided
    if tools:
        session_config["tools"] = tools
    
    session_update = {
        "type": "session.update",
        "session": session_config,
        "event_id": ""
    }
    connection.send(json.dumps(session_update))
    print("Session created: ", json.dumps(session_update))

    # Ensure output directory exists with timestamp subdirectory for this run
    # Build root directory at --output-dir/<timestamp> and put per-session subfolders inside
    root_out = output_dir if output_dir is not None else os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    if session_timestamp_global:
        root_out = os.path.join(root_out, session_timestamp_global)
    # Ensure root directory exists early
    os.makedirs(root_out, exist_ok=True)
    if session_suffix_global:
        output_dir = os.path.join(root_out, session_suffix_global)
    else:
        # Single session mode writes directly into timestamp root
        output_dir = root_out
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
    else:
        print(f"Using output directory: {output_dir}")
        
    # Store the output directory in a global variable so other functions can access it
    global response_output_dir
    response_output_dir = output_dir

    # Read the test files list
    audio_file_records = read_test_files(test_files_path)
    if not audio_file_records:
        print("No audio files found in the specified file list. Exiting.")
        return
    
    audio_files = [record['audio_path'] for record in audio_file_records]
    
    # Build metadata lookup for ground truth and other fields
    audio_metadata = {record['audio_path']: record for record in audio_file_records}

    # Set expected turns for operational metrics
    global expected_turns
    expected_turns = len(audio_files)
    print(f"Expected turns from {expected_turns} input files")

    # Create and start threads
    send_thread = threading.Thread(target=send_audio_from_files, args=(connection, audio_files, audio_metadata))
    receive_thread = threading.Thread(target=receive_audio_and_save, args=(connection, modalities))
    keyboard_thread = threading.Thread(target=read_keyboard_and_quit)

    print("Starting the conversation with audio files...")
    
    send_thread.start()
    receive_thread.start()
    keyboard_thread.start()
    
    # Wait for either all files to be processed or user to quit manually
    while not stop_event.is_set() and not all_files_processed_event.is_set():
        time.sleep(0.1)
        
    # If all files are processed but stop_event is not set yet, set it to signal threads to stop
    if all_files_processed_event.is_set() and not stop_event.is_set():
        print("All files processed, shutting down...")
        stop_event.set()
    
    # Wait for threads to finish
    send_thread.join(timeout=2)
    receive_thread.join(timeout=2)
    keyboard_thread.join(timeout=2)  # Now safe to join keyboard thread as it will exit when all files are processed
    
    connection.close()
    
    # Write operational metrics summary
    write_operational_metrics_summary()
    
    print("Conversation processing complete.")

# --- End of Main Function ---

def read_test_files(test_files_path: str = None) -> List[Dict[str, str]]:
    """Read the list of audio files from sample_evaluation_input\Eiffel_Tower_Visit_1\Eiffel_Tower_Visit_1.jsonl or JSONL format
    
    Args:
        test_files_path (str, optional): Path to the file containing the list of audio files.
            If None, defaults to "sample_evaluation_input\Eiffel_Tower_Visit_1\Eiffel_Tower_Visit_1.jsonl" in the script directory.
            Supports both plain text (one file per line) and JSONL with WavPath field.
    
    Returns:
        List of dicts with 'audio_path', 'ground_truth' (Answer field if available), and other metadata
    """
    if test_files_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        test_files_path = os.path.join(script_dir, "sample_evaluation_input\Eiffel_Tower_Visit_1\Eiffel_Tower_Visit_1.jsonl")
    
    if not os.path.exists(test_files_path):
        print(f"Error: test files list not found at {test_files_path}")
        return []
    
    audio_files = []
    
    # Get the directory containing the test files list for resolving relative paths
    test_files_dir = os.path.dirname(os.path.abspath(test_files_path))
    
    # Detect if file is JSONL format
    is_jsonl = test_files_path.endswith('.jsonl')
    
    with open(test_files_path, 'r', encoding='utf-8') as f:
        if is_jsonl:
            # Parse JSONL format
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    wav_path = record.get('WavPath', record.get('audio'))
                    if not wav_path:
                        print(f"Warning: Line {line_num} missing WavPath/audio field")
                        continue
                    
                    # Convert relative paths to absolute
                    # Try multiple strategies to find the file:
                    # 1. If already absolute and exists, use it
                    # 2. If relative, try relative to JSONL file directory (same folder)
                    # 3. If path starts with "prototype_v1/", navigate to repo root
                    resolved_path = None
                    if os.path.isabs(wav_path):
                        if os.path.exists(wav_path):
                            resolved_path = wav_path
                    else:
                        # Try relative to JSONL file directory (same directory as JSONL)
                        candidate = os.path.join(test_files_dir, os.path.basename(wav_path))
                        if os.path.exists(candidate):
                            resolved_path = os.path.abspath(candidate)
                        else:
                            # Try the full relative path from JSONL directory
                            candidate = os.path.join(test_files_dir, wav_path)
                            if os.path.exists(candidate):
                                resolved_path = os.path.abspath(candidate)
                            else:
                                # Navigate up to find repo root and try from there
                                current_dir = test_files_dir
                                for _ in range(5):  # Try up to 5 levels up
                                    candidate = os.path.join(current_dir, wav_path)
                                    if os.path.exists(candidate):
                                        resolved_path = os.path.abspath(candidate)
                                        break
                                    parent = os.path.dirname(current_dir)
                                    if parent == current_dir:  # Reached root
                                        break
                                    current_dir = parent
                    
                    if not resolved_path:
                        print(f"Warning: Audio file not found: {wav_path}")
                        print(f"  Searched in: {test_files_dir}")
                        continue
                    
                    file_info = {
                        'audio_path': resolved_path,
                        'ground_truth': record.get('Answer', record.get('answer')),
                        'question': record.get('Question', record.get('question')),
                        'tool_definitions': record.get('tool_definitions', []),
                        'conversation_id': record.get('conversationID', record.get('conversation_id', 'default')),
                        'system_prompt': record.get('system_prompt')
                    }
                    audio_files.append(file_info)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse JSON on line {line_num}: {e}")
                    continue
        else:
            # Plain text format (backward compatibility)
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Check if file exists
                if os.path.exists(line):
                    audio_files.append({'audio_path': line, 'ground_truth': None, 'question': None, 'tool_definitions': []})
                else:
                    print(f"Warning: Audio file not found: {line}")
    
    print(f"Found {len(audio_files)} audio files to process")
    return audio_files

def read_wav_file(file_path: str) -> tuple[np.ndarray, int]:
    """Read a WAV file and return its data and sample rate"""
    with wave.open(file_path, 'rb') as wf:
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        data = np.frombuffer(frames, dtype=np.int16)
    return data, sample_rate

def resample_audio(audio_data: np.ndarray, orig_sample_rate: int, target_sample_rate: int) -> np.ndarray:
    """Resample audio data to the target sample rate"""
    if orig_sample_rate == target_sample_rate:
        return audio_data
    
    # Simple linear resampling for demonstration purposes
    # For production, consider using a dedicated resampling library like librosa or scipy
    duration = len(audio_data) / orig_sample_rate
    target_length = int(duration * target_sample_rate)
    indices = np.linspace(0, len(audio_data) - 1, target_length)
    resampled = np.interp(indices, np.arange(len(audio_data)), audio_data).astype(np.int16)
    return resampled

logger = logging.getLogger(__name__)
AUDIO_SAMPLE_RATE = 24000

class VoiceLiveConnection:
    def __init__(self, url: str, headers: dict) -> None:
        self._url = url
        self._headers = headers
        self._ws = None
        self._message_queue = queue.Queue()
        self._connected = False

    def connect(self) -> None:
        def on_message(ws, message):
            self._message_queue.put(message)
        
        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")
        
        def on_close(ws, close_status_code, close_msg):
            logger.info("WebSocket connection closed")
            self._connected = False
        
        def on_open(ws):
            logger.info("WebSocket connection opened")
            self._connected = True

        self._ws = websocket.WebSocketApp(
            self._url,
            header=self._headers,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )
        
        # Start WebSocket in a separate thread
        self._ws_thread = threading.Thread(target=self._ws.run_forever)
        self._ws_thread.daemon = True
        self._ws_thread.start()
        
        # Wait for connection to be established
        timeout = 10  # seconds
        start_time = time.time()
        while not self._connected and time.time() - start_time < timeout:
            time.sleep(0.1)
        
        if not self._connected:
            raise ConnectionError("Failed to establish WebSocket connection")

    def recv(self) -> str:
        try:
            return self._message_queue.get(timeout=1)
        except queue.Empty:
            return None

    def send(self, message: str) -> None:
        if self._ws and self._connected:
            self._ws.send(message)

    def close(self) -> None:
        if self._ws:
            self._ws.close()
            self._connected = False

class AzureVoiceLive:
    def __init__(
        self,
        *,
        azure_endpoint: str | None = None,
        api_version: str | None = None,
        token: str | None = None,
        api_key: str | None = None,
    ) -> None:

        self._azure_endpoint = azure_endpoint
        self._api_version = api_version
        self._token = token
        self._api_key = api_key
        self._connection = None

    def connect(self, model: str) -> VoiceLiveConnection:
        if self._connection is not None:
            raise ValueError("Already connected to the Voice Live API.")
        if not model:
            raise ValueError("Model name is required.")

        url = f"{self._azure_endpoint.rstrip('/')}/voice-live/realtime?api-version={self._api_version}&model={model}"
        url = url.replace("https://", "wss://")

        request_id = str(uuid.uuid4())
        headers = [
            f"x-ms-client-request-id: {request_id}",
            f"Authorization: Bearer {self._token}" if self._token else f"api-key: {self._api_key}"
        ]

        self._connection = VoiceLiveConnection(url, headers)
        self._connection.connect()
        return self._connection

class AudioRecorder:
    def __init__(self, output_path):
        self.output_path = output_path
        self.frames = []
        self.is_recording = False
        
    def add_data(self, data: bytes):
        if self.is_recording:
            self.frames.append(data)
            
    def start(self):
        self.is_recording = True
        self.frames = []
        
    def stop(self):
        if not self.is_recording:
            return
            
        self.is_recording = False
        if not self.frames:
            logger.warning(f"No audio data recorded for {self.output_path}")
            return
            
        try:
            # Combine all audio data
            audio_data = b''.join(self.frames)
            
            # Create a WAV file with the recorded audio
            with wave.open(self.output_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 2 bytes for int16
                wf.setframerate(AUDIO_SAMPLE_RATE)
                wf.writeframes(audio_data)
                
            logger.info(f"Response audio saved to {self.output_path}")
            print(f"Response saved to {self.output_path}")
        except Exception as e:
            logger.error(f"Error saving audio file: {e}")

def update_output_file_for_new_turn():
    """Update the current output file path based on the current turn number"""
    global current_output_file, current_turn_number, response_output_dir, actual_turns
    
    if response_output_dir:
        # Increment turn number for this new turn
        current_turn_number += 1
        actual_turns = current_turn_number  # Keep actual_turns in sync
        prefix = f"{session_suffix_global}_" if session_suffix_global else ""
        current_output_file = os.path.join(response_output_dir, f"{prefix}turn_{current_turn_number:02d}_response.wav")
        print(f"DEBUG - Updated output file for turn {current_turn_number}: {current_output_file}")

def write_operational_metrics_summary():
    """Write operational metrics summary to evaluation directory if enabled"""
    global evaluation_enabled, evaluation_output_file, expected_turns, actual_turns, session_timestamp_global
    global turns_with_audio_response, turns_with_text_only_response
    
    if evaluation_enabled and evaluation_output_file:
        operational_metrics = {
            "operational_metrics": {
                "turns_processed": f"{actual_turns}/{expected_turns}",
                "expected_turns": expected_turns,
                "actual_turns": actual_turns,
                "vad_splitting_detected": actual_turns > expected_turns,
                "turn_expansion_factor": round(actual_turns / expected_turns, 2) if expected_turns > 0 else 0,
                "turns_with_audio_response": turns_with_audio_response,
                "turns_with_text_only_response": turns_with_text_only_response,
                "audio_response_rate": round(turns_with_audio_response / actual_turns, 2) if actual_turns > 0 else 0
            },
            "session_info": {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "evaluation_mode": "enabled",
                "session_id": session_timestamp_global,
                "session_suffix": session_suffix_global
            }
        }
        evaluation_dir = os.path.dirname(evaluation_output_file)
        suffix_part = f"_{session_suffix_global}" if session_suffix_global else ""
        summary_file = os.path.join(evaluation_dir, f"operational_summary_{session_timestamp_global}{suffix_part}.json")
        try:
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(operational_metrics, f, indent=2)
            print(f"Operational metrics summary written to {summary_file}")
            # NOTE: Previously we also appended the operational metrics as a final line
            # in the evaluation jsonl file. Per updated request, this behavior has been
            # removed to keep the jsonl containing only per-turn evaluation records.
            print(f"Turns processed: {actual_turns}/{expected_turns} (actual/expected)")
            if actual_turns > expected_turns:
                print(f"VAD splitting detected: {actual_turns - expected_turns} additional turns created by Azure turn detection")
            elif actual_turns < expected_turns:
                print(f"Fewer turns than expected: {expected_turns - actual_turns} turns may have been missed or combined")
            else:
                print("Turn count matches expectations - no VAD splitting detected")
        except Exception as e:
            logger.error(f"Error writing operational metrics summary: {e}")
            print(f"Error writing operational metrics summary: {e}")
    else:
        print(f"Session completed - Turns processed: {actual_turns}/{expected_turns} (actual/expected)")
        if actual_turns > expected_turns:
            print(f"VAD splitting detected: {actual_turns - expected_turns} additional turns created by Azure turn detection")

def send_audio_from_files(connection: VoiceLiveConnection, audio_files: List[str], audio_metadata: Optional[Dict[str, Any]] = None) -> None:
    global current_metrics
    logger.info("Starting audio file processing...")
    
    if audio_metadata is None:
        audio_metadata = {}
    
    # Process each file in sequence
    for file_index, file_path in enumerate(audio_files):
        file_name = os.path.basename(file_path)
        print(f"\nProcessing file {file_index + 1}/{len(audio_files)}: {file_name}")
        
        # Wait for previous file's response AND turn finalization to complete FIRST
        # CRITICAL: Must wait for response_complete_event (turn finalized) not audio_transcript_complete_event (just transcript done)
        # This ensures the evaluation data is written BEFORE we load next file's metadata
        if file_index > 0:
            print(f"  Waiting for previous file's turn finalization to complete...")
            response_complete_event.wait(timeout=120)
        
        # Load metadata for this file AFTER waiting
        # This ensures previous file's evaluation is complete before we overwrite class variables
        if file_path in audio_metadata:
            current_metrics.ground_truth = audio_metadata[file_path].get('ground_truth')
            if current_metrics.ground_truth:
                gt_preview = current_metrics.ground_truth[:100] + "..." if len(current_metrics.ground_truth) > 100 else current_metrics.ground_truth
                print(f"  Ground truth loaded for evaluation: {gt_preview}")
            
            # Load tool_definitions from dataset (ensure it's a list, default to empty)
            tool_defs = audio_metadata[file_path].get('tool_definitions')
            current_metrics.tool_definitions = tool_defs if isinstance(tool_defs, list) else []
        else:
            # Reset to defaults if no metadata available for this file
            current_metrics.ground_truth = None
            current_metrics.tool_definitions = []
        
        # Take snapshot of metadata for this file's turn(s)
        # This prevents metadata from being overwritten when next file loads
        current_metrics.turn_ground_truth = current_metrics.ground_truth
        current_metrics.turn_tool_definitions = list(current_metrics.tool_definitions) if current_metrics.tool_definitions else []
        print(f"  Metadata snapshot captured: tool_definitions={len(current_metrics.turn_tool_definitions)}")
        
        # Note: output file will be set when each turn starts (in transcription handler)
        # Reset the completion events for this turn
        response_complete_event.clear()
        audio_transcript_complete_event.clear()
        
        # Read and process the audio file
        try:
            audio_data, sample_rate = read_wav_file(file_path)
            
            # Resample if necessary
            if sample_rate != AUDIO_SAMPLE_RATE:
                logger.info(f"Resampling audio from {sample_rate}Hz to {AUDIO_SAMPLE_RATE}Hz")
                audio_data = resample_audio(audio_data, sample_rate, AUDIO_SAMPLE_RATE)
            
            # Send the audio file in chunks
            chunk_size = int(AUDIO_SAMPLE_RATE * 0.02)  # 20ms chunks
            
            print(f"Sending audio from {file_name}...")
            for i in range(0, len(audio_data), chunk_size):
                if stop_event.is_set():
                    break
                    
                # Get chunk of audio data
                chunk = audio_data[i:i+chunk_size]
                
                # If chunk is smaller than expected, pad with silence
                if len(chunk) < chunk_size:
                    chunk = np.pad(chunk, (0, chunk_size - len(chunk)), 'constant')
                
                # Encode and send the audio chunk
                audio = base64.b64encode(chunk.tobytes()).decode("utf-8")
                param = {"type": "input_audio_buffer.append", "audio": audio, "event_id": ""}
                data_json = json.dumps(param)
                connection.send(data_json)
                
                # Small delay to simulate real-time audio
                time.sleep(0.02)
            
            print(f"Finished sending audio, waiting for response...")
            
            # Wait for audio transcript signal (indicates we're getting responses)
            # NOTE: This loop waits for audio_transcript_complete_event just to detect response arrival
            # The actual turn finalization happens in response.done event
            # The next file's iteration will wait for response_complete_event (turn finalized) before loading metadata
            silence_chunk = np.zeros(chunk_size, dtype=np.int16)
            silence_audio = base64.b64encode(silence_chunk.tobytes()).decode("utf-8")
            
            # Safety timeout to prevent infinite waiting if service fails
            safety_timeout = 60  # seconds - only triggers if service never responds
            start_time = time.time()
            
            while not audio_transcript_complete_event.is_set() and not stop_event.is_set():
                # Safety timeout check - only to prevent infinite waiting if service fails
                if time.time() - start_time > safety_timeout:
                    print(f"SAFETY TIMEOUT ({safety_timeout}s): No audio transcript received, service may have failed")
                    
                    # Write evaluation data with timeout status
                    if evaluation_enabled and evaluation_output_file and current_metrics.audio_send_end_time:
                        try:
                            evaluation_data = current_metrics.finalize_turn_and_get_evaluation_data()
                            
                            if evaluation_data:
                                global turns_with_audio_response, turns_with_text_only_response
                                if evaluation_data['metrics'].get('audio_response_received', False):
                                    turns_with_audio_response += 1
                                else:
                                    turns_with_text_only_response += 1
                                    print(f"WARNING - Safety timeout on turn {evaluation_data['metrics'].get('logical_turn_number')}: No response received within {safety_timeout}s")
                                    logger.warning(f"Turn {evaluation_data['metrics'].get('logical_turn_number')}: Safety timeout - service may have failed")
                                
                                print(f"DEBUG - Safety timeout: Turn {evaluation_data['metrics'].get('logical_turn_number')} evaluation data: {json.dumps(evaluation_data)[:200]}...")
                                if write_evaluation_data_safe(evaluation_output_file, evaluation_data):
                                    print(f"Safety timeout: Turn {evaluation_data['metrics'].get('logical_turn_number')} evaluation data written")
                            else:
                                print("DEBUG - Safety timeout: No valid turn data to write")
                        except Exception as e:
                            logger.error(f"Error writing timeout evaluation data: {e}")
                            print(f"Error writing timeout evaluation data: {e}")
                    
                    response_complete_event.set()
                    audio_transcript_complete_event.set()
                    break
                
                # Send silence to keep the connection active
                param = {"type": "input_audio_buffer.append", "audio": silence_audio, "event_id": ""}
                data_json = json.dumps(param)
                connection.send(data_json)
                
                # Wait briefly before checking again
                time.sleep(0.1)
            
            # Don't reset metrics object between files to maintain conversation context
            # We'll keep the metrics object alive across all files
            print(f"Completed processing {file_name}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            print(f"Error processing file {file_path}: {e}")
    
    print("\nAll audio files have been processed.")
    
    # Wait a few seconds for any pending transcriptions to complete
    print("Waiting for any pending transcriptions to complete...")
    time.sleep(5.0)
    
    all_files_processed_event.set()  # Signal that all files have been processed

def receive_audio_and_save(connection: VoiceLiveConnection, modalities) -> None:
    global current_metrics, tool_output_sent
    last_audio_item_id = None
    current_recorder = None
    # Buffers for function-call arguments streaming
    function_call_buffers = {}
    # Buffers for assistant text output (realtime output_text.* events)
    text_output_buffers = {}

    logger.info("Starting audio response recorder...")
    try:
        while not stop_event.is_set():
            raw_event = connection.recv()
            if raw_event is None:
                continue
                
            try:
                event = json.loads(raw_event)
                event_type = event.get("type")
                
                # Print the event type but not the entire event (which can be large)
                print(f"Received event: {event_type}")

                if event_type == "session.created":
                    session = event.get("session")
                    logger.info(f"Session created: {session.get('id')}")

                elif event_type == "response.audio.delta":
                    # If this is a new audio item, start a new recording
                    incoming_item_id = event.get("item_id")
                    if incoming_item_id != last_audio_item_id:
                        last_audio_item_id = incoming_item_id
                        # Record first audio response time for metrics and mark audio as received
                        if evaluation_enabled and current_metrics.first_audio_response_time is None:
                            current_metrics.first_audio_response_time = datetime.now()
                            current_metrics.audio_response_received = True
                        # If there's an existing recorder and a brand-new item, stop and roll to the same file (append within one turn)
                        if current_recorder and current_recorder.is_recording:
                            current_recorder.stop()
                    # Ensure we have an active recorder regardless of item_id reuse
                    if (not current_recorder or not current_recorder.is_recording) and current_output_file:
                        current_recorder = AudioRecorder(current_output_file)
                        current_recorder.start()

                    # Process the audio data
                    bytes_data = base64.b64decode(event.get("delta", ""))
                    if bytes_data and current_recorder:
                        logger.debug(f"Received audio data of length: {len(bytes_data)}")   
                        current_recorder.add_data(bytes_data)

                ### Added events for conversation logging and evaluation input ###
                # Added transcription events
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    transcript = event.get("transcript", "")
                    user_transcript = f'User Input:\t{transcript}'
                    logger.info(user_transcript)
                    print(f'\n\t{user_transcript}\n')
                    
                    # Update output file for the new turn (works both with and without evaluation)
                    update_output_file_for_new_turn()
                    
                    # Record transcription complete time for metrics
                    if evaluation_enabled:
                        current_time = datetime.now()
                        current_metrics.transcription_complete_time = current_time
                        
                        # Reset turn completion flag for new input (this fixes missing turn 4)
                        current_metrics.current_turn_complete = False
                        
                        # Avoid setting audio_send_end_time late if audio already started (prevents negative latency)
                        if not current_metrics.audio_send_end_time and current_metrics.first_audio_response_time is None:
                            current_metrics.audio_send_end_time = current_time
                            print(f"DEBUG - No audio_send_end_time detected, setting it now: {current_time}")
                            
                        # Update user content with actual transcript
                        if current_metrics.user_content:
                            current_metrics.user_content[-1]["content"][0]["text"] = transcript
                        else:
                            # If no user content exists yet, create it
                            current_metrics.user_content.append({
                                "createdAt": current_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "role": "user",
                                "content": [{
                                    "type": "text",
                                    "text": transcript
                                }]
                            })
                            print(f"DEBUG - Created new user content entry for transcript")

                # Added response text logging and output. Only returned by the API if audio output is disabled for the session.
                elif event_type == "response.text.done":
                    agent_text_response = f'Agent Text Response:\t{event.get("text", "")}'
                    logger.info(agent_text_response)
                    print(f'\n\t{agent_text_response}\n')
                    
                    # Record first text response time for metrics
                    if evaluation_enabled and current_metrics.first_text_response_time is None:
                        current_metrics.first_text_response_time = datetime.now()
                        # Add assistant response to metrics
                        current_metrics.assistant_content.append({
                            "createdAt": current_metrics.first_text_response_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "run_id": f"run_{uuid.uuid4().hex.replace('-', '')}",
                            "role": "assistant",
                            "content": [{
                                "type": "text",
                                "text": event.get("text", "")
                            }]
                        })

                # Realtime text output events (common in Realtime APIs)
                elif event_type == "response.output_text.delta":
                    item_id = event.get("item_id") or event.get("id") or "default"
                    delta = event.get("delta", "")
                    buf = text_output_buffers.get(item_id, "") + (delta or "")
                    text_output_buffers[item_id] = buf
                    # Record first text response time if not already
                    if evaluation_enabled and current_metrics.first_text_response_time is None:
                        current_metrics.first_text_response_time = datetime.now()

                elif event_type == "response.output_text.done":
                    item_id = event.get("item_id") or event.get("id") or "default"
                    full_text = text_output_buffers.pop(item_id, event.get("text", ""))
                    agent_text_response = f'Agent Text Response:\t{full_text}'
                    logger.info(agent_text_response)
                    print(f'\n\t{agent_text_response}\n')

                    # Add assistant response to metrics
                    if evaluation_enabled:
                        now = datetime.now()
                        current_metrics.assistant_content.append({
                            "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "run_id": f"run_{uuid.uuid4().hex.replace('-', '')}",
                            "role": "assistant",
                            "content": [{
                                "type": "text",
                                "text": full_text
                            }]
                        })

                # Added response audio transcript logging and output. Only returned by the API if audio transcription and audio output is enabled for the session.
                elif event_type == "response.audio_transcript.done":
                    agent_audio_response = f'Agent Audio Response:\t{event.get("transcript", "")}'
                    logger.info(agent_audio_response)
                    print(f'\n\t{agent_audio_response}\n')
                    
                    # Add audio transcript to assistant content for metrics
                    if evaluation_enabled:
                        current_time = datetime.now()
                        transcript = event.get("transcript", "")
                        
                        # For multi-part responses, we need to track if this is a new response
                        # or a continuation of a previous one
                        is_continuation = False
                        is_checking_info = any(phrase in transcript.lower() for phrase in [
                            "let me check", "hold on", "one moment", "checking", "looking", "searching", 
                            "fetching", "retrieving", "finding", "please wait", "just a sec", "accessing"
                        ])
                        
                        # If we have previous assistant content and this new response seems like a follow-up,
                        # try to identify if it's a continuation
                        if current_metrics.assistant_content:
                            last_response = current_metrics.assistant_content[-1]["content"][0]["text"]
                            if (is_checking_info or 
                                last_response.endswith("...") or
                                "checking" in last_response.lower() or
                                "looking" in last_response.lower()):
                                is_continuation = True
                        
                        if is_continuation and current_metrics.assistant_content:
                            # If this seems like a continuation of the previous response,
                            # update the existing content
                            print(f"DEBUG - Detected multi-part response, updating previous response")
                            current_metrics.assistant_content[-1]["content"][0]["text"] = transcript
                        else:
                            # Otherwise, add as a new response
                            current_metrics.assistant_content.append({
                                "createdAt": current_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "run_id": f"run_{uuid.uuid4().hex.replace('-', '')}",
                                "role": "assistant",
                                "content": [{
                                    "type": "text",
                                    "text": transcript
                                }]
                            })
                    
                    # Wait 250ms to check for additional responses
                    print("Waiting 250ms to check for additional agent responses...")
                    time.sleep(0.25)
                    
                    # Check if we received any new response.audio_transcript.delta events during the wait
                    # by checking if there are pending messages in the queue
                    additional_response_detected = False
                    temp_messages = []
                    
                    # Check up to 5 messages ahead to see if there are more audio transcript deltas
                    for _ in range(5):
                        try:
                            temp_message = connection._message_queue.get_nowait()
                            temp_messages.append(temp_message)
                            temp_event = json.loads(temp_message)
                            if temp_event.get("type") == "response.audio_transcript.delta":
                                additional_response_detected = True
                                print("DEBUG - Additional response detected, will wait for completion")
                                break
                        except queue.Empty:
                            break
                        except json.JSONDecodeError:
                            continue
                    
                    # Put all the messages back in the queue for normal processing
                    for msg in reversed(temp_messages):
                        # Put them back at the front of the queue
                        temp_queue = queue.Queue()
                        temp_queue.put(msg)
                        while not connection._message_queue.empty():
                            temp_queue.put(connection._message_queue.get())
                        connection._message_queue = temp_queue
                    
                    # If no additional response is detected, we can proceed
                    if not additional_response_detected:
                        print("No additional responses detected, response appears complete")
                        # Signal that audio transcript is complete
                        audio_transcript_complete_event.set()
                
                # Capture tool/function events for evaluation history
                elif ("tool" in (event_type or "")) or ("function" in (event_type or "")):
                    try:
                        # Handle explicit function/tool-call protocol to execute local tools
                        # Normalize common fields across providers
                        def _norm_call_id(ev: dict) -> str | None:
                            return ev.get("call_id") or ev.get("tool_call_id") or ev.get("id")

                        def _norm_name(ev: dict, buf: dict | None = None) -> str | None:
                            return ev.get("name") or ev.get("function") or (buf.get("name") if buf else None)

                        # Detect streamed arguments for function/tool calls
                        if event_type.endswith(".arguments.delta") or ".arguments.delta" in event_type:
                            call_id = _norm_call_id(event)
                            name = _norm_name(event)
                            delta = event.get("delta") or event.get("arguments") or event.get("input") or ""
                            if call_id:
                                buf = function_call_buffers.setdefault(call_id, {"name": name, "arguments": ""})
                                if name and not buf.get("name"):
                                    buf["name"] = name
                                buf["arguments"] = (buf.get("arguments") or "") + (delta or "")
                                # Record or update an assistant tool_call message for this call_id (show streaming args)
                                if evaluation_enabled:
                                    # Remove any existing placeholder for this call_id to replace with updated args
                                    current_metrics.tool_content = [m for m in current_metrics.tool_content if not (m.get("role") == "assistant" and any(c.get("tool_call_id") == call_id for c in m.get("content", [])))]
                                    raw_args = buf.get("arguments", "")
                                    parsed_args = raw_args
                                    if isinstance(raw_args, str):
                                        try:
                                            parsed_attempt = json.loads(raw_args)
                                            parsed_args = parsed_attempt
                                        except Exception:
                                            parsed_args = raw_args
                                    
                                    # Log in Azure AI Evaluation SDK compatible format
                                    current_metrics.tool_content.append({
                                        "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "role": "assistant",
                                        "content": [{
                                            "type": "tool_call",
                                            "tool_call_id": call_id,
                                            "name": name,
                                            "arguments": parsed_args
                                        }]
                                    })
                                    
                                    # Also maintain a separate tool_calls array for ToolCallAccuracyEvaluator
                                    if not hasattr(current_metrics, 'tool_calls_array'):
                                        current_metrics.tool_calls_array = []
                                    
                                    # Remove existing entry for this call_id
                                    current_metrics.tool_calls_array = [tc for tc in current_metrics.tool_calls_array if tc.get("tool_call_id") != call_id]
                                    
                                    # Add the tool call in the format expected by ToolCallAccuracyEvaluator
                                    current_metrics.tool_calls_array.append({
                                        "type": "tool_call",
                                        "tool_call_id": call_id,
                                        "name": name,
                                        "arguments": parsed_args
                                    })
                            # We know a tool call is in progress; mark pending follow-up
                            if not pending_tool_followup_event.is_set():
                                print(f"DEBUG - Tool call started (delta). call_id={call_id}, name={name}")
                                pending_tool_followup_event.set()
                            # Don't add metric entry yet; wait for done
                            continue

                        # Arguments stream completed; execute tool and send output
                        if event_type.endswith(".arguments.done") or ".arguments.done" in event_type:
                            call_id = _norm_call_id(event)
                            buf = function_call_buffers.get(call_id, {}) if call_id else {}
                            name = _norm_name(event, buf)
                            args_str = buf.get("arguments") or event.get("arguments") or event.get("input") or ""
                            # Parse arguments JSON if possible
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) and args_str else {}
                            except Exception:
                                # Keep raw if not JSON
                                args = {"raw": args_str}

                            # Execute the tool if available
                            result_text = f"[Tool {name or 'unknown'} executed with no result]"
                            try:
                                tool_fn = TOOL_REGISTRY.get(name)
                                if callable(tool_fn):
                                    # Call with kwargs if dict, else pass raw
                                    if isinstance(args, dict) and "raw" not in args:
                                        result = tool_fn(**args) if args else tool_fn()
                                    else:
                                        # If parsed as non-dict or raw
                                        result = tool_fn(args if not isinstance(args, dict) else args.get("raw"))
                                    result_text = str(result)
                                else:
                                    result_text = f"[Unknown tool: {name}]"
                            except Exception as ex:
                                result_text = f"[Tool {name} error: {ex}]"

                            print(f"DEBUG - Tool executed. call_id={call_id}, name={name}, result={result_text}")

                            # Send function output back to the model and request continuation
                            try:
                                tool_output_sent = True  # Mark that we've sent tool output and expect follow-up response
                                out_evt = {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result_text
                                    },
                                    "event_id": ""
                                }
                                connection.send(json.dumps(out_evt))
                                print(f"DEBUG - Sent conversation.item.create (function_call_output): {json.dumps(out_evt)}")
                                time.sleep(0.05)

                                create_evt = {"type": "response.create", "response": {"conversation": "auto", "modalities": modalities}, "event_id": ""}
                                connection.send(json.dumps(create_evt))
                                print(f"DEBUG - Sent response.create to continue: {json.dumps(create_evt)}")
                                # Prepare a one-time retry if the gateway doesn’t start generation
                                followup_created_event.clear()
                                def _retry_create_once():
                                    if not followup_created_event.is_set():
                                        try:
                                            retry_evt = {"type": "response.create", "response": {"conversation": "auto", "modalities": modalities,}, "event_id": ""}
                                            connection.send(json.dumps(retry_evt))
                                            print(f"DEBUG - Retried response.create: {json.dumps(retry_evt)}")
                                        except Exception as rex:
                                            logger.error(f"Failed retry response.create: {rex}")
                                threading.Timer(0.6, _retry_create_once).start()
                            except Exception as send_ex:
                                logger.error(f"Failed sending tool output: {send_ex}")

                            # Track tool output in evaluation metrics
                            if evaluation_enabled:
                                now = datetime.now()
                                # Log tool result in standardized schema
                                current_metrics.tool_content.append({
                                    "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "run_id": f"run_{uuid.uuid4().hex}",
                                    "tool_call_id": call_id,
                                    "role": "tool",
                                    "content": [{
                                        "type": "tool_result",
                                        "tool_result": [result_text] if isinstance(result_text, str) else result_text if isinstance(result_text, list) else [str(result_text)]
                                    }]
                                })

                            # Clear buffer for this call_id
                            if call_id in function_call_buffers:
                                function_call_buffers.pop(call_id, None)
                            # Continue; we've fully handled this function call
                            continue

                        # Some providers send a single function_call event with name+arguments
                        if ("function_call" in event_type) and (event.get("name") is not None) and (event.get("arguments") is not None or event.get("input") is not None):
                            call_id = _norm_call_id(event)
                            name = _norm_name(event)
                            args_str = event.get("arguments") or event.get("input") or ""
                            try:
                                args = json.loads(args_str) if isinstance(args_str, str) and args_str else {}
                            except Exception:
                                args = {"raw": args_str}
                            # Log assistant tool_call before executing
                            if evaluation_enabled:
                                current_metrics.tool_content.append({
                                    "createdAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "role": "assistant",
                                    "content": [{
                                        "type": "tool_call",
                                        "tool_call_id": call_id,
                                        "name": name,
                                        "arguments": args
                                    }]
                                })
                                
                                # Also maintain a separate tool_calls array for ToolCallAccuracyEvaluator
                                # Add the tool call in the format expected by ToolCallAccuracyEvaluator
                                current_metrics.tool_calls_array.append({
                                    "type": "tool_call",
                                    "tool_call_id": call_id,
                                    "name": name,
                                    "arguments": args
                                })
                            # Execute
                            result_text = f"[Tool {name or 'unknown'} executed with no result]"
                            try:
                                tool_fn = TOOL_REGISTRY.get(name)
                                if callable(tool_fn):
                                    if isinstance(args, dict) and "raw" not in args:
                                        result = tool_fn(**args) if args else tool_fn()
                                    else:
                                        result = tool_fn(args if not isinstance(args, dict) else args.get("raw"))
                                    result_text = str(result)
                                else:
                                    result_text = f"[Unknown tool: {name}]"
                            except Exception as ex:
                                result_text = f"[Tool {name} error: {ex}]"

                            print(f"DEBUG - Tool executed (single event). call_id={call_id}, name={name}, result={result_text}")
                            try:
                                tool_output_sent = True  # Mark that we've sent tool output and expect follow-up response
                                out_evt = {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": result_text
                                    },
                                    "event_id": ""
                                }
                                connection.send(json.dumps(out_evt))
                                print(f"DEBUG - Sent conversation.item.create (function_call_output): {json.dumps(out_evt)}")
                                time.sleep(0.05)
                                create_evt = {"type": "response.create", "response": {"conversation": "auto", "modalities": modalities,}, "event_id": ""}
                                connection.send(json.dumps(create_evt))
                                print(f"DEBUG - Sent response.create to continue: {json.dumps(create_evt)}")
                                # Prepare a one-time retry if the gateway doesn’t start generation
                                followup_created_event.clear()
                                def _retry_create_once2():
                                    if not followup_created_event.is_set():
                                        try:
                                            retry_evt = {"type": "response.create", "response": {"conversation": "auto", "modalities": modalities,}, "event_id": ""}
                                            connection.send(json.dumps(retry_evt))
                                            print(f"DEBUG - Retried response.create: {json.dumps(retry_evt)}")
                                        except Exception as rex:
                                            logger.error(f"Failed retry response.create: {rex}")
                                threading.Timer(0.6, _retry_create_once2).start()
                            except Exception as send_ex:
                                logger.error(f"Failed sending tool output: {send_ex}")
                            # Track tool output in simplified format compatible with Azure AI Evaluation SDK
                            if evaluation_enabled:
                                now = datetime.now()
                                current_metrics.tool_content.append({
                                    "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "tool_call_id": call_id,
                                    "role": "tool",
                                    "content": [result_text] if isinstance(result_text, str) else result_text if isinstance(result_text, list) else [str(result_text)]
                                })
                            continue

                        now = datetime.now()
                        # Infer a stable id for buffering deltas
                        tool_id = event.get("id") or event.get("call_id") or event.get("name") or event_type
                        # Extract any text-like payloads
                        text_parts = []
                        for key in ("output_text", "result", "arguments", "delta", "output", "transcript"):
                            val = event.get(key)
                            if val is None:
                                continue
                            if isinstance(val, (dict, list)):
                                try:
                                    text_parts.append(json.dumps(val))
                                except Exception:
                                    text_parts.append(str(val))
                            else:
                                text_parts.append(str(val))
                        payload_text = " ".join([p for p in text_parts if p]).strip()

                        # Accumulate for delta events
                        if event_type.endswith(".delta"):
                            current_metrics._tool_buffers[tool_id] = current_metrics._tool_buffers.get(tool_id, "") + (payload_text or "")
                        else:
                            # For done/other events, prefer buffer if present
                            if tool_id in current_metrics._tool_buffers:
                                payload_text = (current_metrics._tool_buffers.get(tool_id) or "").strip() or payload_text
                                # Clear buffer once consumed on a non-delta
                                current_metrics._tool_buffers.pop(tool_id, None)

                            # Build a tool message entry if we have anything meaningful
                            name = event.get("name") or event.get("tool_name") or "tool"
                            role_entry = {
                                "createdAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "role": "tool",
                                "name": name,
                                "content": [{
                                    "type": "text",
                                    "text": payload_text or f"[{event_type}]"
                                }]
                            }
                            if evaluation_enabled:
                                current_metrics.tool_content.append(role_entry)
                    except Exception as e:
                        logger.debug(f"Skipping tool/function event capture due to error: {e}")
                ### End added events for conversation logging and evaluation input ###

                elif event_type == "response.done":
                    # Response has ended, check whether to finalize or keep recording for tool follow-up
                    print(f"DEBUG - response.done event received")
                    print(f"DEBUG - evaluation_enabled: {evaluation_enabled}")
                    print(f"DEBUG - evaluation_output_file: {evaluation_output_file}")
                    print(f"DEBUG - audio_send_end_time: {current_metrics.audio_send_end_time}")
                    
                    # Wait 1000ms after response.done to ensure transcript events are processed
                    print("Waiting 2000ms after response.done to allow transcript processing...")
                    time.sleep(2.0)
                    
                    # Check if there are still audio deltas or transcript events in the queue
                    additional_audio_detected = False
                    additional_transcript_detected = False
                    temp_messages = []
                    
                    # Check up to 20 messages ahead to see if there are more audio/transcript events or pending tool calls
                    upcoming_function_events_detected = False
                    for _ in range(20):
                        try:
                            temp_message = connection._message_queue.get_nowait()
                            temp_messages.append(temp_message)
                            temp_event = json.loads(temp_message)
                            t = temp_event.get("type")
                            if t in ["response.audio.delta", "response.audio_transcript.delta"]:
                                additional_audio_detected = True
                                print(f"DEBUG - Additional audio detected after response.done: {t}")
                            # Check for pending transcript.done events that haven't been processed yet
                            if t == "response.audio_transcript.done":
                                additional_transcript_detected = True
                                print(f"DEBUG - Audio transcript.done event still pending processing")
                            # Detect upcoming function call events so we don't finalize yet
                            if t and (t.startswith("response.function_call") or ".function" in t or ".tool" in t or t.endswith(".arguments.delta") or t.endswith(".arguments.done")):
                                upcoming_function_events_detected = True
                                print(f"DEBUG - Upcoming function event detected after response.done: {t}")
                                break
                        except queue.Empty:
                            break
                        except json.JSONDecodeError:
                            continue
                    
                    # Put all the messages back in the queue for normal processing
                    for msg in reversed(temp_messages):
                        # Put them back at the front of the queue
                        temp_queue = queue.Queue()
                        temp_queue.put(msg)
                        while not connection._message_queue.empty():
                            temp_queue.put(connection._message_queue.get())
                        connection._message_queue = temp_queue
                    
                    # If there are pending transcript.done events, wait for them to be processed
                    if additional_transcript_detected:
                        print("Waiting additional 2000ms for transcript.done events to be processed...")
                        time.sleep(2.0)
                    
                    # Check if we should defer finalization for tool follow-up response
                    # Only defer if we sent tool output but haven't captured the follow-up response yet
                    should_defer_for_tool = (tool_output_sent and not current_metrics.assistant_content)
                    
                    # If additional audio is detected, wait longer and defer finalization
                    if additional_audio_detected:
                        print("Additional audio detected, waiting 3 more seconds for completion...")
                        time.sleep(3.0)
                        # Defer finalization - more content is coming
                        continue
                    elif upcoming_function_events_detected or pending_tool_followup_event.is_set() or should_defer_for_tool:
                        # Tool follow-up is expected/in-progress; defer finalization until follow-up response completes
                        # We need to wait for the agent's response that incorporates the tool result
                        print(f"DEBUG - Tool follow-up pending (should_defer={should_defer_for_tool}, assistant_content={len(current_metrics.assistant_content) if current_metrics.assistant_content else 0}); deferring turn finalization until next response.done")
                        continue
                    else:
                        print("No additional audio detected, response appears complete")
                        # Now safe to stop recording
                        if current_recorder and current_recorder.is_recording:
                            current_recorder.stop()
                    
                    # Initialize evaluation_data to None before potential use
                    evaluation_data = None
                    
                    # Write evaluation data if enabled - use new turn finalization approach
                    if evaluation_enabled and evaluation_output_file:
                        try:
                            if current_metrics.audio_send_end_time and not current_metrics.current_turn_complete:
                                # Check if we received audio but don't have assistant content yet
                                # This means audio_transcript.done hasn't been processed yet
                                if current_metrics.audio_response_received and not current_metrics.assistant_content:
                                    print("DEBUG - Audio response received but transcript not yet processed. Waiting 3 more seconds...")
                                    time.sleep(3.0)
                                
                                # Finalize the current turn and get evaluation data
                                evaluation_data = current_metrics.finalize_turn_and_get_evaluation_data()
                                
                                if evaluation_data:
                                    # Verify we have response content if audio was received
                                    if evaluation_data['metrics'].get('audio_response_received', False) and not evaluation_data.get('response'):
                                        print(f"WARNING - Turn {evaluation_data['metrics'].get('logical_turn_number')}: Audio received but no response content captured. Waiting 2 more seconds...")
                                        time.sleep(2.0)
                                        # Re-finalize to capture any late-arriving content
                                        evaluation_data = current_metrics.finalize_turn_and_get_evaluation_data()
                                    
                                    # Track audio response statistics
                                    global turns_with_audio_response, turns_with_text_only_response
                                    if evaluation_data['metrics'].get('audio_response_received', False):
                                        turns_with_audio_response += 1
                                    else:
                                        turns_with_text_only_response += 1
                                        print(f"WARNING - Turn {evaluation_data['metrics'].get('logical_turn_number')}: Text response received but no audio response. This may indicate an audio generation issue.")
                                        logger.warning(f"Turn {evaluation_data['metrics'].get('logical_turn_number')}: Text-only response (no audio)")
                                    
                                    print(f"DEBUG - Turn {evaluation_data['metrics'].get('logical_turn_number')} evaluation data: {json.dumps(evaluation_data)[:200]}...")
                                    if write_evaluation_data_safe(evaluation_output_file, evaluation_data):
                                        print(f"Turn {evaluation_data['metrics'].get('logical_turn_number')} evaluation data written to {evaluation_output_file}")
                                else:
                                    print("DEBUG - No valid turn data to write")
                            else:
                                print("DEBUG - Skipping evaluation write - no audio_send_end_time or turn already completed")
                        except Exception as e:
                            logger.error(f"Error writing evaluation data: {e}")
                            print(f"Error writing evaluation data: {e}")
                    
                    # Clear tool-followup flags ONLY if we actually finalized a turn (not deferred)
                    # If we deferred finalization above (for tool follow-up), the flags stay set
                    # Only clear them when we've successfully written evaluation data with the follow-up response
                    if (pending_tool_followup_event.is_set() or tool_output_sent) and evaluation_data and evaluation_data.get('response'):
                        print("DEBUG - Clearing tool follow-up flags after capturing follow-up response")
                        pending_tool_followup_event.clear()
                        followup_created_event.clear()
                        tool_output_sent = False
                    response_complete_event.set()
                    print("Response complete.")

                elif event_type == "input_audio_buffer.speech_started":
                    print("Speech started")
                    # For each new speech segment, we might need to start tracking a new turn
                    if evaluation_enabled:
                        # If a previous turn is pending finalization, finalize and write it now
                        if not current_metrics.current_turn_complete and current_metrics.audio_send_end_time and evaluation_output_file:
                            try:
                                evaluation_data = current_metrics.finalize_turn_and_get_evaluation_data()
                                if evaluation_data:
                                    if write_evaluation_data_safe(evaluation_output_file, evaluation_data):
                                        print(f"DEBUG - Wrote pending turn {evaluation_data['metrics'].get('logical_turn_number')} on speech start")
                                else:
                                    print("DEBUG - No valid pending turn data to write on speech start")
                            except Exception as e:
                                logger.error(f"Error writing pending turn on speech start: {e}")
                            finally:
                                # Mark the previous turn as complete
                                current_metrics.current_turn_complete = True
                            
                        # When starting a new speech segment, reset the completion events
                        # to allow the system to wait for a response after the speech is processed
                        response_complete_event.clear()
                        audio_transcript_complete_event.clear()
                        print("Reset completion events for new speech segment")
                
                # Track speech stopped to handle multi-utterance files
                elif event_type == "input_audio_buffer.speech_stopped":
                    print(f"Speech stopped detected")
                    if evaluation_enabled:
                        # For each speech segment, record the end time
                        current_metrics.audio_send_end_time = datetime.now()
                        current_metrics.current_turn_complete = False
                        # Add placeholder for user input that will be updated when transcript is received
                        current_metrics.user_content.append({
                            "createdAt": current_metrics.audio_send_end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "role": "user",
                            "content": [{
                                "type": "text",
                                "text": "[Awaiting transcription]"
                            }]
                        })
                        
                        print(f"DEBUG - New speech segment detected, audio_send_end_time set to {current_metrics.audio_send_end_time}")
                        
                    # Set response_complete_event to false to ensure we wait for responses
                    response_complete_event.clear()

                elif event_type == "error":
                    error_details = event.get("error", {})
                    error_type = error_details.get("type", "Unknown")
                    error_code = error_details.get("code", "Unknown")
                    error_message = error_details.get("message", "No message provided")
                    logger.error(f"Error received: Type={error_type}, Code={error_code}, Message={error_message}")
                    print(f"Error: {error_message}")
                # Additional visibility for response lifecycle
                elif event_type == "response.created":
                    print("DEBUG - response.created received (model started generating)")
                    followup_created_event.set()
                elif event_type == "response.error":
                    err = event.get("error") or {}
                    print(f"DEBUG - response.error: {err}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON event: {e}")
                continue

    except Exception as e:
        logger.error(f"Error in audio response recorder: {e}")
    finally:
        if current_recorder and current_recorder.is_recording:
            current_recorder.stop()
        logger.info("Audio response recorder stopped.")

def read_keyboard_and_quit() -> None:
    print("Press 'q' and Enter to quit the processing.")
    
    # Non-blocking input approach with checking for stop_event and all_files_processed_event
    import sys
    import select
    
    # Check if we're on Windows or Unix-like system
    if os.name == 'nt':  # Windows
        import msvcrt
        while not stop_event.is_set():
            # Check for keypress without blocking
            if msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8').lower()
                if key == 'q':
                    print("Quitting the process...")
                    stop_event.set()
                    break
            # Exit if all files are processed
            if all_files_processed_event.is_set():
                break
            time.sleep(0.1)  # Small sleep to prevent CPU hogging
    else:  # Unix-like systems
        import tty
        import termios
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while not stop_event.is_set():
                if select.select([sys.stdin], [], [], 0)[0]:
                    key = sys.stdin.read(1).lower()
                    if key == 'q':
                        print("Quitting the process...")
                        stop_event.set()
                        break
                # Exit if all files are processed
                if all_files_processed_event.is_set():
                    break
                time.sleep(0.1)  # Small sleep to prevent CPU hogging
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

if __name__ == "__main__":
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Process audio files through Azure Voice Live API')
        parser.add_argument('--test-files', '-f', dest='test_files_path', default='./prototype_v1/sample_evaluation_input/Eiffel_Tower_Visit_1/Eiffel_Tower_Visit_1.jsonl',
                            help='Path to the file containing the list of audio files to process')
        parser.add_argument('--output-dir', '-o', dest='output_dir', default='./output',
                            help='Directory to store response audio files (default: "output" in script directory)')
        parser.add_argument('--evaluation', '-e', dest='evaluation_dir', default='./output',
                            help='Enable evaluation data generation and specify directory to store JSONL evaluation data')
        parser.add_argument(
            '--session-mode',
            dest='session_mode',
            choices=['single', 'per-file', 'per-conversation'],
            default='single',
            help='Session handling mode: single (all files in one conversational session), per-file (each file in its own fresh session), or per-conversation (new session per conversationID)'
        )
        parser.add_argument(
            '--eval-object-id',
            dest='eval_object_id',
            default=None,
            help='Optional evaluation object ID to use in evaluation runs (for Azure AI Evaluation SDK)'
        )
        parser.add_argument(
            '--aggregate-eval-file',
            dest='aggregate_eval_file',
            default=None,
            help='Path to aggregated evaluation file (used by batch processor for multi-session aggregation)'
        )
        parser.add_argument(
            '--session-suffix',
            dest='session_suffix',
            default=None,
            help='Session suffix for identifying sessions in batch mode (e.g., conv-1, session-2)'
        )
        args = parser.parse_args()
        
        # Convert relative paths to absolute paths before changing directory
        if args.test_files_path and not os.path.isabs(args.test_files_path):
            args.test_files_path = os.path.abspath(args.test_files_path)
        if args.output_dir and not os.path.isabs(args.output_dir):
            args.output_dir = os.path.abspath(args.output_dir)
        if args.evaluation_dir and not os.path.isabs(args.evaluation_dir):
            args.evaluation_dir = os.path.abspath(args.evaluation_dir)
        
        # Change to the directory where this script is located
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        # Add folder for logging
        if not os.path.exists('logs'):
            os.makedirs('logs')
        # Add timestamp for logfiles
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # Set up logging
        logging.basicConfig(
            filename=f'logs/{timestamp}_voicelive_file_input.log',
            filemode="w",
            level=logging.WARN,
            format='%(asctime)s:%(name)s:%(levelname)s:%(message)s'
        )
        # Load environment variables from .env file
        load_dotenv("./.env", override=True)

        # Set up signal handler for graceful shutdown
        def signal_handler(signum, frame):
            print("\nReceived interrupt signal, shutting down...")
            stop_event.set()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Helper to run evaluation after a session
        def run_evaluation_if_enabled(output_dir_root: str, session_id: str, override_input_file: str | None = None, aggregate: bool = False, eval_object_id: str | None = None) -> None:
            """Run evaluation if enabled. When aggregate=True, use override_input_file as the combined JSONL."""
            if not evaluation_enabled:
                return
            eval_file_to_use = override_input_file if aggregate and override_input_file else evaluation_output_file
            if not eval_file_to_use or not os.path.exists(eval_file_to_use):
                print("No evaluation file found to run evaluation.")
                return
            try:
                import voice_agent_evaluation
            except ImportError as e:
                print(f"Error importing evaluation module: {e}")
                return
            try:
                label = "aggregate" if aggregate else session_id
                print(f"Starting {'AGGREGATE ' if aggregate else ''}evaluation for session {label}")
                eval_input_path = eval_file_to_use
                eval_name = os.path.basename(eval_file_to_use)
                eval_description = f"Voice Live API: {datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
                timestamp_root = os.path.join(output_dir_root, session_id)
                os.makedirs(timestamp_root, exist_ok=True)
                voice_agent_evaluation.main(
                    eval_input_path,
                    referenceTranscriptFilePath = "",
                    output_folder = timestamp_root,
                    eval_group_name = eval_description,
                    eval_object_id = eval_object_id if eval_object_id is not None else "",
                    eval_run_name = f"{eval_name}",
                    eval_run_scenario = eval_name,
                    dataset_id = "",
                    dataset_appendix = "",
                    setupCustomEvaluators = False
                )    

                print(f"Evaluation completed for session {label} (results in {timestamp_root})")
            except Exception as e:
                print(f"Error during evaluation: {e}")

        if args.session_mode == 'single':
            print("Running in SINGLE session mode (all files in one conversation). Use --session-mode per-file to isolate each file.")
            # For single mode, read first file's system_prompt if available
            file_list = read_test_files(args.test_files_path)
            first_file_record = None
            if file_list:
                first_file_record = file_list[0]
                first_file_system_prompt = first_file_record.get('system_prompt')
                if first_file_system_prompt:
                    reset_session_state(system_prompt=first_file_system_prompt)
                    print(f"Using custom system_prompt from dataset: {first_file_system_prompt[:50]}...")
            # Pass aggregate_eval_file and session_suffix from CLI args if provided (batch mode)
            main(args.test_files_path, args.output_dir, args.evaluation_dir, timestamp, 
                 evaluation_output_file_override=args.aggregate_eval_file, 
                 session_suffix=args.session_suffix, 
                 file_metadata=first_file_record)
            run_evaluation_if_enabled(args.output_dir, timestamp, eval_object_id = args.eval_object_id if args.eval_object_id else None)
        elif args.session_mode == 'per-conversation':
            print("Running in PER-CONVERSATION session mode (new session per conversationID with AGGREGATED evaluation).")
            # Read list of files first
            file_list = read_test_files(args.test_files_path)
            
            # Group files by conversationID
            from itertools import groupby
            from operator import itemgetter
            import shutil
            
            # Prepare aggregate evaluation file path (timestamp for the whole run)
            aggregate_run_id = timestamp  # use initial timestamp as aggregate id
            aggregated_eval_dir_base = args.evaluation_dir or args.output_dir
            if not os.path.exists(aggregated_eval_dir_base):
                os.makedirs(aggregated_eval_dir_base, exist_ok=True)
            aggregated_eval_dir = os.path.join(aggregated_eval_dir_base, aggregate_run_id)
            os.makedirs(aggregated_eval_dir, exist_ok=True)
            
            # Create temp folder for intermediate files (will be cleaned up at the end)
            temp_folder = os.path.join(aggregated_eval_dir, "temp")
            os.makedirs(temp_folder, exist_ok=True)
            
            # Extract dataset name from test_files_path (remove .jsonl or .txt extension)
            dataset_name = os.path.splitext(os.path.basename(args.test_files_path))[0] if args.test_files_path else "dataset"
            aggregated_eval_file = os.path.join(aggregated_eval_dir, f"{aggregate_run_id}_aggregate_{dataset_name}.jsonl")
            if os.path.exists(aggregated_eval_file):
                # Avoid mixing with previous run
                os.remove(aggregated_eval_file)
            print(
                "Aggregate evaluation file: "
                f"{aggregated_eval_file}\n"
                "All per-conversation session evaluation JSONL entries will be appended here."
            )
            
            # Group files by conversationID (assuming files are already sorted by conversationID and turn order)
            conversation_groups = []
            for conversation_id, group in groupby(file_list, key=itemgetter('conversation_id')):
                conversation_groups.append((conversation_id, list(group)))
            
            print(f"Found {len(conversation_groups)} conversations to process")
            
            for conv_idx, (conversation_id, conv_files) in enumerate(conversation_groups, start=1):
                # Get system_prompt from first file of conversation (applies to entire conversation)
                conv_system_prompt = conv_files[0].get('system_prompt') if conv_files else None
                
                # Reset global state between conversation sessions, with custom system_prompt if available
                reset_session_state(system_prompt=conv_system_prompt)
                
                # Create a temporary JSONL file containing only files for this conversation with metadata
                temp_list_path = os.path.join(temp_folder, f"temp_conversation_{conversation_id}_{conv_idx}.jsonl")
                with open(temp_list_path, 'w', encoding='utf-8') as tf:
                    for file_record in conv_files:
                        json.dump({
                            'WavPath': file_record['audio_path'],
                            'Answer': file_record.get('ground_truth'),
                            'Question': file_record.get('question'),
                            'tool_definitions': file_record.get('tool_definitions', []),
                            'conversationID': file_record.get('conversation_id'),
                            'system_prompt': file_record.get('system_prompt')
                        }, tf)
                        tf.write('\n')
                
                # Maintain same base timestamp; add conversation suffix
                session_id = timestamp  # base timestamp reused
                session_suffix = f"conv-{conversation_id}"
                print(f"\n--- Starting conversation session {conv_idx}/{len(conversation_groups)} for conversationID: {conversation_id} ({len(conv_files)} turns) (session_id={session_id}, suffix={session_suffix}) ---")
                
                # Pass override so all turns from this per-conversation session go into aggregate file, along with suffix
                # Also pass first file's metadata so system_prompt is used in session.update
                main(temp_list_path, args.output_dir, args.evaluation_dir, session_id, evaluation_output_file_override=aggregated_eval_file, session_suffix=session_suffix, file_metadata=conv_files[0] if conv_files else None)
            
            # Clean up temp folder after all conversations complete
            print("All per-conversation sessions completed. Cleaning up temp files...")
            try:
                shutil.rmtree(temp_folder)
            except OSError as e:
                print(f"Warning: Could not remove temp folder {temp_folder}: {e}")
            
            print("Running aggregate evaluation...")
            run_evaluation_if_enabled(args.output_dir, aggregate_run_id, override_input_file=aggregated_eval_file, aggregate=True, eval_object_id=args.eval_object_id if args.eval_object_id else None)
        else:
            print("Running in PER-FILE session mode with AGGREGATED evaluation (one evaluation run for all per-file sessions).")
            # Read list of files first
            file_list = read_test_files(args.test_files_path)
            # Prepare aggregate evaluation file path (timestamp for the whole run)
            aggregate_run_id = timestamp  # use initial timestamp as aggregate id
            # Place aggregate eval file under timestamp root folder
            aggregated_eval_dir_base = args.evaluation_dir or args.output_dir
            if not os.path.exists(aggregated_eval_dir_base):
                os.makedirs(aggregated_eval_dir_base, exist_ok=True)
            aggregated_eval_dir = os.path.join(aggregated_eval_dir_base, aggregate_run_id)
            os.makedirs(aggregated_eval_dir, exist_ok=True)
            # Extract dataset name from test_files_path (remove .jsonl or .txt extension)
            dataset_name = os.path.splitext(os.path.basename(args.test_files_path))[0] if args.test_files_path else "dataset"
            aggregated_eval_file = os.path.join(aggregated_eval_dir, f"{aggregate_run_id}_aggregate_{dataset_name}.jsonl")
            if os.path.exists(aggregated_eval_file):
                # Avoid mixing with previous run
                os.remove(aggregated_eval_file)
            print(
                "Aggregate evaluation file: "
                f"{aggregated_eval_file}\n"
                "All per-file session evaluation JSONL entries will be appended here."
            )
            
            # Create temp folder for intermediate files (will be cleaned up at the end)
            import shutil
            temp_folder = os.path.join(aggregated_eval_dir, "temp")
            os.makedirs(temp_folder, exist_ok=True)

            for idx, file_record in enumerate(file_list, start=1):
                # Get system_prompt from file record (each file can have its own system_prompt)
                file_system_prompt = file_record.get('system_prompt')
                
                # Reset global state between sessions, with custom system_prompt if available
                reset_session_state(system_prompt=file_system_prompt)
                audio_path = file_record['audio_path']
                # Create a temporary JSONL file containing only this file with metadata
                temp_list_path = os.path.join(temp_folder, f"temp_single_file_list_{idx}.jsonl")
                with open(temp_list_path, 'w', encoding='utf-8') as tf:
                    json.dump({
                        'WavPath': audio_path,
                        'Answer': file_record.get('ground_truth'),
                        'Question': file_record.get('question'),
                        'tool_definitions': file_record.get('tool_definitions', []),
                        'system_prompt': file_record.get('system_prompt')
                    }, tf)
                    tf.write('\n')
                # Maintain same base timestamp; add session-<n> suffix
                session_id = timestamp  # base timestamp reused
                session_suffix = f"session-{idx}"
                print(f"\n--- Starting session {idx}/{len(file_list)} for file: {audio_path} (session_id={session_id}, suffix={session_suffix}) ---")
                # Pass override so all turns from this per-file session go into aggregate file, along with suffix
                main(temp_list_path, args.output_dir, args.evaluation_dir, session_id, evaluation_output_file_override=aggregated_eval_file, session_suffix=session_suffix, file_metadata=file_record)
            
            # Clean up temp folder after all files complete
            print("All per-file sessions completed. Cleaning up temp files...")
            try:
                shutil.rmtree(temp_folder)
            except OSError as e:
                print(f"Warning: Could not remove temp folder {temp_folder}: {e}")
            
            print("Running aggregate evaluation...")
            run_evaluation_if_enabled(args.output_dir, aggregate_run_id, override_input_file=aggregated_eval_file, aggregate=True, eval_object_id=args.eval_object_id if args.eval_object_id else None)

    except Exception as e:
        print(f"Error: {e}")
        stop_event.set()
