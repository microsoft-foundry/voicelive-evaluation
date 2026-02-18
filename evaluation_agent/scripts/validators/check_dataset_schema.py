"""
Dataset Schema Checker

PURPOSE:
    Quick pre-validation check to analyze dataset fields and identify what's 
    required vs optional. Use this BEFORE full validation to understand what
    defaults will be applied during evaluation.
    
    Unlike consistency validation (which fails on missing fields), this tool
    distinguishes between:
    - REQUIRED fields (evaluation cannot proceed without these)
    - OPTIONAL fields (evaluation uses defaults if missing)
    
WHEN TO USE:
    - Before running evaluations to understand what defaults will be used
    - When creating new datasets to verify field coverage
    - To quickly check if a dataset needs additional metadata
    - Before full validation to set expectations

FIELD REQUIREMENTS:
    REQUIRED (evaluation fails without):
        - WavPath or audio: Path to audio file
        
    OPTIONAL (uses defaults if missing):
        - Question/question: User query transcript (default: None)
        - Answer/answer: Expected response (default: None, skips ResponseCompleteness)
        - tool_definitions: Available tools (default: [] no tools)
        - conversationID/conversation_id: Conversation grouping (default: 'default')
        - system_prompt: Agent instructions (default: script default prompt)

COMMAND LINE USAGE:
    # Basic schema check
    python check_dataset_schema.py dataset.jsonl
    
    # Check folder (auto-detects JSONL file)
    python check_dataset_schema.py ./datasets/wave1/
    
    # Output as JSON for programmatic use
    python check_dataset_schema.py dataset.jsonl --json

PROGRAMMATIC USAGE:
    from check_dataset_schema import DatasetSchemaChecker
    
    checker = DatasetSchemaChecker("dataset.jsonl")
    result = checker.check()
    
    if result['can_proceed']:
        if result['optional_missing']:
            print("Missing optional fields:", result['optional_missing'])
            # Ask user if they want to proceed with defaults
        else:
            print("All fields present")
    else:
        print("Missing required fields:", result['required_missing'])

EXIT CODES:
    0 - All fields present (required and optional)
    1 - Error (file not found, parse error, missing required fields)
    2 - Can proceed but optional fields missing (warnings)
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure proper UTF-8 encoding for console output on Windows
if sys.platform == 'win32':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


class DatasetSchemaChecker:
    """
    Analyzes JSONL datasets to check for required vs optional fields.
    
    Attributes:
        dataset_path: Path to the JSONL file
        entries: List of parsed JSON entries
        total_entries: Number of entries in dataset
    """
    
    # Required fields - evaluation cannot proceed without these
    REQUIRED_FIELDS = {
        "audio_path": {
            "fields": ["WavPath", "audio"],
            "description": "Path to audio file",
            "critical": True
        }
    }
    
    # Optional fields - evaluation uses defaults if missing
    OPTIONAL_FIELDS = {
        "question": {
            "fields": ["Question", "question"],
            "default": "None (no transcript logged)",
            "description": "User query transcript"
        },
        "answer": {
            "fields": ["Answer", "answer"],
            "default": "None (ResponseCompleteness evaluator skipped)",
            "description": "Expected ground truth response"
        },
        "tool_definitions": {
            "fields": ["tool_definitions"],
            "default": "[] (no tools available)",
            "description": "Tool/function definitions for agent"
        },
        "conversation_id": {
            "fields": ["conversationID", "conversation_id"],
            "default": "'default' (all entries treated as one conversation)",
            "description": "Conversation grouping identifier"
        },
        "system_prompt": {
            "fields": ["system_prompt"],
            "default": "Script default system prompt",
            "description": "Custom agent instructions"
        }
    }
    
    def __init__(self, dataset_path: str):
        """
        Initialize the schema checker.
        
        Args:
            dataset_path: Path to JSONL file or folder containing JSONL
        """
        self.dataset_path = Path(dataset_path)
        self.entries: List[Dict] = []
        self.total_entries: int = 0
        self._resolved_path: Optional[Path] = None
    
    def _resolve_path(self) -> Path:
        """Resolve dataset path, handling folder input."""
        if self._resolved_path:
            return self._resolved_path
            
        path = self.dataset_path
        
        if path.is_dir():
            jsonl_files = list(path.glob("*.jsonl"))
            if jsonl_files:
                path = jsonl_files[0]
            else:
                raise FileNotFoundError(f"No .jsonl file found in folder: {self.dataset_path}")
        
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {path}")
        
        self._resolved_path = path
        return path
    
    def _load_entries(self) -> None:
        """Load and parse JSONL entries."""
        path = self._resolve_path()
        self.entries = []
        
        with open(path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                try:
                    self.entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    # Still count it but note the parse error
                    pass
        
        self.total_entries = len(self.entries)
    
    def check(self) -> Dict[str, Any]:
        """
        Check dataset schema for required and optional fields.
        
        Returns:
            Dictionary with:
                - status: 'passed', 'warnings', 'failed', or 'error'
                - can_proceed: Boolean, True if evaluation can run
                - total_entries: Number of entries checked
                - required_missing: List of missing required fields
                - optional_missing: List of missing optional fields with defaults
                - file: Resolved file path
        """
        try:
            self._load_entries()
        except FileNotFoundError as e:
            return {
                "status": "error",
                "can_proceed": False,
                "error": str(e),
                "file": str(self.dataset_path)
            }
        
        if self.total_entries == 0:
            return {
                "status": "error",
                "can_proceed": False,
                "error": "No valid JSONL entries found",
                "file": str(self._resolved_path)
            }
        
        required_missing = []
        optional_missing = []
        
        # Check required fields
        for field_name, field_info in self.REQUIRED_FIELDS.items():
            count = sum(1 for e in self.entries if any(e.get(f) for f in field_info["fields"]))
            if count < self.total_entries:
                missing = self.total_entries - count
                required_missing.append({
                    "field": field_name,
                    "description": field_info["description"],
                    "present": count,
                    "missing": missing,
                    "total": self.total_entries
                })
        
        # Check optional fields
        for field_name, field_info in self.OPTIONAL_FIELDS.items():
            count = sum(1 for e in self.entries if any(e.get(f) for f in field_info["fields"]))
            if count < self.total_entries:
                missing = self.total_entries - count
                optional_missing.append({
                    "field": field_name,
                    "description": field_info["description"],
                    "present": count,
                    "missing": missing,
                    "total": self.total_entries,
                    "default": field_info["default"]
                })
        
        # Determine status
        can_proceed = len(required_missing) == 0
        has_warnings = len(optional_missing) > 0
        
        if not can_proceed:
            status = "failed"
        elif has_warnings:
            status = "warnings"
        else:
            status = "passed"
        
        return {
            "status": status,
            "can_proceed": can_proceed,
            "has_optional_missing": has_warnings,
            "total_entries": self.total_entries,
            "required_missing": required_missing,
            "optional_missing": optional_missing,
            "file": str(self._resolved_path)
        }
    
    def print_report(self) -> int:
        """
        Print human-readable schema check report.
        
        Returns:
            Exit code (0=passed, 1=failed/error, 2=warnings)
        """
        result = self.check()
        
        print("=" * 60)
        print("DATASET SCHEMA CHECK")
        print("=" * 60)
        print(f"File: {result.get('file', self.dataset_path)}")
        
        if result["status"] == "error":
            print(f"\n❌ ERROR: {result['error']}")
            return 1
        
        print(f"Entries: {result['total_entries']}")
        print()
        
        # Required fields section
        print("REQUIRED FIELDS (evaluation fails without these):")
        print("-" * 40)
        if result["required_missing"]:
            for field in result["required_missing"]:
                print(f"  ❌ {field['field']}: {field['present']}/{field['total']} present")
                print(f"     → {field['description']}")
        else:
            print("  ✅ All required fields present")
        print()
        
        # Optional fields section
        print("OPTIONAL FIELDS (uses defaults if missing):")
        print("-" * 40)
        if result["optional_missing"]:
            for field in result["optional_missing"]:
                print(f"  ⚠  {field['field']}: {field['present']}/{field['total']} present")
                print(f"     → {field['description']}")
                print(f"     → Default: {field['default']}")
        else:
            print("  ✅ All optional fields present")
        print()
        
        # Summary
        print("=" * 60)
        if not result["can_proceed"]:
            print("❌ CANNOT PROCEED: Missing required fields")
            print("   Fix the required fields before running evaluation.")
            return 1
        elif result["has_optional_missing"]:
            print("⚠  CAN PROCEED WITH DEFAULTS")
            print("   Optional fields missing - evaluation will use default values.")
            print("   Consider adding these fields for more accurate evaluation.")
            return 2
        else:
            print("✅ ALL FIELDS PRESENT")
            print("   Dataset is ready for evaluation.")
            return 0


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Check dataset schema for required vs optional fields",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_dataset_schema.py dataset.jsonl
  python check_dataset_schema.py ./datasets/wave1/
  python check_dataset_schema.py dataset.jsonl --json
        """
    )
    
    parser.add_argument(
        "dataset_path",
        help="Path to JSONL file or folder containing JSONL"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable report"
    )
    
    args = parser.parse_args()
    
    checker = DatasetSchemaChecker(args.dataset_path)
    
    if args.json:
        result = checker.check()
        print(json.dumps(result, indent=2))
        if not result["can_proceed"]:
            sys.exit(1)
        elif result.get("has_optional_missing"):
            sys.exit(2)
        else:
            sys.exit(0)
    else:
        exit_code = checker.print_report()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
