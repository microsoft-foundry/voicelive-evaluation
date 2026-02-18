"""
Voice Metrics Evaluators - Custom Code-Based Evaluators for Voice Agent Metrics

This module provides FOUR separate custom code-based evaluators for Azure AI Foundry:
1. Transcription Latency Evaluator - ASR speed (target: <=300ms excellent, <=500ms good)
2. Response Latency Evaluator - TTS/generation speed (target: <=1s excellent, <=2s good)
3. Audio Delivery Evaluator - Whether audio response was successfully delivered
4. Turn Alignment Evaluator - Whether expected turns match actual turns

Each evaluator provides its own pass rate in Foundry, enabling granular visibility.

Usage:
    from voice_metrics_evaluator import (
        create_transcription_latency_evaluator,
        create_response_latency_evaluator,
        create_audio_delivery_evaluator,
        create_turn_alignment_evaluator,
        get_all_voice_metrics_testing_criteria,
        create_all_voice_metrics_evaluators,
    )
    
    # Create all evaluators at once
    create_all_voice_metrics_evaluators(project_client)
    
    # Add all to testing criteria
    testing_criteria.extend(get_all_voice_metrics_testing_criteria())

Author: Voice Live Evaluation Team
Date: January 2026
"""

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import EvaluatorVersion, EvaluatorCategory, EvaluatorDefinitionType
from typing import Dict, Any, Optional, List, Union
from time import sleep

# ============================================================================
# Configuration Constants
# ============================================================================

# Evaluator names and display names
EVALUATOR_CONFIGS = {
    "transcription_latency": {
        "name": "transcriptionLatencyEvaluator",
        "display_name": "Transcription Latency Evaluator",
        "description": "Evaluates ASR transcription latency. Pass: <=500ms, Excellent: <=300ms"
    },
    "response_latency": {
        "name": "responseLatencyEvaluator",
        "display_name": "Response Latency Evaluator", 
        "description": "Evaluates TTS/response generation latency. Pass: <=2s, Excellent: <=1s"
    },
    "audio_delivery": {
        "name": "audioDeliveryEvaluator",
        "display_name": "Audio Delivery Evaluator",
        "description": "Evaluates whether audio response was successfully delivered"
    },
    "turn_alignment": {
        "name": "turnAlignmentEvaluator",
        "display_name": "Turn Alignment Evaluator",
        "description": "Evaluates whether expected conversation turns match actual turns"
    }
}

# Legacy combined evaluator (kept for backward compatibility)
EVALUATOR_NAME = "voiceMetricsEvaluator"
EVALUATOR_DISPLAY_NAME = "Voice Metrics Evaluator (Combined)"
EVALUATOR_DESCRIPTION = """
Combined evaluator for voice agent performance metrics.
For separate pass rates, use the individual evaluators instead.
"""

# Default thresholds for voice metrics (in seconds)
DEFAULT_THRESHOLDS = {
    "transcription_latency_excellent": 0.3,   # <= 300ms is excellent
    "transcription_latency_good": 0.5,        # <= 500ms is good (pass threshold)
    "transcription_latency_acceptable": 1.0,  # <= 1s is acceptable
    "response_latency_excellent": 1.0,        # <= 1s is excellent
    "response_latency_good": 2.0,             # <= 2s is good (pass threshold)
    "response_latency_acceptable": 3.0,       # <= 3s is acceptable
}

# ============================================================================
# Individual Evaluator Code Blocks
# ============================================================================

TRANSCRIPTION_LATENCY_CODE = '''
def grade(sample: dict, item: dict) -> dict:
    """
    Evaluate ASR transcription latency.
    Pass threshold: <=500ms, Excellent: <=300ms
    """
    # Get transcription latency from various possible locations
    latency = None
    if isinstance(item, dict):
        latency = item.get("metrics.turn-audio-transcription-latency-in-seconds")
        if latency is None:
            metrics = item.get("metrics", {})
            if isinstance(metrics, dict):
                latency = metrics.get("turn-audio-transcription-latency-in-seconds")
        if latency is None:
            latency = item.get("turn-audio-transcription-latency-in-seconds")
    
    if latency is None:
        return {"result": 0.0, "label": "no_data", "reason": "No transcription latency data available", "latency_seconds": None}
    
    try:
        lat = float(latency)
        if lat <= 0.3:
            return {"result": 1.0, "label": "excellent", "reason": f"Transcription latency {lat:.3f}s is excellent (<=300ms)", "latency_seconds": lat}
        elif lat <= 0.5:
            return {"result": 0.9, "label": "good", "reason": f"Transcription latency {lat:.3f}s is good (<=500ms)", "latency_seconds": lat}
        elif lat <= 1.0:
            return {"result": 0.7, "label": "acceptable", "reason": f"Transcription latency {lat:.3f}s is acceptable (<=1s)", "latency_seconds": lat}
        else:
            return {"result": 0.3, "label": "slow", "reason": f"Transcription latency {lat:.3f}s is too slow (>1s)", "latency_seconds": lat}
    except (ValueError, TypeError):
        return {"result": 0.0, "label": "error", "reason": f"Invalid latency value: {latency}", "latency_seconds": None}
'''

RESPONSE_LATENCY_CODE = '''
def grade(sample: dict, item: dict) -> dict:
    """
    Evaluate TTS/response generation latency.
    Pass threshold: <=2s, Excellent: <=1s
    """
    # Get response latency from various possible locations
    latency = None
    if isinstance(item, dict):
        latency = item.get("metrics.turn-audio-resonse-latency-in-seconds")  # Note: typo in original field
        if latency is None:
            metrics = item.get("metrics", {})
            if isinstance(metrics, dict):
                latency = metrics.get("turn-audio-resonse-latency-in-seconds")
        if latency is None:
            latency = item.get("turn-audio-resonse-latency-in-seconds")
    
    if latency is None:
        return {"result": 0.0, "label": "no_data", "reason": "No response latency data available", "latency_seconds": None}
    
    try:
        lat = float(latency)
        if lat <= 1.0:
            return {"result": 1.0, "label": "excellent", "reason": f"Response latency {lat:.3f}s is excellent (<=1s)", "latency_seconds": lat}
        elif lat <= 2.0:
            return {"result": 0.85, "label": "good", "reason": f"Response latency {lat:.3f}s is good (<=2s)", "latency_seconds": lat}
        elif lat <= 3.0:
            return {"result": 0.6, "label": "acceptable", "reason": f"Response latency {lat:.3f}s is acceptable (<=3s)", "latency_seconds": lat}
        else:
            return {"result": 0.3, "label": "slow", "reason": f"Response latency {lat:.3f}s is too slow (>3s)", "latency_seconds": lat}
    except (ValueError, TypeError):
        return {"result": 0.0, "label": "error", "reason": f"Invalid latency value: {latency}", "latency_seconds": None}
'''

