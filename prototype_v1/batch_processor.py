"""
Batch Processor for Voice Agent Audio Input Evaluation

This script provides multi-threaded processing for voice_agent_audio_input_evaluation.py.
Each session (single, per-conversation, or per-file) runs as a separate subprocess to avoid
global state conflicts.

Usage:
    # Process a single dataset with parallel conversation sessions
    python batch_processor.py --test-files dataset.jsonl --session-mode per-conversation --max-workers 4
    
    # Process multiple datasets sequentially, each with parallel file sessions  
    python batch_processor.py --test-files-folder ./datasets --session-mode per-file --max-workers 2
    
    # Process a dataset in single session mode (no parallelism for sessions)
    python batch_processor.py --test-files dataset.jsonl --session-mode single
"""

import os
import sys
import subprocess
import argparse
import json
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
import logging
import concurrent.futures
from itertools import groupby
from operator import itemgetter

# Global logger and file-only logger
logger = logging.getLogger(__name__)
file_logger = logging.getLogger(__name__ + '.file_only')


def setup_logging(log_file: str, verbose: bool = False):
    """
    Set up logging to both file and console.
    
    Args:
        log_file: Path to the log file
        verbose: If True, include DEBUG level in file; otherwise INFO and above only
    """
    # Main logger - logs to both file and console
    logger.setLevel(logging.DEBUG)
    
    # File handler - logs DEBUG if verbose, otherwise INFO and above
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler - logs INFO and above (skips DEBUG/verbose)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File-only logger - same file handler, no console
    file_logger.setLevel(logging.DEBUG)
    file_logger.addHandler(file_handler)
    file_logger.propagate = False


def log_message(message: str, level: str = "info", file_only: bool = False):
    """
    Log message to both file and console, with Unicode handling.
    
    Args:
        message: The message to log
        level: Log level ('debug', 'info', 'warning', 'error')
        file_only: If True, only log to file, not console
    """
    target_logger = file_logger if file_only else logger
    
    try:
        if level == "debug":
            target_logger.debug(message)
        elif level == "info":
            target_logger.info(message)
        elif level == "warning":
            target_logger.warning(message)
        elif level == "error":
            target_logger.error(message)
    except UnicodeEncodeError:
        safe_message = message.encode('ascii', errors='replace').decode('ascii')
        if level == "debug":
            target_logger.debug(safe_message)
        elif level == "info":
            target_logger.info(safe_message)
        elif level == "warning":
            target_logger.warning(safe_message)
        elif level == "error":
            target_logger.error(safe_message)


def read_test_files(test_files_path: str) -> List[Dict[str, Any]]:
    """
    Read the list of audio files from JSONL format.
    
    Args:
        test_files_path: Path to the JSONL file containing audio file records
    
    Returns:
        List of dicts with audio_path, ground_truth, conversation_id, etc.
    """
    if not os.path.exists(test_files_path):
        raise FileNotFoundError(f"Test file not found: {test_files_path}")
    
    audio_files = []
    test_files_dir = os.path.dirname(os.path.abspath(test_files_path))
    is_jsonl = test_files_path.endswith('.jsonl')
    
    with open(test_files_path, 'r', encoding='utf-8') as f:
        if is_jsonl:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    wav_path = record.get('WavPath') or record.get('audio_path') or record.get('wav_path')
                    if not wav_path:
                        continue
                    
                    # Resolve relative paths
                    if not os.path.isabs(wav_path):
                        wav_path = os.path.join(test_files_dir, wav_path)
                    
                    audio_files.append({
                        'audio_path': wav_path,
                        'ground_truth': record.get('Answer') or record.get('ground_truth'),
                        'question': record.get('Question') or record.get('question'),
                        'conversation_id': record.get('conversationID') or record.get('conversation_id') or 'default',
                        'tool_definitions': record.get('tool_definitions', []),
                        'system_prompt': record.get('system_prompt')
                    })
                except json.JSONDecodeError:
                    continue
        else:
            # Plain text format - one file per line
            for line in f:
                line = line.strip()
                if not line:
                    continue
                wav_path = line
                if not os.path.isabs(wav_path):
                    wav_path = os.path.join(test_files_dir, wav_path)
                audio_files.append({
                    'audio_path': wav_path,
                    'ground_truth': None,
                    'question': None,
                    'conversation_id': 'default',
                    'tool_definitions': [],
                    'system_prompt': None
                })
    
    return audio_files


