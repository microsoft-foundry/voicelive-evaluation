# Dataset Consistency Validator Skill

## Overview
Validates JSONL voice agent datasets for structural integrity and completeness. This is a **MANDATORY** pre-evaluation check.

**Version:** 1.0.0  
**Language:** Python  
**Type:** Validation / Pre-processing

## Purpose

Ensures datasets are structurally sound before running:
- Quality validation
- Voice agent evaluations
- Data processing pipelines

## When to Use

✅ **ALWAYS use before:**
- Running voice agent evaluations
- Quality validation
- Dataset processing

✅ **Use when:**
- Creating new datasets
- Modifying existing datasets
- Dataset source is untrusted
- Setting up CI/CD pipelines

## What It Validates

1. **JSONL Syntax** ❌ CRITICAL
   - Each line must be valid JSON
   
2. **Required Fields** ❌ CRITICAL
   - WavPath, Question, Answer, conversationID, system_prompt
   
3. **Audio Files** ❌ CRITICAL
   - All referenced WAV files must exist
   
4. **Unreferenced Files** ⚠️ WARNING
   - Files in folder not in JSONL
   
5. **Conversation Structure** ❌ CRITICAL
   - system_prompt consistent within conversations
   - Turn count analysis/validation

## Usage

### Command Line

```bash
# Basic validation (shows turn distribution)
python validate_dataset_consistency.py dataset.jsonl

# Enforce specific turn count
python validate_dataset_consistency.py dataset.jsonl --expected-turns 3

# Handle comment lines
python validate_dataset_consistency.py dataset.jsonl --ignore-comments

# Pass folder path
python validate_dataset_consistency.py ./datasets/wave1/
```

### Programmatic (Python)

```python
from dataset_validator.validate_dataset_consistency import DatasetConsistencyValidator

# Basic usage
validator = DatasetConsistencyValidator("dataset.jsonl")
if validator.validate():
    print("Dataset ready for evaluation")
    proceed_to_quality_validation()
else:
    print(f"Errors: {validator.errors}")
    print(f"Warnings: {validator.warnings}")
    
# With options
validator = DatasetConsistencyValidator(
    "dataset.jsonl",
    ignore_comments=True,
    expected_turns=3
)
success = validator.validate()
```

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset_path` | string | Yes | - | Path to JSONL file or folder |
| `--ignore-comments` | flag | No | false | Skip // or # lines |
| `--expected-turns` | integer | No | null | Validate specific turn count |

## Returns

**Exit Code:**
- `0` - All checks passed ✅
- `1` - Validation failed ❌

**Attributes:**
- `validator.errors` - List of critical issues
- `validator.warnings` - List of non-blocking concerns

## Integration Modes

### 1. Dynamic Discovery (Skill-Based)

**For:** Autonomous agents that decide when to validate

```yaml
Agent discovers:
  - when_to_use: "BEFORE running voice agent evaluations"
  - description: What the validator does
  - parameters: Available options

Agent decides:
  - "User mentioned dataset evaluation"
  - "I should validate first"
  - Calls skill with appropriate parameters
```

**Best for:**
- Foundry Agents with dynamic workflows
- Multi-agent systems
- Context-aware validation

### 2. Programmatic (Hard-Coded)

**For:** Fixed validation pipelines

```python
def evaluation_workflow(dataset_path):
    # Step 1: ALWAYS validate consistency
    validator = DatasetConsistencyValidator(dataset_path)
    if not validator.validate():
        raise ValueError(f"Dataset invalid: {validator.errors}")
    
    # Step 2: Proceed to quality
    ...
```

**Best for:**
- CI/CD pipelines
- Automated testing
- Guaranteed validation workflows

## Output Example

```
================================================================================
  DATASET CONSISTENCY VALIDATION
  Dataset: dataset.jsonl
================================================================================

✓ 1. JSONL SYNTAX VALIDATION
  ✅ PASSED: All 150 lines are valid JSON

✓ 2. REQUIRED FIELDS VALIDATION
  ✅ WavPath: 150/150 valid
  ✅ Question: 150/150 valid
  ✅ Answer: 150/150 valid
  ✅ conversationID: 150/150 valid
  ✅ system_prompt: 150/150 valid

✓ 3. AUDIO FILES VALIDATION
  ✅ PASSED: All 150 referenced files exist
  ⚠  WARNING: 1 unreferenced files found
     - extra_file.wav

✓ 4. CONVERSATION STRUCTURE VALIDATION
  Turn Count Distribution:
    • 3 turns: 50 conversations (100.0%)
  ✅ CONSISTENT: All conversations have 3 turns
  ✅ PASSED: All conversations have consistent system_prompts

  🎯 STATUS: ✅ ALL CHECKS PASSED
```

## Decision Guide

**Use this skill when:**
- ✅ Agent needs to decide if validation is needed
- ✅ Multiple agents share validation service
- ✅ Workflow is dynamic and context-dependent

**Use direct Python import when:**
- ✅ Validation is always required (mandatory gate)
- ✅ Fixed CI/CD pipeline
- ✅ Single-purpose script/workflow

## Related Skills

- **validate-dataset-quality** - Run AFTER this passes
- Quality validation is ADVISORY, this is MANDATORY

## Documentation

See `../../DATASET_VALIDATION_README.md` for complete documentation.

## Tags

`validation` `dataset` `voice-agent` `pre-evaluation` `data-quality` `mandatory`