AUDIO_DELIVERY_CODE = '''
def grade(sample: dict, item: dict) -> dict:
    """
    Evaluate whether audio response was successfully delivered.
    Binary: 1.0 for success, 0.0 for failure
    """
    # Get audio delivery status from various possible locations
    audio_received = None
    if isinstance(item, dict):
        audio_received = item.get("metrics.audio_response_received")
        if audio_received is None:
            metrics = item.get("metrics", {})
            if isinstance(metrics, dict):
                audio_received = metrics.get("audio_response_received")
        if audio_received is None:
            audio_received = item.get("audio_response_received")
    
    if audio_received is None:
        return {"result": 0.0, "label": "no_data", "reason": "No audio delivery data available", "audio_received": None}
    
    if audio_received is True or str(audio_received).lower() == "true":
        return {"result": 1.0, "label": "delivered", "reason": "Audio response delivered successfully", "audio_received": True}
    else:
        return {"result": 0.0, "label": "failed", "reason": "Audio response delivery failed", "audio_received": False}
'''

TURN_ALIGNMENT_CODE = '''
def grade(sample: dict, item: dict) -> dict:
    """
    Evaluate whether expected conversation turns match actual turns.
    Expected turn is derived from counting user messages in the query history.
    """
    import re
    
    def count_user_messages(query_data):
        if not query_data:
            return None
        if isinstance(query_data, str):
            return 1
        if isinstance(query_data, list):
            count = sum(1 for msg in query_data if isinstance(msg, dict) and msg.get("role") == "user")
            return count if count > 0 else None
        return None
    
    def get_metric(item, key):
        if not isinstance(item, dict):
            return None
        val = item.get(f"metrics.{key}")
        if val is not None:
            return val
        metrics = item.get("metrics", {})
        if isinstance(metrics, dict):
            val = metrics.get(key)
            if val is not None:
                return val
        return item.get(key)
    
    # Get actual turn number
    actual_turn = get_metric(item, "logical_turn_number")
    if actual_turn is not None:
        try:
            actual_turn = int(actual_turn)
        except (ValueError, TypeError):
            actual_turn = None
    
    # Derive expected turn from query conversation history
    expected_turn = count_user_messages(item.get("query") if isinstance(item, dict) else None)
    
    # Get inputs_in_turn for shift detection
    inputs_in_turn = get_metric(item, "inputs_in_turn")
    
    if expected_turn is None:
        return {"result": 0.5, "label": "unknown", "reason": "Could not determine expected turn from query", 
                "expected_turn": None, "actual_turn": actual_turn, "alignment_status": "unknown"}
    
    if actual_turn is None:
        return {"result": 0.0, "label": "no_data", "reason": "No actual turn number recorded",
                "expected_turn": expected_turn, "actual_turn": None, "alignment_status": "no_data"}
    
    if actual_turn == expected_turn:
        return {"result": 1.0, "label": "aligned", "reason": f"Turn {actual_turn} matches expected {expected_turn}",
                "expected_turn": expected_turn, "actual_turn": actual_turn, "alignment_status": "aligned"}
    elif actual_turn == expected_turn + 1 and inputs_in_turn and int(inputs_in_turn) > 1:
        return {"result": 0.8, "label": "shifted", "reason": f"Turn {actual_turn} shifted by 1 due to {inputs_in_turn} inputs (expected {expected_turn})",
                "expected_turn": expected_turn, "actual_turn": actual_turn, "alignment_status": "shifted_multi_input"}
    elif actual_turn > expected_turn:
        diff = actual_turn - expected_turn
        score = max(0.3, 1.0 - (diff * 0.2))
        return {"result": score, "label": "extra_turns", "reason": f"Turn {actual_turn} has {diff} extra turn(s) vs expected {expected_turn}",
                "expected_turn": expected_turn, "actual_turn": actual_turn, "alignment_status": "extra_turns"}
    else:
        diff = expected_turn - actual_turn
        score = max(0.3, 1.0 - (diff * 0.2))
        return {"result": score, "label": "missing_turns", "reason": f"Turn {actual_turn} is missing {diff} turn(s) vs expected {expected_turn}",
                "expected_turn": expected_turn, "actual_turn": actual_turn, "alignment_status": "missing_turns"}
'''

# ============================================================================
# Combined Evaluator Code (Legacy - kept for backward compatibility)
# ============================================================================