def run_session_subprocess(
    session_info: Dict[str, Any],
    base_args: Dict[str, Any],
    verbose: bool = False,
    timeout: int = 600
) -> Tuple[str, int, str, str]:
    """
    Run a single session as a subprocess of voice_agent_audio_input_evaluation.py.
    
    Args:
        session_info: Dict containing session details (temp_file_path, session_id, suffix, etc.)
        base_args: Base arguments for the evaluation script
        verbose: If True, show detailed output
        timeout: Timeout in seconds for the subprocess
    
    Returns:
        tuple: (session_id, return_code, stdout, stderr)
    """
    script_dir = Path(__file__).parent
    v3_script_path = script_dir / "voice_agent_audio_input_evaluation.py"
    
    session_id = session_info.get('session_id', 'unknown')
    suffix = session_info.get('suffix', '')
    temp_file_path = session_info.get('temp_file_path')
    aggregated_eval_file = session_info.get('aggregated_eval_file')
    
    try:
        # Build command with all parameters passed as CLI arguments
        cmd = [
            sys.executable, str(v3_script_path),
            '--test-files', temp_file_path,
            '--output-dir', base_args['output_dir'],
            '--evaluation', base_args['evaluation_dir'],
            '--session-mode', 'single'  # Each subprocess runs in single mode
        ]
        
        # Add batch-specific parameters as CLI arguments
        if aggregated_eval_file:
            cmd.extend(['--aggregate-eval-file', aggregated_eval_file])
        if suffix:
            cmd.extend(['--session-suffix', suffix])
        
        if base_args.get('eval_object_id'):
            cmd.extend(['--eval-object-id', base_args['eval_object_id']])
        
        log_message(f"Starting session subprocess: {suffix or session_id}", level="debug")
        log_message(f"Command: {' '.join(cmd)}", level="debug", file_only=True)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(script_dir)
        )
        
        if result.stdout and verbose:
            for line in result.stdout.strip().split('\n'):
                if line:
                    log_message(f"[{suffix}] {line}", level="debug")
        
        if result.returncode == 0:
            log_message(f"✓ Session completed: {suffix or session_id}")
            return session_id, 0, result.stdout, ""
        else:
            error_msg = result.stderr or "Unknown error"
            log_message(f"✗ Session failed: {suffix or session_id} - {error_msg[:200]}", level="error")
            return session_id, result.returncode, result.stdout, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = f"Session timed out after {timeout}s"
        log_message(f"✗ Timeout: {suffix or session_id}", level="error")
        return session_id, -1, "", error_msg
    except Exception as e:
        error_msg = str(e)
        log_message(f"✗ Exception in session {suffix or session_id}: {error_msg}", level="error")
        return session_id, -1, "", error_msg


def prepare_conversation_sessions(
    file_list: List[Dict[str, Any]],
    temp_folder: str,
    timestamp: str,
    aggregated_eval_file: str
) -> List[Dict[str, Any]]:
    """
    Prepare session info for per-conversation mode.
    Groups files by conversationID and creates temp JSONL files for each conversation.
    
    Returns:
        List of session_info dicts for each conversation
    """
    # Group files by conversationID
    conversation_groups = []
    sorted_files = sorted(file_list, key=lambda x: x.get('conversation_id', 'default'))
    for conversation_id, group in groupby(sorted_files, key=lambda x: x.get('conversation_id', 'default')):
        conversation_groups.append((conversation_id, list(group)))
    
    sessions = []
    for conv_idx, (conversation_id, conv_files) in enumerate(conversation_groups, start=1):
        # Create temp JSONL file for this conversation
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
        
        sessions.append({
            'session_id': timestamp,
            'suffix': f"conv-{conversation_id}",
            'temp_file_path': temp_list_path,
            'conversation_id': conversation_id,
            'num_files': len(conv_files),
            'aggregated_eval_file': aggregated_eval_file
        })
    
    return sessions


