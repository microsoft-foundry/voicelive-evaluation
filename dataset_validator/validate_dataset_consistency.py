"""
Dataset Consistency Validator

PURPOSE:
    Pre-evaluation validation of JSONL datasets to ensure structural integrity
    and completeness. Run this FIRST before quality validation or evaluation.
    
    Use this validator to catch:
    - Malformed JSON syntax
    - Missing required fields
    - Broken file references
    - Structural inconsistencies
    
WHEN TO USE:
    - After creating or modifying a dataset
    - Before running voice agent evaluations
    - As a gate check in CI/CD pipelines
    - To verify dataset consistency after data transformation

VALIDATION CHECKS:
    1. JSONL syntax correctness (valid JSON per line)
    2. Required field completeness (WavPath, Question, Answer, conversationID, system_prompt)
    3. Audio file presence (all referenced WAV files exist)
    4. Conversation structure (turn distribution/validation, system_prompt consistency)

COMMAND LINE USAGE:
    # Basic validation with turn distribution analysis
    python validate_dataset_consistency.py dataset.jsonl
    
    # Validate specific turn count (e.g., enforce 3-turn conversations)
    python validate_dataset_consistency.py dataset.jsonl --expected-turns 3
    
    # Handle datasets with comment lines
    python validate_dataset_consistency.py dataset.jsonl --ignore-comments
    
    # Pass folder path (auto-detects .jsonl file)
    python validate_dataset_consistency.py ./datasets/wave1/

PROGRAMMATIC USAGE:
    from validate_dataset_consistency import DatasetConsistencyValidator
    
    # Basic validation
    validator = DatasetConsistencyValidator("dataset.jsonl")
    is_valid = validator.validate()  # Returns True if all checks pass
    
    # With options
    validator = DatasetConsistencyValidator(
        "dataset.jsonl",
        ignore_comments=True,
        expected_turns=3
    )
    is_valid = validator.validate()
    
    # Check specific issues
    if not is_valid:
        print("Errors:", validator.errors)
        print("Warnings:", validator.warnings)

EXIT CODES:
    0 - All validation checks passed
    1 - Validation failed or error occurred

PARAMETERS:
    --ignore-comments       Skip lines starting with // or # (non-standard extension)
    --expected-turns N      Validate all conversations have exactly N turns
                           (default: analyze and report turn count distribution)
"""

import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

# Ensure proper UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    try:
        import io
        # Try to reconfigure existing stdout if possible
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        elif hasattr(sys.stdout, 'buffer') and not hasattr(sys.stdout, '_wrapped_for_utf8'):
            # Only wrap if not already wrapped
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
            sys.stdout._wrapped_for_utf8 = True
            sys.stderr._wrapped_for_utf8 = True
    except Exception:
        pass  # Silently fail if UTF-8 setup doesn't work