COMBINED_EVALUATOR_CODE = '''
def grade(sample: dict, item: dict) -> dict:
    """
    Combined voice metrics evaluator (legacy - use individual evaluators for better pass rate visibility).
    
    This evaluator analyzes:
    1. Audio transcription latency (ASR speed)
    2. Audio response latency (TTS/generation speed)
    3. Audio delivery success rate
    4. Turn alignment (expected vs actual turn numbers)
    5. Input/response balance per turn
    
    Args:
        sample: Empty dict (not used by Foundry)
        item: Dict containing the evaluation data with metrics fields
        
    Returns:
        dict: Contains 'result' (0.0-1.0 composite score) and 'reason' (explanation)
    """
    import json
    import re
    
    # Extract metrics from item - handle both flat and nested structures
    transcription_latency = None
    response_latency = None
    audio_received = None
    turn_number = None
    expected_turn = None
    conversation_id = None
    wav_path = None
    inputs_in_turn = None
    responses_in_turn = None
    
    # Try to get metrics from item directly (flat structure)
    if isinstance(item, dict):
        transcription_latency = item.get("metrics.turn-audio-transcription-latency-in-seconds")
        response_latency = item.get("metrics.turn-audio-resonse-latency-in-seconds")  # Note: typo in original field name
        audio_received = item.get("metrics.audio_response_received")
        turn_number = item.get("metrics.logical_turn_number")
        inputs_in_turn = item.get("metrics.inputs_in_turn")
        responses_in_turn = item.get("metrics.responses_in_turn")
        
        # Get source identifiers for expected turn extraction
        conversation_id = item.get("conversationID") or item.get("conversation_id")
        wav_path = item.get("WavPath") or item.get("wav_path") or item.get("wavpath")
        
        # Also try without metrics. prefix
        if transcription_latency is None:
            transcription_latency = item.get("turn-audio-transcription-latency-in-seconds")
        if response_latency is None:
            response_latency = item.get("turn-audio-resonse-latency-in-seconds")
        if audio_received is None:
            audio_received = item.get("audio_response_received")
        if turn_number is None:
            turn_number = item.get("logical_turn_number")
        if inputs_in_turn is None:
            inputs_in_turn = item.get("inputs_in_turn")
        if responses_in_turn is None:
            responses_in_turn = item.get("responses_in_turn")
            
        # Try nested metrics object
        metrics = item.get("metrics", {})
        if isinstance(metrics, dict):
            if transcription_latency is None:
                transcription_latency = metrics.get("turn-audio-transcription-latency-in-seconds")
            if response_latency is None:
                response_latency = metrics.get("turn-audio-resonse-latency-in-seconds")
            if audio_received is None:
                audio_received = metrics.get("audio_response_received")
            if turn_number is None:
                turn_number = metrics.get("logical_turn_number")
            if inputs_in_turn is None:
                inputs_in_turn = metrics.get("inputs_in_turn")
            if responses_in_turn is None:
                responses_in_turn = metrics.get("responses_in_turn")
    
    # Extract expected turn number from conversation history in query
    # This is more reliable than WavPath since the aggregate data always has query
    def count_user_messages(query_data):
        """Count user messages in query to determine expected turn number."""
        if not query_data:
            return None
        if isinstance(query_data, str):
            return 1  # Simple string query = turn 1
        if isinstance(query_data, list):
            user_count = 0
            for msg in query_data:
                if isinstance(msg, dict) and msg.get("role") == "user":
                    user_count += 1
            return user_count if user_count > 0 else None
        return None
    
    def extract_expected_turn_from_path(path_or_id):
        """Fallback: extract turn from WavPath or conversationID if available."""
        if not path_or_id:
            return None
        path_str = str(path_or_id)
        # Pattern: turn followed by number (e.g., "turn3", "turn-3", "turn_3")
        match = re.search(r'turn[-_]?(\d+)', path_str, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    # Primary: derive expected turn from query conversation history
    query_data = item.get("query") if isinstance(item, dict) else None
    expected_turn = count_user_messages(query_data)
    
    # Fallback: try WavPath or conversationID (if source data was preserved)
    if expected_turn is None:
        expected_turn = extract_expected_turn_from_path(wav_path) or extract_expected_turn_from_path(conversation_id)
    
    # Initialize scoring components
    scores = []
    reasons = []
    
    # Get thresholds from init_parameters (with defaults)
    trans_excellent = 0.3
    trans_good = 0.5
    trans_acceptable = 1.0
    resp_excellent = 1.0
    resp_good = 2.0
    resp_acceptable = 3.0
    
    # 1. Evaluate Transcription Latency (ASR)
    if transcription_latency is not None:
        try:
            trans_lat = float(transcription_latency)
            if trans_lat <= trans_excellent:
                trans_score = 1.0
                trans_label = "excellent"
            elif trans_lat <= trans_good:
                trans_score = 0.8
                trans_label = "good"
            elif trans_lat <= trans_acceptable:
                trans_score = 0.6
                trans_label = "acceptable"
            else:
                trans_score = 0.3
                trans_label = "slow"
            scores.append(trans_score)
            reasons.append(f"Transcription: {trans_lat:.3f}s ({trans_label})")
        except (ValueError, TypeError):
            reasons.append(f"Transcription: invalid value ({transcription_latency})")
    else:
        reasons.append("Transcription: no data")
    
    # 2. Evaluate Response Latency (TTS/Generation)
    if response_latency is not None:
        try:
            resp_lat = float(response_latency)
            if resp_lat <= resp_excellent:
                resp_score = 1.0
                resp_label = "excellent"
            elif resp_lat <= resp_good:
                resp_score = 0.8
                resp_label = "good"
            elif resp_lat <= resp_acceptable:
                resp_score = 0.6
                resp_label = "acceptable"
            else:
                resp_score = 0.3
                resp_label = "slow"
            scores.append(resp_score)
            reasons.append(f"Response: {resp_lat:.3f}s ({resp_label})")
        except (ValueError, TypeError):
            reasons.append(f"Response: invalid value ({response_latency})")
    else:
        reasons.append("Response: no data")
    
    # 3. Evaluate Audio Delivery Success
    if audio_received is not None:
        if audio_received is True or str(audio_received).lower() == "true":
            audio_score = 1.0
            reasons.append("Audio: delivered successfully")
        else:
            audio_score = 0.0
            reasons.append("Audio: delivery failed")
        scores.append(audio_score)
    else:
        reasons.append("Audio: no delivery data")
    
    # 4. Evaluate Turn Alignment (expected vs actual)
    turn_alignment_score = None
    turn_alignment_status = "unknown"
    
    if expected_turn is not None and turn_number is not None:
        try:
            actual_turn = int(turn_number)
            if actual_turn == expected_turn:
                # Perfect match
                turn_alignment_score = 1.0
                turn_alignment_status = "aligned"
                reasons.append(f"Turn: {actual_turn}/{expected_turn} (aligned)")
            elif actual_turn == expected_turn + 1 and inputs_in_turn and int(inputs_in_turn) > 1:
                # Off by one due to multiple inputs in turn (e.g., empty input followed by real input)
                turn_alignment_score = 0.7
                turn_alignment_status = "shifted_multi_input"
                reasons.append(f"Turn: {actual_turn}/{expected_turn} (shifted due to {inputs_in_turn} inputs)")
            elif actual_turn > expected_turn:
                # More turns than expected - could indicate retry or error recovery
                turn_diff = actual_turn - expected_turn
                turn_alignment_score = max(0.3, 1.0 - (turn_diff * 0.2))
                turn_alignment_status = "extra_turns"
                reasons.append(f"Turn: {actual_turn}/{expected_turn} (+{turn_diff} extra)")
            elif actual_turn < expected_turn:
                # Fewer turns than expected - could indicate early termination
                turn_diff = expected_turn - actual_turn
                turn_alignment_score = max(0.3, 1.0 - (turn_diff * 0.2))
                turn_alignment_status = "missing_turns"
                reasons.append(f"Turn: {actual_turn}/{expected_turn} (-{turn_diff} missing)")
            scores.append(turn_alignment_score)
        except (ValueError, TypeError):
            reasons.append(f"Turn: alignment error (expected={expected_turn}, actual={turn_number})")
    elif turn_number is not None:
        # No expected turn to compare against, just report the actual
        reasons.append(f"Turn: {turn_number} (no expected value)")
    elif expected_turn is not None:
        # Have expected but no actual - indicates collection issue
        turn_alignment_score = 0.0
        turn_alignment_status = "no_actual_turn"
        reasons.append(f"Turn: ?/{expected_turn} (no actual turn collected)")
        scores.append(turn_alignment_score)
    else:
        reasons.append("Turn: no turn data available")
    
    # 5. Evaluate Input/Response Balance
    io_balance_score = None
    if inputs_in_turn is not None and responses_in_turn is not None:
        try:
            inputs = int(inputs_in_turn)
            responses = int(responses_in_turn)
            if inputs == 1 and responses == 1:
                # Perfect 1:1 balance
                io_balance_score = 1.0
                reasons.append("I/O: 1:1 balanced")
            elif inputs > 0 and responses > 0:
                # Some imbalance but both present
                ratio = min(inputs, responses) / max(inputs, responses)
                io_balance_score = 0.5 + (ratio * 0.5)
                reasons.append(f"I/O: {inputs}:{responses} (ratio={ratio:.2f})")
            elif responses == 0:
                # No response to input(s)
                io_balance_score = 0.0
                reasons.append(f"I/O: {inputs}:0 (no response)")
            elif inputs == 0:
                # Response without input (unusual)
                io_balance_score = 0.3
                reasons.append(f"I/O: 0:{responses} (response without input)")
            scores.append(io_balance_score)
        except (ValueError, TypeError):
            pass
    
    # Calculate composite score
    if scores:
        result = sum(scores) / len(scores)
    else:
        result = 0.0
        reasons.append("No scoreable metrics found")
    
    # Determine pass/fail label
    if result >= 0.8:
        label = "pass"
    elif result >= 0.6:
        label = "marginal"
    else:
        label = "fail"
    
    return {
        "result": round(result, 4),
        "label": label,
        "reason": " | ".join(reasons),
        "transcription_latency": transcription_latency,
        "response_latency": response_latency,
        "audio_received": audio_received,
        "actual_turn": turn_number,
        "expected_turn": expected_turn,
        "turn_alignment_status": turn_alignment_status,
        "turn_alignment_score": round(turn_alignment_score, 4) if turn_alignment_score is not None else None,
        "inputs_in_turn": inputs_in_turn,
        "responses_in_turn": responses_in_turn,
        "io_balance_score": round(io_balance_score, 4) if io_balance_score is not None else None
    }
'''