def prepare_file_sessions(
    file_list: List[Dict[str, Any]],
    temp_folder: str,
    timestamp: str,
    aggregated_eval_file: str
) -> List[Dict[str, Any]]:
    """
    Prepare session info for per-file mode.
    Creates a temp JSONL file for each audio file.
    
    Returns:
        List of session_info dicts for each file
    """
    sessions = []
    for idx, file_record in enumerate(file_list, start=1):
        # Create temp JSONL file for this single file
        temp_list_path = os.path.join(temp_folder, f"temp_single_file_{idx}.jsonl")
        with open(temp_list_path, 'w', encoding='utf-8') as tf:
            json.dump({
                'WavPath': file_record['audio_path'],
                'Answer': file_record.get('ground_truth'),
                'Question': file_record.get('question'),
                'tool_definitions': file_record.get('tool_definitions', []),
                'system_prompt': file_record.get('system_prompt')
            }, tf)
            tf.write('\n')
        
        sessions.append({
            'session_id': timestamp,
            'suffix': f"session-{idx}",
            'temp_file_path': temp_list_path,
            'audio_path': file_record['audio_path'],
            'num_files': 1,
            'aggregated_eval_file': aggregated_eval_file
        })
    
    return sessions


def aggregate_evaluation_files(
    session_results: List[Dict[str, Any]],
    output_dir: str,
    timestamp: str,
    dataset_name: str,
    aggregated_eval_file: str
) -> Optional[str]:
    """
    Verify the aggregated evaluation file exists and has content.
    In multi-session modes, each subprocess writes directly to the aggregated file.
    
    Returns:
        Path to the aggregated evaluation file, or None if not found/empty
    """
    if not aggregated_eval_file:
        # For single mode, look for the session's evaluation file
        session_dir = os.path.join(output_dir, timestamp)
        if os.path.exists(session_dir):
            for f in os.listdir(session_dir):
                if f.endswith('.jsonl'):
                    return os.path.join(session_dir, f)
        return None
    
    if os.path.exists(aggregated_eval_file):
        # Check if file has content
        with open(aggregated_eval_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if content:
                line_count = len([l for l in content.split('\n') if l.strip()])
                log_message(f"Aggregated evaluation file has {line_count} entries: {aggregated_eval_file}")
                return aggregated_eval_file
    
    log_message("No evaluation data found in aggregated file", level="warning")
    return None


def run_final_evaluation(
    aggregated_eval_file: str,
    output_dir: str,
    timestamp: str,
    eval_object_id: Optional[str] = None
):
    """
    Run the final evaluation on the aggregated JSONL file.
    """
    if not aggregated_eval_file or not os.path.exists(aggregated_eval_file):
        log_message("No aggregated evaluation file found, skipping final evaluation", level="warning")
        return
    
    try:
        # Import the evaluation module
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        import voice_agent_evaluation
        
        eval_name = os.path.basename(aggregated_eval_file)
        eval_description = f"Voice Live API Batch: {datetime.now().strftime('%Y%m%d_%H%M%S')}"
        timestamp_root = os.path.join(output_dir, timestamp)
        
        log_message(f"Running final evaluation on: {aggregated_eval_file}")
        
        voice_agent_evaluation.main(
            aggregated_eval_file,
            referenceTranscriptFilePath="",
            output_folder=timestamp_root,
            eval_group_name=eval_description,
            eval_object_id=eval_object_id or "",
            eval_run_name=eval_name,
            eval_run_scenario=eval_name,
            dataset_id="",
            dataset_appendix="",
            setupCustomEvaluators=False
        )
        
        log_message(f"Evaluation completed! Results in: {timestamp_root}")
    except ImportError as e:
        log_message(f"Error importing evaluation module: {e}", level="error")
    except Exception as e:
        log_message(f"Error during evaluation: {e}", level="error")


def get_dataset_files(input_path: str, extensions: List[str] = None) -> List[str]:
    """
    Get dataset files from a folder or return the single file.
    
    Args:
        input_path: Path to a file or folder
        extensions: List of valid extensions (default: ['jsonl', 'txt'])
    
    Returns:
        List of dataset file paths
    """
    if extensions is None:
        extensions = ['jsonl', 'txt']
    
    input_path = Path(input_path)
    
    if input_path.is_file():
        return [str(input_path)]
    
    if input_path.is_dir():
        files = []
        for ext in extensions:
            files.extend(input_path.glob(f"*.{ext}"))
        return [str(f) for f in sorted(files)]
    
    raise FileNotFoundError(f"Input path not found: {input_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch processor for Voice Agent Audio Input Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single dataset with parallel conversation sessions
  python batch_processor.py --test-files dataset.jsonl --session-mode per-conversation --max-workers 4
  
  # Process all JSONL files in a folder
  python batch_processor.py --test-files-folder ./datasets --session-mode per-file --max-workers 2
  
  # Process a dataset in single session mode (no parallelism)
  python batch_processor.py --test-files dataset.jsonl --session-mode single
        """
    )
    
    # Input options (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--test-files', '-f',
        dest='test_files_path',
        help='Path to a single JSONL file containing audio file records'
    )
    input_group.add_argument(
        '--test-files-folder',
        dest='test_files_folder',
        help='Path to a folder containing multiple JSONL dataset files'
    )
    
    parser.add_argument(
        '--session-mode',
        dest='session_mode',
        choices=['single', 'per-file', 'per-conversation'],
        default='per-conversation',
        help='Session handling mode: single (all files in one session), per-file (each file in its own session), or per-conversation (new session per conversationID)'
    )
    
    parser.add_argument(
        '--max-workers',
        type=int,
        default=1,
        help='Maximum number of parallel session processes (default: 1). Note: single mode always runs with 1 worker.'
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        dest='output_dir',
        default='./output',
        help='Directory to store response audio files and evaluation results'
    )
    
    parser.add_argument(
        '--evaluation', '-e',
        dest='evaluation_dir',
        default='./output',
        help='Directory to store JSONL evaluation data'
    )
    
    parser.add_argument(
        '--eval-object-id',
        dest='eval_object_id',
        default=None,
        help='Optional evaluation object ID for Azure AI Evaluation SDK'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=600,
        help='Timeout in seconds for each session subprocess (default: 600)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show sessions that would be processed without actually running them'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output from session subprocesses'
    )
    
    parser.add_argument(
        '--skip-evaluation',
        action='store_true',
        help='Skip the final evaluation step'
    )
    
    args = parser.parse_args()
    
    # Set up directories
    script_dir = Path(__file__).parent
    os.chdir(str(script_dir))
    
    # Create logs directory
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Set up logging
    log_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = f'logs/{log_timestamp}_batch_processor.log'
    setup_logging(log_file, args.verbose)
    
    log_message(f"Batch Processor v3 started at {log_timestamp}")
    log_message(f"Log file: {log_file}")
    
    # Convert relative paths to absolute
    if args.test_files_path and not os.path.isabs(args.test_files_path):
        args.test_files_path = os.path.abspath(args.test_files_path)
    if args.test_files_folder and not os.path.isabs(args.test_files_folder):
        args.test_files_folder = os.path.abspath(args.test_files_folder)
    if args.output_dir and not os.path.isabs(args.output_dir):
        args.output_dir = os.path.abspath(args.output_dir)
    if args.evaluation_dir and not os.path.isabs(args.evaluation_dir):
        args.evaluation_dir = os.path.abspath(args.evaluation_dir)
    
    # Get dataset files
    try:
        if args.test_files_path:
            dataset_files = [args.test_files_path]
        else:
            dataset_files = get_dataset_files(args.test_files_folder)
        
        if not dataset_files:
            log_message("No dataset files found to process", level="error")
            return
        
        log_message(f"Found {len(dataset_files)} dataset file(s) to process")
        for df in dataset_files:
            log_message(f"  - {df}")
    except FileNotFoundError as e:
        log_message(str(e), level="error")
        return
    
    # Process each dataset
    for dataset_idx, dataset_file in enumerate(dataset_files, start=1):
        log_message(f"\n{'='*60}")
        log_message(f"Processing dataset {dataset_idx}/{len(dataset_files)}: {dataset_file}")
        log_message(f"{'='*60}")
        
        try:
            # Read the dataset
            file_list = read_test_files(dataset_file)
            if not file_list:
                log_message(f"No audio files found in {dataset_file}", level="warning")
                continue
            
            log_message(f"Found {len(file_list)} audio files in dataset")
            
            # Generate timestamp for this batch run
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dataset_name = os.path.splitext(os.path.basename(dataset_file))[0]
            
            # Create output directories
            batch_output_dir = os.path.join(args.output_dir, timestamp)
            os.makedirs(batch_output_dir, exist_ok=True)
            
            # Create temp folder for session files
            temp_folder = os.path.join(batch_output_dir, "temp")
            os.makedirs(temp_folder, exist_ok=True)
            
            # Create aggregated evaluation file path for multi-session modes
            aggregated_eval_file = os.path.join(batch_output_dir, f"{timestamp}_aggregate_{dataset_name}.jsonl")
            
            # Prepare sessions based on mode
            if args.session_mode == 'single':
                log_message("Running in SINGLE session mode (all files in one session)")
                # Single mode - create one session with all files
                sessions = [{
                    'session_id': timestamp,
                    'suffix': '',
                    'temp_file_path': dataset_file,  # Use original file
                    'num_files': len(file_list),
                    'aggregated_eval_file': None  # Single mode doesn't need aggregation
                }]
                effective_workers = 1  # Force single worker
            elif args.session_mode == 'per-conversation':
                log_message("Running in PER-CONVERSATION session mode")
                sessions = prepare_conversation_sessions(file_list, temp_folder, timestamp, aggregated_eval_file)
                effective_workers = min(args.max_workers, len(sessions))
            else:  # per-file
                log_message("Running in PER-FILE session mode")
                sessions = prepare_file_sessions(file_list, temp_folder, timestamp, aggregated_eval_file)
                effective_workers = min(args.max_workers, len(sessions))
            
            log_message(f"Prepared {len(sessions)} session(s)")
            log_message(f"Using {effective_workers} worker(s)")
            
            if args.dry_run:
                log_message("\nDry run - Sessions that would be processed:")
                for session in sessions:
                    log_message(f"  - {session['suffix'] or 'main'}: {session['num_files']} file(s)")
                continue
            
            # Base arguments for all sessions
            base_args = {
                'output_dir': batch_output_dir,
                'evaluation_dir': batch_output_dir,
                'eval_object_id': args.eval_object_id
            }
            
            # Process sessions
            failed_sessions = []
            session_results = []
            
            if effective_workers == 1:
                # Sequential processing
                for session in sessions:
                    session_id, return_code, stdout, stderr = run_session_subprocess(
                        session, base_args, args.verbose, args.timeout
                    )
                    session_results.append({
                        'session_id': session_id,
                        'suffix': session.get('suffix', ''),
                        'return_code': return_code
                    })
                    if return_code != 0:
                        failed_sessions.append((session.get('suffix', session_id), stderr))
            else:
                # Parallel processing
                with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
                    futures = {
                        executor.submit(
                            run_session_subprocess,
                            session, base_args, args.verbose, args.timeout
                        ): session for session in sessions
                    }
                    
                    for future in concurrent.futures.as_completed(futures):
                        session = futures[future]
                        try:
                            session_id, return_code, stdout, stderr = future.result()
                            session_results.append({
                                'session_id': session_id,
                                'suffix': session.get('suffix', ''),
                                'return_code': return_code
                            })
                            if return_code != 0:
                                failed_sessions.append((session.get('suffix', session_id), stderr))
                        except Exception as e:
                            failed_sessions.append((session.get('suffix', 'unknown'), str(e)))
            
            # Cleanup temp folder
            log_message("Cleaning up temp files...")
            try:
                shutil.rmtree(temp_folder)
            except OSError as e:
                log_message(f"Warning: Could not remove temp folder: {e}", level="warning")
            
            # Summary
            successful_count = len(sessions) - len(failed_sessions)
            log_message(f"\n{'-'*40}")
            log_message(f"Session processing complete for: {dataset_name}")
            log_message(f"Successfully completed: {successful_count}/{len(sessions)} sessions")
            
            if failed_sessions:
                log_message("Failed sessions:", level="error")
                for suffix, error in failed_sessions:
                    log_message(f"  - {suffix}: {error[:100]}", level="error")
            
            # Aggregate evaluation files and run final evaluation
            if not args.skip_evaluation and successful_count > 0:
                # Get the aggregated eval file path (None for single mode)
                agg_file = aggregated_eval_file if args.session_mode != 'single' else None
                verified_eval_file = aggregate_evaluation_files(
                    session_results, args.output_dir, timestamp, dataset_name, agg_file
                )
                if verified_eval_file:
                    run_final_evaluation(
                        verified_eval_file, args.output_dir, timestamp, args.eval_object_id
                    )
            
            log_message(f"Output saved to: {batch_output_dir}")
            
        except KeyboardInterrupt:
            log_message("\nBatch processing interrupted by user", level="warning")
            sys.exit(1)
        except Exception as e:
            log_message(f"Error processing dataset {dataset_file}: {e}", level="error")
            continue
    
    log_message(f"\n{'='*60}")
    log_message("Batch processing complete!")
    log_message(f"{'='*60}")


if __name__ == "__main__":
    main()