class DatasetConsistencyValidator:
    """
    Validates structural consistency and completeness of JSONL voice agent datasets.
    
    This validator performs mandatory pre-evaluation checks to ensure datasets
    are properly formatted and complete before running quality validation or
    voice agent evaluations.
    
    Attributes:
        dataset_path (Path): Path to JSONL file or folder containing JSONL
        jsonl_path (Path): Resolved path to the JSONL file
        folder_path (Path): Folder containing the JSONL and audio files
        entries (list): Loaded JSON entries from the JSONL file
        errors (list): Critical errors that prevent evaluation
        warnings (list): Non-blocking issues that should be reviewed
        ignore_comments (bool): Whether to skip comment lines (// or #)
        expected_turns (int|None): Expected turn count per conversation (None = analyze only)
    
    Example:
        >>> validator = DatasetConsistencyValidator("dataset.jsonl")
        >>> if validator.validate():
        ...     print("Dataset ready for evaluation")
        ... else:
        ...     print(f"Errors: {validator.errors}")
    """
    
    def __init__(self, dataset_path: str, ignore_comments: bool = False, expected_turns: int = None):
        """
        Initialize validator with dataset path and options.
        
        Args:
            dataset_path: Path to .jsonl file or folder containing dataset
            ignore_comments: If True, skip lines starting with // or # (default: False)
            expected_turns: Expected turn count per conversation. If None, analyzes
                          and reports distribution without validation (default: None)
        
        Raises:
            ValueError: If path is invalid or multiple JSONL files found in folder
        """
        self.dataset_path = Path(dataset_path)
        self.jsonl_path = None
        self.folder_path = None
        self.errors = []
        self.warnings = []
        self.entries = []
        self.ignore_comments = ignore_comments
        self.expected_turns = expected_turns  # None = analyze distribution, int = validate specific count
        self.skipped_lines = []  # Track comment lines
        
        # Determine if path is file or folder
        if self.dataset_path.is_file() and self.dataset_path.suffix == '.jsonl':
            self.jsonl_path = self.dataset_path
            self.folder_path = self.dataset_path.parent
        elif self.dataset_path.is_dir():
            self.folder_path = self.dataset_path
            # Find JSONL file in folder
            jsonl_files = list(self.folder_path.glob('*.jsonl'))
            if not jsonl_files:
                raise ValueError(f"No JSONL file found in {self.folder_path}")
            if len(jsonl_files) > 1:
                raise ValueError(f"Multiple JSONL files found in {self.folder_path}. Please specify the file.")
            self.jsonl_path = jsonl_files[0]
        else:
            raise ValueError(f"Path must be a .jsonl file or directory: {dataset_path}")
    
    def validate(self) -> bool:
        """
        Run all validation checks.
        
        Executes the following checks in order:
        1. JSONL syntax validation
        2. Required fields validation
        3. Audio file presence validation
        4. Conversation structure validation
        
        Returns:
            bool: True if all validation checks pass, False otherwise.
                 Check self.errors and self.warnings for details.
        
        Example:
            >>> validator = DatasetConsistencyValidator("dataset.jsonl")
            >>> if validator.validate():
            ...     # Proceed to quality validation
            ...     pass
        """
        print("=" * 80)
        print(f"  DATASET CONSISTENCY VALIDATION")
        print(f"  Dataset: {self.jsonl_path.name}")
        print(f"  Location: {self.folder_path}")
        print("=" * 80)
        
        # Run validation checks
        syntax_ok = self._validate_jsonl_syntax()
        fields_ok = self._validate_required_fields()
        audio_ok = self._validate_audio_files()
        structure_ok = self._validate_conversation_structure()
        
        # Print summary
        self._print_summary()
        
        return syntax_ok and fields_ok and audio_ok and structure_ok
    
    def _validate_jsonl_syntax(self) -> bool:
        """
        Validate JSONL syntax - each line should be valid JSON.
        
        Returns:
            bool: True if all lines are valid JSON, False if syntax errors found
        """
        print("\n✓ 1. JSONL SYNTAX VALIDATION")
        print("-" * 80)
        
        line_errors = []
        self.entries = []
        
        try:
            with open(self.jsonl_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Skip comment lines if flag is set
                    if self.ignore_comments and (line.startswith('//') or line.startswith('#')):
                        self.skipped_lines.append(f"Line {line_num}: {line[:50]}...")
                        continue
                    
                    try:
                        entry = json.loads(line)
                        self.entries.append(entry)
                    except json.JSONDecodeError as e:
                        line_errors.append(f"Line {line_num}: {str(e)}")
        except Exception as e:
            self.errors.append(f"Failed to read JSONL file: {str(e)}")
            print(f"  ❌ ERROR: {str(e)}")
            return False
        
        if line_errors:
            self.errors.extend(line_errors)
            print(f"  ❌ FAILED: {len(line_errors)} parsing errors")
            for error in line_errors[:5]:  # Show first 5 errors
                print(f"     {error}")
            if len(line_errors) > 5:
                print(f"     ... and {len(line_errors) - 5} more errors")
            return False
        else:
            print(f"  ✅ PASSED: All {len(self.entries)} lines are valid JSON")
            if self.skipped_lines:
                print(f"  ℹ  Skipped {len(self.skipped_lines)} comment lines")
            return True
    
    def _validate_required_fields(self) -> bool:
        """
        Validate that all required fields are present and non-empty.
        
        For legacy format: WavPath, Question, Answer, conversationID, system_prompt
        For media format (input_audio in messages): expected_output replaces Answer,
          Question and system_prompt come from messages array.
        Optional fields: tool_definitions
        
        Returns:
            bool: True if all required fields are valid, False if any are missing/empty
        """
        print("\n✓ 2. REQUIRED FIELDS VALIDATION")
        print("-" * 80)
        
        if not self.entries:
            self.errors.append("No entries loaded")
            print("  ❌ FAILED: No entries to validate")
            return False
        
        # Detect if dataset uses media format
        media_count = sum(1 for e in self.entries if self._has_input_audio(e))
        legacy_count = len(self.entries) - media_count
        
        if media_count > 0:
            print(f"  ℹ  Format: {media_count} media entries, {legacy_count} legacy entries")
        
        all_ok = True
        audio_missing = 0
        
        for idx, entry in enumerate(self.entries, start=1):
            is_media = self._has_input_audio(entry)
            
            # Audio source check: WavPath (legacy) or input_audio (media)
            if not is_media:
                wav = entry.get('WavPath') or entry.get('audio_path') or (entry.get('audio') if isinstance(entry.get('audio'), str) else None)
                if not wav or (isinstance(wav, str) and not wav.strip()):
                    audio_missing += 1
        
        if audio_missing > 0:
            all_ok = False
            status = f"❌ Audio source: {len(self.entries) - audio_missing}/{len(self.entries)} valid ({audio_missing} missing WavPath or input_audio)"
            self.errors.append(status)
        else:
            status = f"✅ Audio source: {len(self.entries)}/{len(self.entries)} valid"
        print(f"  {status}")
        
        # Check metadata fields (adapt to format)
        required_fields = ['Question', 'Answer', 'conversationID', 'system_prompt'] if legacy_count > 0 else []
        field_stats = defaultdict(lambda: {'present': 0, 'empty': 0, 'missing': 0})
        
        for idx, entry in enumerate(self.entries, start=1):
            is_media = self._has_input_audio(entry)
            
            for field in required_fields:
                # Media format uses messages/expected_output instead
                if is_media and field in ('Question', 'Answer', 'system_prompt'):
                    # Check media equivalents
                    if field == 'Answer':
                        val = entry.get('expected_output') or entry.get('Answer')
                    elif field == 'Question':
                        val = self._extract_text_from_messages(entry) or entry.get('Question')
                    elif field == 'system_prompt':
                        val = self._extract_system_prompt(entry) or entry.get('system_prompt')
                    else:
                        val = entry.get(field)
                else:
                    val = entry.get(field)
                
                if val is None:
                    field_stats[field]['missing'] += 1
                elif not val or (isinstance(val, str) and not val.strip()):
                    field_stats[field]['empty'] += 1
                else:
                    field_stats[field]['present'] += 1
        
        for field in required_fields:
            stats = field_stats[field]
            total = len(self.entries)
            
            if stats['missing'] > 0 or stats['empty'] > 0:
                all_ok = False
                issues = []
                if stats['missing'] > 0:
                    issues.append(f"{stats['missing']} missing")
                if stats['empty'] > 0:
                    issues.append(f"{stats['empty']} empty")
                
                status = f"❌ {field}: {stats['present']}/{total} valid ({', '.join(issues)})"
                self.errors.append(status)
            else:
                status = f"✅ {field}: {total}/{total} valid"
            
            print(f"  {status}")
        
        # Check tool_definitions field (optional, just report)
        tool_def_count = sum(1 for e in self.entries if e.get('tool_definitions'))
        print(f"  ℹ  tool_definitions: {tool_def_count}/{len(self.entries)} populated (optional)")
        
        return all_ok
    
    @staticmethod
    def _has_input_audio(entry: dict) -> bool:
        """Check if a JSONL entry contains input_audio media content."""
        for msg in entry.get("messages", []):
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "input_audio":
                            ref = part.get("input_audio", {})
                            if ref.get("data"):
                                return True
        # Also check top-level audio field
        top_audio = entry.get("audio")
        if isinstance(top_audio, dict) and top_audio.get("type") == "input_audio":
            ref = top_audio.get("input_audio", {})
            if ref.get("data"):
                return True
        return False
    
    @staticmethod
    def _extract_text_from_messages(entry: dict) -> str:
        """Extract user text from messages array."""
        for msg in entry.get("messages", []):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text"]
                return " ".join(t for t in texts if t)
        return ""
    
    @staticmethod
    def _extract_system_prompt(entry: dict) -> str:
        """Extract system prompt from messages array."""
        for msg in entry.get("messages", []):
            if msg.get("role") == "system":
                c = msg.get("content", "")
                return c if isinstance(c, str) else str(c)
        return ""
    
    def _validate_audio_files(self) -> bool:
        """
        Validate that all referenced audio files exist in the dataset folder.
        Media entries (input_audio) are validated for non-empty data instead.
        Also checks for unreferenced audio files (warning only).
        
        Returns:
            bool: True if all referenced WAV files exist, False if any are missing
        """
        print("\n✓ 3. AUDIO FILES VALIDATION")
        print("-" * 80)
        
        if not self.entries:
            print("  ⚠  SKIPPED: No entries to validate")
            return True
        
        missing_files = []
        referenced_files = set()
        media_valid = 0
        for entry in self.entries:
            if self._has_input_audio(entry):
                # Media entry — validate data is non-empty (already checked in _has_input_audio)
                media_valid += 1
                continue
            
            wav_path = entry.get('WavPath')
            if wav_path:
                referenced_files.add(wav_path)
                full_path = self.folder_path / wav_path
                if not full_path.exists():
                    missing_files.append(wav_path)
        
        # Count actual WAV files in folder
        actual_wav_files = list(self.folder_path.glob('*.wav'))
        
        if media_valid > 0:
            print(f"  Media entries (input_audio): {media_valid} valid")
        print(f"  Referenced in JSONL: {len(referenced_files)} files")
        print(f"  WAV files in folder: {len(actual_wav_files)} files")
        
        # Check for unreferenced audio files (non-response files) BEFORE returning
        referenced_names = set(referenced_files)
        unreferenced_files = []
        
        for wav_file in actual_wav_files:
            # Skip response files (these are expected to be unreferenced)
            if 'response' in wav_file.name.lower():
                continue
            
            # Check if this file is referenced in JSONL
            if wav_file.name not in referenced_names:
                unreferenced_files.append(wav_file.name)
        
        # Now report both missing and unreferenced files
        has_errors = False
        
        if missing_files:
            self.errors.append(f"{len(missing_files)} audio files missing")
            print(f"  ❌ FAILED: {len(missing_files)} missing files")
            for file in missing_files[:10]:
                print(f"     - {file}")
            if len(missing_files) > 10:
                print(f"     ... and {len(missing_files) - 10} more")
            has_errors = True
        else:
            print(f"  ✅ PASSED: All {len(referenced_files)} referenced files exist")
        
        # Report unreferenced files as warning (even if there are missing files)
        if unreferenced_files:
            self.warnings.append(f"{len(unreferenced_files)} audio files in folder not referenced in JSONL")
            print(f"  ⚠  WARNING: {len(unreferenced_files)} unreferenced files found")
            for file in unreferenced_files[:10]:
                print(f"     - {file}")
            if len(unreferenced_files) > 10:
                print(f"     ... and {len(unreferenced_files) - 10} more")
            print(f"     (These files exist in folder but are not in JSONL)")
        
        # Report on response files if present
        response_files = [f for f in actual_wav_files if 'response' in f.name.lower()]
        if response_files:
            print(f"  ℹ  Additional response files: {len(response_files)}")
        
        return not has_errors
    
    def _validate_conversation_structure(self) -> bool:
        """
        Validate conversation grouping, turn counts, and system_prompt consistency.
        
        Checks:
        - Turn count distribution (or validates against expected_turns if set)
        - system_prompt consistency within each conversation
        
        Returns:
            bool: True if structure is valid, False if critical issues found
        """
        print("\n✓ 4. CONVERSATION STRUCTURE VALIDATION")
        print("-" * 80)
        
        if not self.entries:
            print("  ⚠  SKIPPED: No entries to validate")
            return True
        
        # Group by conversationID
        conversations = defaultdict(list)
        for entry in self.entries:
            conv_id = entry.get('conversationID', 'unknown')
            conversations[conv_id].append(entry)
        
        print(f"  Total conversations: {len(conversations)}")
        print(f"  Total entries: {len(self.entries)}")
        
        # Analyze turn counts
        turn_counts = {}
        turn_distribution = defaultdict(int)
        
        for conv_id, entries in conversations.items():
            turn_count = len(entries)
            turn_counts[conv_id] = turn_count
            turn_distribution[turn_count] += 1
        
        # If expected_turns is set, validate against that specific value
        if self.expected_turns is not None:
            inconsistent_turns = []
            for conv_id, count in turn_counts.items():
                if count != self.expected_turns:
                    inconsistent_turns.append((conv_id, count))
            
            if inconsistent_turns:
                self.warnings.append(f"{len(inconsistent_turns)} conversations don't have expected {self.expected_turns} turns")
                print(f"  ⚠  WARNING: {len(inconsistent_turns)} conversations don't have exactly {self.expected_turns} turns")
                for conv_id, count in inconsistent_turns[:5]:
                    print(f"     - {conv_id}: {count} turns (expected {self.expected_turns})")
                if len(inconsistent_turns) > 5:
                    print(f"     ... and {len(inconsistent_turns) - 5} more")
            else:
                print(f"  ✅ PASSED: All conversations have exactly {self.expected_turns} turns")
        else:
            # Default behavior: Show turn distribution
            print(f"\n  Turn Count Distribution:")
            for turn_count in sorted(turn_distribution.keys()):
                conv_count = turn_distribution[turn_count]
                percentage = (conv_count / len(conversations)) * 100
                print(f"    • {turn_count} turns: {conv_count} conversations ({percentage:.1f}%)")
            
            # Check if all conversations have the same turn count
            if len(turn_distribution) == 1:
                single_turn_count = list(turn_distribution.keys())[0]
                print(f"  ✅ CONSISTENT: All conversations have {single_turn_count} turns")
            else:
                print(f"  ℹ  INFO: Dataset has variable turn counts across {len(turn_distribution)} different patterns")
                print(f"     (Use --expected-turns flag to validate specific turn count)")
        
        # Check system_prompt consistency within conversations
        inconsistent_prompts = []
        for conv_id, entries in conversations.items():
            prompts = set(e.get('system_prompt', '') for e in entries)
            if len(prompts) > 1:
                inconsistent_prompts.append(conv_id)
        
        if inconsistent_prompts:
            self.errors.append(f"{len(inconsistent_prompts)} conversations have inconsistent system_prompts")
            print(f"  ❌ FAILED: {len(inconsistent_prompts)} conversations have inconsistent system_prompts")
            for conv_id in inconsistent_prompts[:5]:
                print(f"     - {conv_id}")
            if len(inconsistent_prompts) > 5:
                print(f"     ... and {len(inconsistent_prompts) - 5} more")
            return False
        else:
            print(f"  ✅ PASSED: All conversations have consistent system_prompts")
        
        return True
    
    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print("  VALIDATION SUMMARY")
        print("=" * 80)
        
        total_checks = 4
        failed_checks = len([e for e in self.errors if 'FAILED' in str(e)])
        passed_checks = total_checks - failed_checks
        
        if not self.errors:
            print("\n  🎯 STATUS: ✅ ALL CHECKS PASSED")
            print(f"\n  Dataset is consistent and ready for evaluation.")
        else:
            print(f"\n  🎯 STATUS: ❌ VALIDATION FAILED")
            print(f"\n  Passed: {passed_checks}/{total_checks} checks")
            print(f"  Failed: {failed_checks} checks")
            print(f"\n  ❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"     - {error}")
        
        if self.warnings:
            print(f"\n  ⚠  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"     - {warning}")
        
        print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Validate JSONL dataset consistency',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate_dataset_consistency.py dataset.jsonl
  python validate_dataset_consistency.py dataset.jsonl --expected-turns 3
  python validate_dataset_consistency.py dataset.jsonl --ignore-comments
  python validate_dataset_consistency.py ./datasets/wave1/
        """
    )
    
    parser.add_argument('dataset_path', help='Path to JSONL file or dataset folder')
    parser.add_argument('--ignore-comments', action='store_true',
                       help='Skip lines starting with // or # (non-standard JSONL extension)')
    parser.add_argument('--expected-turns', type=int, metavar='N',
                       help='Validate that all conversations have exactly N turns (default: analyze distribution)')
    
    args = parser.parse_args()
    
    try:
        validator = DatasetConsistencyValidator(args.dataset_path, 
                                               ignore_comments=args.ignore_comments,
                                               expected_turns=args.expected_turns)
        success = validator.validate()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ VALIDATION ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