# Alternative simpler version that returns just a float (if dict return causes issues)
VOICE_METRICS_CODE_SIMPLE = '''
def grade(sample: dict, item: dict) -> float:
    """
    Evaluate voice agent performance metrics including turn alignment.
    Returns composite score 0.0-1.0.
    """
    import re
    scores = []
    
    # Get metrics
    transcription_latency = item.get("metrics.turn-audio-transcription-latency-in-seconds")
    response_latency = item.get("metrics.turn-audio-resonse-latency-in-seconds")
    audio_received = item.get("metrics.audio_response_received")
    turn_number = item.get("metrics.logical_turn_number")
    inputs_in_turn = item.get("metrics.inputs_in_turn")
    responses_in_turn = item.get("metrics.responses_in_turn")
    wav_path = item.get("WavPath") or item.get("wav_path")
    conversation_id = item.get("conversationID") or item.get("conversation_id")
    
    # Also try nested
    if transcription_latency is None:
        metrics = item.get("metrics", {})
        if isinstance(metrics, dict):
            transcription_latency = metrics.get("turn-audio-transcription-latency-in-seconds")
            response_latency = metrics.get("turn-audio-resonse-latency-in-seconds")
            audio_received = metrics.get("audio_response_received")
            turn_number = turn_number or metrics.get("logical_turn_number")
            inputs_in_turn = inputs_in_turn or metrics.get("inputs_in_turn")
            responses_in_turn = responses_in_turn or metrics.get("responses_in_turn")
    
    # Derive expected turn from query conversation history (count user messages)
    def count_user_messages(query_data):
        if not query_data:
            return None
        if isinstance(query_data, str):
            return 1
        if isinstance(query_data, list):
            return sum(1 for msg in query_data if isinstance(msg, dict) and msg.get("role") == "user") or None
        return None
    
    def extract_turn_from_path(path_or_id):
        if not path_or_id:
            return None
        match = re.search(r'turn[-_]?(\d+)', str(path_or_id), re.IGNORECASE)
        return int(match.group(1)) if match else None
    
    # Primary: derive from query history
    expected_turn = count_user_messages(item.get("query"))
    # Fallback: try WavPath/conversationID
    if expected_turn is None:
        expected_turn = extract_turn_from_path(wav_path) or extract_turn_from_path(conversation_id)
    
    # Score transcription latency
    if transcription_latency is not None:
        try:
            lat = float(transcription_latency)
            if lat <= 0.3:
                scores.append(1.0)
            elif lat <= 0.5:
                scores.append(0.8)
            elif lat <= 1.0:
                scores.append(0.6)
            else:
                scores.append(0.3)
        except:
            pass
    
    # Score response latency
    if response_latency is not None:
        try:
            lat = float(response_latency)
            if lat <= 1.0:
                scores.append(1.0)
            elif lat <= 2.0:
                scores.append(0.8)
            elif lat <= 3.0:
                scores.append(0.6)
            else:
                scores.append(0.3)
        except:
            pass
    
    # Score audio delivery
    if audio_received is not None:
        if audio_received is True or str(audio_received).lower() == "true":
            scores.append(1.0)
        else:
            scores.append(0.0)
    
    # Score turn alignment
    if expected_turn is not None and turn_number is not None:
        try:
            actual = int(turn_number)
            if actual == expected_turn:
                scores.append(1.0)  # Perfect alignment
            elif actual == expected_turn + 1 and inputs_in_turn and int(inputs_in_turn) > 1:
                scores.append(0.7)  # Shifted due to multi-input
            else:
                diff = abs(actual - expected_turn)
                scores.append(max(0.3, 1.0 - (diff * 0.2)))  # Penalty for misalignment
        except:
            pass
    
    # Score I/O balance
    if inputs_in_turn is not None and responses_in_turn is not None:
        try:
            inputs = int(inputs_in_turn)
            responses = int(responses_in_turn)
            if inputs == 1 and responses == 1:
                scores.append(1.0)
            elif inputs > 0 and responses > 0:
                ratio = min(inputs, responses) / max(inputs, responses)
                scores.append(0.5 + (ratio * 0.5))
            elif responses == 0:
                scores.append(0.0)
        except:
            pass
    
    # Return composite score
    return round(sum(scores) / len(scores), 4) if scores else 0.0
'''

# ============================================================================
# Data Schema for Voice Metrics
# ============================================================================

def get_voice_metrics_data_schema() -> Dict[str, Any]:
    """
    Returns the data schema for the voice metrics evaluator.
    This defines what fields the evaluator expects in the input data.
    """
    return {
        "required": ["item"],
        "type": "object",
        "properties": {
            "item": {
                "type": "object",
                "properties": {
                    "metrics.turn-audio-transcription-latency-in-seconds": {
                        "type": "number",
                        "description": "Time in seconds for ASR to transcribe audio input"
                    },
                    "metrics.turn-audio-resonse-latency-in-seconds": {
                        "type": "number",
                        "description": "Time in seconds for TTS to generate audio response"
                    },
                    "metrics.audio_response_received": {
                        "type": "boolean",
                        "description": "Whether audio response was successfully delivered"
                    },
                    "metrics.logical_turn_number": {
                        "type": "integer",
                        "description": "Actual turn number recorded during conversation execution"
                    },
                    "metrics.inputs_in_turn": {
                        "type": "integer",
                        "description": "Number of user inputs in this turn (usually 1, but can be >1 for retries)"
                    },
                    "metrics.responses_in_turn": {
                        "type": "integer",
                        "description": "Number of assistant responses in this turn"
                    },
                    "WavPath": {
                        "type": "string",
                        "description": "Original audio file path containing expected turn info (e.g., conversation1-turn3.wav)"
                    },
                    "conversationID": {
                        "type": "string",
                        "description": "Conversation identifier that may contain turn info"
                    },
                    "query": {
                        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]
                    },
                    "response": {
                        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]
                    },
                },
            },
        },
    }


def get_voice_metrics_item_schema() -> Dict[str, Any]:
    """
    Returns the item schema for data_source_config.
    Use this when creating the eval group.
    """
    return {
        "type": "object",
        "properties": {
            "query": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
            "response": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "object"}}]},
            "tool_definitions": {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]},
            "tool_calls": {"anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}]},
            "metrics.turn-audio-transcription-latency-in-seconds": {"type": "number"},
            "metrics.turn-audio-resonse-latency-in-seconds": {"type": "number"},
            "metrics.audio_response_received": {"type": "boolean"},
            "metrics.logical_turn_number": {"type": "integer"},
        },
        "required": ["query", "response"],
    }


# ============================================================================
# Testing Criteria Configuration
# ============================================================================

def get_voice_metrics_testing_criteria(
    pass_threshold: float = 0.7,
    use_simple_code: bool = False
) -> Dict[str, Any]:
    """
    Returns the testing criteria configuration for the voice metrics evaluator.
    
    Args:
        pass_threshold: Minimum score to pass (0.0-1.0)
        use_simple_code: If True, use the simpler float-returning version
        
    Returns:
        Dict containing the testing criteria for this evaluator
    """
    return {
        "type": "azure_ai_evaluator",
        "name": EVALUATOR_NAME,
        "evaluator_name": EVALUATOR_NAME,
        "data_mapping": {
            "metrics.turn-audio-transcription-latency-in-seconds": "{{item.metrics.turn-audio-transcription-latency-in-seconds}}",
            "metrics.turn-audio-resonse-latency-in-seconds": "{{item.metrics.turn-audio-resonse-latency-in-seconds}}",
            "metrics.audio_response_received": "{{item.metrics.audio_response_received}}",
            "metrics.logical_turn_number": "{{item.metrics.logical_turn_number}}",
        },
        "initialization_parameters": {
            "pass_threshold": pass_threshold,
        },
    }


def get_voice_metrics_testing_criteria_flat() -> Dict[str, Any]:
    """
    Returns testing criteria using flat field mapping (for datasets with flat structure).
    """
    return {
        "type": "azure_ai_evaluator",
        "name": EVALUATOR_NAME,
        "evaluator_name": EVALUATOR_NAME,
        "data_mapping": {
            # Map the entire item to let the evaluator extract metrics
            "item": "{{item}}",
        },
        "initialization_parameters": {
            "pass_threshold": 0.7,
        },
    }


# ============================================================================
# Evaluator Creation Functions
# ============================================================================

def create_voice_metrics_evaluator(
    project_client: AIProjectClient,
    use_simple_code: bool = False,
    custom_thresholds: Optional[Dict[str, float]] = None
) -> EvaluatorVersion:
    """
    Creates the voice metrics evaluator in the Azure AI Foundry project.
    
    Args:
        project_client: The AIProjectClient instance
        use_simple_code: If True, use the simpler float-returning version
        custom_thresholds: Optional custom threshold values
        
    Returns:
        EvaluatorVersion: The created evaluator version
    """
    code_text = VOICE_METRICS_CODE_SIMPLE if use_simple_code else VOICE_METRICS_CODE
    
    # If using custom thresholds, inject them into the code
    if custom_thresholds:
        # Replace default values in code (for simple version)
        for key, value in custom_thresholds.items():
            if "transcription" in key and "excellent" in key:
                code_text = code_text.replace("0.3", str(value), 1)
            # Add more replacements as needed
    
    print(f"Creating voice metrics evaluator: {EVALUATOR_NAME}")
    
    try:
        evaluator = project_client.evaluators.create_version(
            name=EVALUATOR_NAME,
            evaluator_version={
                "name": EVALUATOR_NAME,
                "categories": [EvaluatorCategory.QUALITY],
                "display_name": EVALUATOR_DISPLAY_NAME,
                "description": EVALUATOR_DESCRIPTION.strip(),
                "definition": {
                    "type": EvaluatorDefinitionType.CODE,
                    "code_text": code_text,
                    "init_parameters": {
                        "required": ["pass_threshold"],
                        "type": "object",
                        "properties": {
                            "pass_threshold": {
                                "type": "number",
                                "description": "Minimum score (0.0-1.0) to pass evaluation"
                            },
                        },
                    },
                    "metrics": {
                        "result": {
                            "type": "ordinal",
                            "desirable_direction": "increase",
                            "min_value": 0.0,
                            "max_value": 1.0,
                        }
                    },
                    "data_schema": get_voice_metrics_data_schema(),
                },
            },
        )
        
        sleep(10)  # Wait for evaluator to be created
        print(f"Voice metrics evaluator created: {evaluator.name} (version {evaluator.version})")
        return evaluator
        
    except Exception as e:
        print(f"Error creating voice metrics evaluator: {e}")
        raise


def delete_voice_metrics_evaluator_versions(
    project_client: AIProjectClient,
    keep_latest: bool = True
) -> None:
    """
    Deletes voice metrics evaluator versions.
    
    Args:
        project_client: The AIProjectClient instance
        keep_latest: If True, keeps the latest version; if False, deletes all
    """
    try:
        versions = list(project_client.evaluators.list_versions(name=EVALUATOR_NAME))
        
        if not versions:
            print(f"No versions found for evaluator: {EVALUATOR_NAME}")
            return
            
        current_version = max(int(v.version) for v in versions)
        print(f"Found {len(versions)} versions of {EVALUATOR_NAME}")
        
        # Determine which versions to delete
        if keep_latest:
            versions_to_delete = range(1, current_version)
            print(f"Keeping version {current_version}, deleting older versions")
        else:
            versions_to_delete = range(1, current_version + 1)
            print(f"Deleting all versions")
        
        for version in versions_to_delete:
            try:
                result = project_client.evaluators.delete_version(
                    name=EVALUATOR_NAME,
                    version=str(version),
                )
                print(f"Deleted version {version}: {result}")
            except Exception as e:
                print(f"Could not delete version {version}: {e}")
                
    except Exception as e:
        print(f"Error listing/deleting evaluator versions: {e}")


# ============================================================================
# Individual Evaluator Creation Functions
# ============================================================================

def _create_individual_evaluator(
    project_client: AIProjectClient,
    evaluator_key: str,
    code_text: str,
) -> EvaluatorVersion:
    """
    Internal helper to create an individual evaluator.
    """
    config = EVALUATOR_CONFIGS[evaluator_key]
    
    print(f"Creating evaluator: {config['name']}")
    
    try:
        evaluator = project_client.evaluators.create_version(
            name=config["name"],
            evaluator_version={
                "name": config["name"],
                "categories": [EvaluatorCategory.QUALITY],
                "display_name": config["display_name"],
                "description": config["description"],
                "definition": {
                    "type": EvaluatorDefinitionType.CODE,
                    "code_text": code_text,
                    "init_parameters": {
                        "required": [],
                        "type": "object",
                        "properties": {},
                    },
                    "metrics": {
                        "result": {
                            "type": "ordinal",
                            "desirable_direction": "increase",
                            "min_value": 0.0,
                            "max_value": 1.0,
                        }
                    },
                    "data_schema": {
                        "required": ["item"],
                        "type": "object",
                        "properties": {
                            "item": {"type": "object"}
                        }
                    },
                },
            },
        )
        
        sleep(5)  # Brief wait for evaluator creation
        print(f"  Created: {evaluator.name} (version {evaluator.version})")
        return evaluator
        
    except Exception as e:
        print(f"  Error creating {config['name']}: {e}")
        raise


def create_transcription_latency_evaluator(project_client: AIProjectClient) -> EvaluatorVersion:
    """Create the Transcription Latency Evaluator."""
    return _create_individual_evaluator(project_client, "transcription_latency", TRANSCRIPTION_LATENCY_CODE)


def create_response_latency_evaluator(project_client: AIProjectClient) -> EvaluatorVersion:
    """Create the Response Latency Evaluator."""
    return _create_individual_evaluator(project_client, "response_latency", RESPONSE_LATENCY_CODE)


def create_audio_delivery_evaluator(project_client: AIProjectClient) -> EvaluatorVersion:
    """Create the Audio Delivery Evaluator."""
    return _create_individual_evaluator(project_client, "audio_delivery", AUDIO_DELIVERY_CODE)


def create_turn_alignment_evaluator(project_client: AIProjectClient) -> EvaluatorVersion:
    """Create the Turn Alignment Evaluator."""
    return _create_individual_evaluator(project_client, "turn_alignment", TURN_ALIGNMENT_CODE)


def create_all_voice_metrics_evaluators(project_client: AIProjectClient) -> List[EvaluatorVersion]:
    """
    Create all four voice metrics evaluators in one call.
    
    Returns:
        List of created EvaluatorVersion objects
    """
    print("Creating all voice metrics evaluators...")
    evaluators = []
    
    evaluators.append(create_transcription_latency_evaluator(project_client))
    evaluators.append(create_response_latency_evaluator(project_client))
    evaluators.append(create_audio_delivery_evaluator(project_client))
    evaluators.append(create_turn_alignment_evaluator(project_client))
    
    print(f"\nCreated {len(evaluators)} voice metrics evaluators")
    return evaluators


def delete_all_voice_metrics_evaluators(project_client: AIProjectClient, keep_latest: bool = False) -> None:
    """
    Delete all voice metrics evaluator versions.
    
    Args:
        project_client: The AIProjectClient instance
        keep_latest: If True, keeps the latest version of each; if False, deletes all
    """
    for config in EVALUATOR_CONFIGS.values():
        try:
            versions = list(project_client.evaluators.list_versions(name=config["name"]))
            if not versions:
                print(f"No versions found for: {config['name']}")
                continue
                
            current_version = max(int(v.version) for v in versions)
            print(f"Found {len(versions)} versions of {config['name']}")
            
            if keep_latest:
                versions_to_delete = range(1, current_version)
            else:
                versions_to_delete = range(1, current_version + 1)
            
            for version in versions_to_delete:
                try:
                    project_client.evaluators.delete_version(name=config["name"], version=str(version))
                    print(f"  Deleted {config['name']} version {version}")
                except Exception as e:
                    print(f"  Could not delete version {version}: {e}")
                    
        except Exception as e:
            print(f"Error managing {config['name']}: {e}")


# ============================================================================
# Testing Criteria Functions
# ============================================================================

def get_transcription_latency_testing_criteria() -> Dict[str, Any]:
    """Get testing criteria for transcription latency evaluator."""
    return {
        "evaluator": EVALUATOR_CONFIGS["transcription_latency"]["name"],
        "init_parameters": {},
    }


def get_response_latency_testing_criteria() -> Dict[str, Any]:
    """Get testing criteria for response latency evaluator."""
    return {
        "evaluator": EVALUATOR_CONFIGS["response_latency"]["name"],
        "init_parameters": {},
    }


def get_audio_delivery_testing_criteria() -> Dict[str, Any]:
    """Get testing criteria for audio delivery evaluator."""
    return {
        "evaluator": EVALUATOR_CONFIGS["audio_delivery"]["name"],
        "init_parameters": {},
    }


def get_turn_alignment_testing_criteria() -> Dict[str, Any]:
    """Get testing criteria for turn alignment evaluator."""
    return {
        "evaluator": EVALUATOR_CONFIGS["turn_alignment"]["name"],
        "init_parameters": {},
    }


def get_all_voice_metrics_testing_criteria() -> List[Dict[str, Any]]:
    """
    Get testing criteria for all four voice metrics evaluators.
    Use this to add all evaluators to your testing_criteria list.
    
    Example:
        testing_criteria.extend(get_all_voice_metrics_testing_criteria())
    """
    return [
        get_transcription_latency_testing_criteria(),
        get_response_latency_testing_criteria(),
        get_audio_delivery_testing_criteria(),
        get_turn_alignment_testing_criteria(),
    ]


# ============================================================================
# Utility Functions
# ============================================================================

def analyze_voice_metrics_locally(data: Union[list, str]) -> Dict[str, Any]:
    """
    Analyze voice metrics locally without calling Foundry.
    Useful for quick local analysis of evaluation data.
    
    Args:
        data: List of evaluation records with metrics, OR path to a JSONL file
        
    Returns:
        Dict with aggregated statistics including turn alignment
    """
    import re
    import json
    
    # If data is a string, treat it as a file path and load JSONL
    if isinstance(data, str):
        with open(data, 'r', encoding='utf-8') as f:
            data = [json.loads(line) for line in f if line.strip()]
    
    transcription_latencies = []
    response_latencies = []
    audio_success_count = 0
    audio_total = 0
    turn_numbers = []
    
    # Turn alignment tracking
    turn_alignments = {"aligned": 0, "shifted": 0, "extra": 0, "missing": 0, "unknown": 0}
    turn_details = []
    io_balances = {"perfect": 0, "imbalanced": 0, "no_response": 0, "unknown": 0}
    
    def count_user_messages(query_data):
        """Count user messages in query to determine expected turn number."""
        if not query_data:
            return None
        if isinstance(query_data, str):
            return 1
        if isinstance(query_data, list):
            user_count = sum(1 for msg in query_data if isinstance(msg, dict) and msg.get("role") == "user")
            return user_count if user_count > 0 else None
        return None
    
    def extract_turn_from_path(path_or_id):
        """Fallback: extract turn from WavPath or conversationID."""
        if not path_or_id:
            return None
        match = re.search(r'turn[-_]?(\d+)', str(path_or_id), re.IGNORECASE)
        return int(match.group(1)) if match else None
    
    def get_metric(ds, key):
        """Get metric from various possible locations in the data structure."""
        # Try flat key with prefix (e.g., "metrics.logical_turn_number")
        val = ds.get(f"metrics.{key}")
        if val is not None:
            return val
        # Try nested metrics object
        metrics = ds.get("metrics", {})
        if isinstance(metrics, dict):
            val = metrics.get(key)
            if val is not None:
                return val
        # Try direct key
        return ds.get(key)
    
    for item in data:
        # Handle nested structure (datasource_item wrapper or direct)
        if isinstance(item, dict):
            ds = item.get("datasource_item", item)
            
            trans_lat = get_metric(ds, "turn-audio-transcription-latency-in-seconds")
            if trans_lat is not None:
                try:
                    transcription_latencies.append(float(trans_lat))
                except (ValueError, TypeError):
                    pass
                    
            resp_lat = get_metric(ds, "turn-audio-resonse-latency-in-seconds")
            if resp_lat is not None:
                try:
                    response_latencies.append(float(resp_lat))
                except (ValueError, TypeError):
                    pass
                    
            audio_recv = get_metric(ds, "audio_response_received")
            if audio_recv is not None:
                audio_total += 1
                if audio_recv is True or str(audio_recv).lower() == "true":
                    audio_success_count += 1
                    
            turn = get_metric(ds, "logical_turn_number")
            if turn is not None:
                turn_numbers.append(int(turn))
            
            # Primary: derive expected turn from query conversation history
            expected_turn = count_user_messages(ds.get("query"))
            # Fallback: try WavPath or conversationID
            if expected_turn is None:
                wav_path = ds.get("WavPath") or ds.get("wav_path")
                conv_id = ds.get("conversationID") or ds.get("conversation_id")
                expected_turn = extract_turn_from_path(wav_path) or extract_turn_from_path(conv_id)
            
            actual_turn = int(turn) if turn is not None else None
            
            # Analyze turn alignment
            inputs_in_turn = get_metric(ds, "inputs_in_turn")
            responses_in_turn = get_metric(ds, "responses_in_turn")
            
            if expected_turn is not None and actual_turn is not None:
                if actual_turn == expected_turn:
                    turn_alignments["aligned"] += 1
                    status = "aligned"
                elif actual_turn == expected_turn + 1 and inputs_in_turn and int(inputs_in_turn) > 1:
                    turn_alignments["shifted"] += 1
                    status = "shifted"
                elif actual_turn > expected_turn:
                    turn_alignments["extra"] += 1
                    status = "extra"
                else:
                    turn_alignments["missing"] += 1
                    status = "missing"
                
                # Get a meaningful source identifier for debugging
                source_id = None
                query_data = ds.get("query")
                if isinstance(query_data, list):
                    # Get last user message as identifier
                    for msg in reversed(query_data):
                        if isinstance(msg, dict) and msg.get("role") == "user":
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        text = c.get("text", "")[:40]
                                        source_id = f'"{text}..."' if len(c.get("text", "")) > 40 else f'"{text}"'
                                        break
                            elif isinstance(content, str):
                                source_id = f'"{content[:40]}..."' if len(content) > 40 else f'"{content}"'
                            break
                if not source_id:
                    wav_path = ds.get("WavPath") or ds.get("wav_path")
                    conv_id = ds.get("conversationID") or ds.get("conversation_id")
                    source_id = wav_path or conv_id or "unknown"
                
                turn_details.append({
                    "expected": expected_turn,
                    "actual": actual_turn,
                    "status": status,
                    "source": source_id
                })
            else:
                turn_alignments["unknown"] += 1
            
            # Analyze I/O balance
            if inputs_in_turn is not None and responses_in_turn is not None:
                inputs = int(inputs_in_turn)
                responses = int(responses_in_turn)
                if inputs == 1 and responses == 1:
                    io_balances["perfect"] += 1
                elif responses == 0:
                    io_balances["no_response"] += 1
                else:
                    io_balances["imbalanced"] += 1
            else:
                io_balances["unknown"] += 1
    
    # Calculate statistics
    total_alignment_known = sum(turn_alignments.values()) - turn_alignments["unknown"]
    
    stats = {
        "total_records": len(data),
        "transcription_latency": {
            "count": len(transcription_latencies),
            "min": min(transcription_latencies) if transcription_latencies else None,
            "max": max(transcription_latencies) if transcription_latencies else None,
            "avg": sum(transcription_latencies) / len(transcription_latencies) if transcription_latencies else None,
        },
        "response_latency": {
            "count": len(response_latencies),
            "min": min(response_latencies) if response_latencies else None,
            "max": max(response_latencies) if response_latencies else None,
            "avg": sum(response_latencies) / len(response_latencies) if response_latencies else None,
        },
        "audio_delivery": {
            "total": audio_total,
            "success": audio_success_count,
            "success_rate": audio_success_count / audio_total if audio_total > 0 else None,
        },
        "turns": {
            "count": len(turn_numbers),
            "unique": len(set(turn_numbers)),
            "max_turn": max(turn_numbers) if turn_numbers else None,
        },
        "turn_alignment": {
            **turn_alignments,
            "alignment_rate": turn_alignments["aligned"] / total_alignment_known if total_alignment_known > 0 else None,
            "details": turn_details[:10] if len(turn_details) > 10 else turn_details,  # First 10 for brevity
        },
        "io_balance": io_balances,
    }
    
    # Calculate INDIVIDUAL pass rates for each evaluator
    # Transcription Latency: pass if <= 0.5s (good threshold)
    trans_pass = sum(1 for lat in transcription_latencies if lat <= 0.5)
    trans_excellent = sum(1 for lat in transcription_latencies if lat <= 0.3)
    
    # Response Latency: pass if <= 2.0s (good threshold)
    resp_pass = sum(1 for lat in response_latencies if lat <= 2.0)
    resp_excellent = sum(1 for lat in response_latencies if lat <= 1.0)
    
    # Audio Delivery: pass if delivered
    audio_pass = audio_success_count
    
    # Turn Alignment: pass if aligned or shifted (minor issue)
    turn_pass = turn_alignments["aligned"] + turn_alignments["shifted"]
    
    stats["individual_pass_rates"] = {
        "transcription_latency": {
            "pass_count": trans_pass,
            "excellent_count": trans_excellent,
            "total": len(transcription_latencies),
            "pass_rate": trans_pass / len(transcription_latencies) if transcription_latencies else None,
        },
        "response_latency": {
            "pass_count": resp_pass,
            "excellent_count": resp_excellent,
            "total": len(response_latencies),
            "pass_rate": resp_pass / len(response_latencies) if response_latencies else None,
        },
        "audio_delivery": {
            "pass_count": audio_pass,
            "total": audio_total,
            "pass_rate": audio_pass / audio_total if audio_total > 0 else None,
        },
        "turn_alignment": {
            "pass_count": turn_pass,
            "total": total_alignment_known,
            "pass_rate": turn_pass / total_alignment_known if total_alignment_known > 0 else None,
        },
    }
    
    # Legacy combined pass rate
    pass_count = 0
    for i in range(len(data)):
        score = 0
        score_count = 0
        
        if i < len(transcription_latencies):
            lat = transcription_latencies[i] if i < len(transcription_latencies) else None
            if lat is not None:
                if lat <= 0.5:
                    score += 1.0
                elif lat <= 1.0:
                    score += 0.6
                else:
                    score += 0.3
                score_count += 1
                
        if i < len(response_latencies):
            lat = response_latencies[i] if i < len(response_latencies) else None
            if lat is not None:
                if lat <= 2.0:
                    score += 1.0
                elif lat <= 3.0:
                    score += 0.6
                else:
                    score += 0.3
                score_count += 1
        
        if score_count > 0 and (score / score_count) >= 0.7:
            pass_count += 1
    
    stats["estimated_pass_rate"] = pass_count / len(data) if data else 0
    
    return stats


def print_voice_metrics_summary(stats: Dict[str, Any]) -> None:
    """Pretty print the voice metrics summary including individual pass rates."""
    print("\n" + "=" * 70)
    print("VOICE METRICS SUMMARY (Individual Evaluator Preview)")
    print("=" * 70)
    
    print(f"\nTotal Records: {stats['total_records']}")
    
    # Individual pass rates section (what you'd see in Foundry)
    ipr = stats.get("individual_pass_rates", {})
    
    print("\n" + "-" * 70)
    print("INDIVIDUAL EVALUATOR PASS RATES")
    print("-" * 70)
    
    # Transcription Latency
    tl = stats["transcription_latency"]
    tl_pr = ipr.get("transcription_latency", {})
    print(f"\n1. TRANSCRIPTION LATENCY EVALUATOR")
    if tl["count"] > 0:
        print(f"   Range: {tl['min']:.3f}s - {tl['max']:.3f}s (avg: {tl['avg']:.3f}s)")
        print(f"   Excellent (<=300ms): {tl_pr.get('excellent_count', 0)}/{tl['count']}")
        print(f"   Pass (<=500ms):      {tl_pr.get('pass_count', 0)}/{tl['count']}")
        pr = tl_pr.get('pass_rate')
        print(f"   PASS RATE: {pr*100:.1f}%" if pr is not None else "   PASS RATE: N/A")
    else:
        print("   No data")
    
    # Response Latency
    rl = stats["response_latency"]
    rl_pr = ipr.get("response_latency", {})
    print(f"\n2. RESPONSE LATENCY EVALUATOR")
    if rl["count"] > 0:
        print(f"   Range: {rl['min']:.3f}s - {rl['max']:.3f}s (avg: {rl['avg']:.3f}s)")
        print(f"   Excellent (<=1s): {rl_pr.get('excellent_count', 0)}/{rl['count']}")
        print(f"   Pass (<=2s):      {rl_pr.get('pass_count', 0)}/{rl['count']}")
        pr = rl_pr.get('pass_rate')
        print(f"   PASS RATE: {pr*100:.1f}%" if pr is not None else "   PASS RATE: N/A")
    else:
        print("   No data")
    
    # Audio Delivery
    ad = stats["audio_delivery"]
    ad_pr = ipr.get("audio_delivery", {})
    print(f"\n3. AUDIO DELIVERY EVALUATOR")
    if ad["total"] > 0:
        print(f"   Delivered: {ad['success']}/{ad['total']}")
        pr = ad_pr.get('pass_rate')
        print(f"   PASS RATE: {pr*100:.1f}%" if pr is not None else "   PASS RATE: N/A")
    else:
        print("   No data")
    
    # Turn Alignment
    ta = stats.get("turn_alignment", {})
    ta_pr = ipr.get("turn_alignment", {})
    print(f"\n4. TURN ALIGNMENT EVALUATOR")
    if ta:
        total = ta_pr.get('total', 0)
        print(f"   Aligned:  {ta.get('aligned', 0)}/{total}")
        print(f"   Shifted:  {ta.get('shifted', 0)}/{total} (multi-input, considered pass)")
        print(f"   Extra:    {ta.get('extra', 0)}/{total}")
        print(f"   Missing:  {ta.get('missing', 0)}/{total}")
        pr = ta_pr.get('pass_rate')
        print(f"   PASS RATE: {pr*100:.1f}%" if pr is not None else "   PASS RATE: N/A")
        
        # Show misalignment details if any
        details = ta.get('details', [])
        misaligned = [d for d in details if d.get('status') not in ('aligned', 'shifted')]
        if misaligned:
            print(f"\n   Misalignment Details (first 3):")
            for d in misaligned[:3]:
                print(f"     - {d.get('source', 'N/A')}: expected={d.get('expected')}, actual={d.get('actual')} ({d.get('status')})")
    else:
        print("   No data")
    
    # I/O Balance (informational)
    print(f"\n" + "-" * 70)
    print("ADDITIONAL METRICS (Informational)")
    print("-" * 70)
    
    print(f"\nTurn Distribution:")
    t = stats["turns"]
    print(f"  Turn count: {t['count']}, Unique turns: {t['unique']}, Max turn: {t['max_turn']}")
    
    io = stats.get("io_balance", {})
    if io:
        print(f"\nInput/Output Balance:")
        print(f"  Perfect (1:1): {io.get('perfect', 0)}, Imbalanced: {io.get('imbalanced', 0)}, No Response: {io.get('no_response', 0)}")
    
    print(f"\nLegacy Combined Pass Rate: {stats['estimated_pass_rate']*100:.1f}%")
    print("=" * 70 + "\n")


# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    """
    Example usage of the voice metrics evaluator module.
    """
    import os
    import json
    from dotenv import load_dotenv
    from azure.identity import DefaultAzureCredential
    
    # Load environment
    load_dotenv()
    
    print("Voice Metrics Evaluator Module")
    print("=" * 40)
    
    # Example 1: Local analysis of existing data
    sample_data = [
        {
            "datasource_item": {
                "metrics.turn-audio-transcription-latency-in-seconds": 0.32,
                "metrics.turn-audio-resonse-latency-in-seconds": 1.12,
                "metrics.audio_response_received": True,
                "metrics.logical_turn_number": 1,
            }
        },
        {
            "datasource_item": {
                "metrics.turn-audio-transcription-latency-in-seconds": 0.45,
                "metrics.turn-audio-resonse-latency-in-seconds": 1.35,
                "metrics.audio_response_received": True,
                "metrics.logical_turn_number": 2,
            }
        },
    ]
    
    print("\n--- Local Analysis Example ---")
    stats = analyze_voice_metrics_locally(sample_data)
    print_voice_metrics_summary(stats)
    
    # Example 2: Show what the testing criteria would look like
    print("\n--- Testing Criteria Example ---")
    criteria = get_voice_metrics_testing_criteria(pass_threshold=0.7)
    print(json.dumps(criteria, indent=2))
    
    # Example 3: Create evaluator in Foundry (commented out - requires connection)
    """
    project_endpoint = os.getenv("PROJECT_ENDPOINT")
    if project_endpoint:
        project_client = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint=project_endpoint
        )
        
        # Create the evaluator
        evaluator = create_voice_metrics_evaluator(project_client, use_simple_code=True)
        print(f"Created evaluator: {evaluator.name} v{evaluator.version}")
        
        # Clean up old versions
        delete_voice_metrics_evaluator_versions(project_client, keep_latest=True)
    """
    
    print("\nTo use this evaluator in voice_agent_evaluation.py:")
    print("1. Import: from voice_metrics_evaluator import create_voice_metrics_evaluator, get_voice_metrics_testing_criteria")
    print("2. Create evaluator: create_voice_metrics_evaluator(project_client)")
    print("3. Add to testing_criteria list: testing_criteria.append(get_voice_metrics_testing_criteria())")
