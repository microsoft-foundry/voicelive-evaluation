# Dataset Quality Validator Skill

## Overview
Validates content quality and appropriateness of JSONL voice agent datasets. This is an **ADVISORY** quality check.

**Version:** 1.0.0  
**Language:** Python  
**Type:** Quality Assessment / Advisory

## Purpose

Assesses dataset quality to guide improvements:
- System prompt alignment with conversations
- Tool definition appropriateness
- Content quality metrics
- Question intent classification

**Note:** This is advisory - results don't block evaluation, but guide quality improvements.

## When to Use

✅ **AFTER consistency validation passes**

✅ **Use when:**
- Assessing dataset quality before evaluation
- Reviewing prompt-conversation alignment
- Validating tool definitions match question types
- Quality assurance in dataset creation
- Analyzing existing datasets for improvements

## What It Assesses

1. **System Prompt Relevance** 📊 ADVISORY
   - Domain detection and keyword matching
   - Alignment percentage (default or strict mode)
   - ≥70%: Good | 50-70%: Moderate | <50%: Low
   
2. **Tool Definition Appropriateness** 📊 ADVISORY
   - Action requests vs conversational queries
   - Tool presence validation
   - Assessments: correct | needs_review | good | mixed
   
3. **Question Intent Classification** 📊 ADVISORY
   - Action requests (need tools)
   - Instructional questions (how-to)
   - General conversation
   
4. **Content Quality Metrics** 📊 ADVISORY
   - Question/answer length
   - System prompt diversity
   - Score: 0-3

## Usage

### Command Line

```bash
# Basic quality validation (permissive ~88%)
python validate_dataset_quality.py dataset.jsonl

# Strict mode - conservative keyword matching (~50%)
python validate_dataset_quality.py dataset.jsonl --strict

# Verbose mode - detailed per-conversation analysis
python validate_dataset_quality.py dataset.jsonl --verbose

# JSON export for programmatic processing
python validate_dataset_quality.py dataset.jsonl --json results.json

# Combine flags
python validate_dataset_quality.py dataset.jsonl --strict --verbose --json output.json
```

### Programmatic (Python)

```python
from dataset_validator.validate_dataset_quality import DatasetQualityValidator

# Basic usage
validator = DatasetQualityValidator("dataset.jsonl")
results = validator.validate()

if results['status'] == 'success':
    print(f"Alignment: {results['prompt_alignment']:.1f}%")
    print(f"Quality Score: {results['content_quality']}/3")
    
    # Make decision based on results
    if results['prompt_alignment'] >= 70:
        proceed_to_evaluation()
    else:
        review_prompts()

# With options
validator = DatasetQualityValidator(
    "dataset.jsonl",
    strict=True,        # Conservative alignment
    verbose=True,       # Detailed output
    ignore_comments=True
)
results = validator.validate()
```

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset_path` | string | Yes | - | Path to JSONL file or folder |
| `--strict` | flag | No | false | Conservative keyword-only matching (~50%) |
| `--verbose` | flag | No | false | Detailed per-conversation analysis |
| `--json` | string | No | null | Export results to JSON file |
| `--ignore-comments` | flag | No | false | Skip // or # lines |

## Returns

**Exit Code:**
- `0` - Quality validation completed ✅
- `1` - Validation failed or error ❌

**Results Object:**
```python
{
    'status': 'success',
    'prompt_alignment': 88.0,      # Percentage
    'aligned_count': 44,
    'unaligned_count': 6,
    'domains': {                    # Domain breakdown
        'Smart Home': 10,
        'EV Support': 12,
        ...
    },
    'tool_assessment': 'correct',   # correct|needs_review|good|mixed
    'action_requests': 0,
    'content_quality': 3,           # 0-3 score
    'total_conversations': 50,
    'total_entries': 150
}
```

## Alignment Modes

### Default Mode (~88%)
**Permissive matching with generic support patterns**

```bash
python validate_dataset_quality.py dataset.jsonl
```

- Includes generic support phrases
- Detects quality responses across domains
- Use for: General quality assessment

### Strict Mode (~50%)
**Conservative keyword-only matching**

```bash
python validate_dataset_quality.py dataset.jsonl --strict
```

- Requires domain-specific vocabulary
- No generic patterns
- Use for: Validating domain expertise

## Integration Modes

### 1. Dynamic Discovery (Skill-Based)

**For:** Agents that decide when/how to assess quality

```yaml
Agent discovers:
  - when_to_use: "AFTER consistency validation passes"
  - alignment_modes: default vs strict
  - parameters: Available options

Agent decides:
  - "Consistency passed"
  - "Should I assess quality?"
  - "Which mode: default or strict?"
  - Calls skill with chosen parameters
```

**Best for:**
- Autonomous agents
- Context-aware quality assessment
- Flexible QA workflows

### 2. Programmatic (Hard-Coded)

**For:** Fixed quality gates in pipelines

```python
def evaluation_workflow(dataset_path):
    # Step 1: Consistency (mandatory)
    consistency = DatasetConsistencyValidator(dataset_path)
    if not consistency.validate():
        raise ValueError("Dataset invalid")
    
    # Step 2: Quality (advisory)
    quality = DatasetQualityValidator(dataset_path, strict=True)
    results = quality.validate()
    
    # Step 3: Decision based on quality
    if results['prompt_alignment'] < 50:
        log_warning("Low alignment - review recommended")
    
    # Proceed anyway (quality is advisory)
    run_evaluation(dataset_path)
```

**Best for:**
- Fixed QA pipelines
- Automated quality reporting
- CI/CD quality gates

## Output Example

```
================================================================================
  DATASET QUALITY VALIDATION
  Dataset: dataset.jsonl
================================================================================

✓ 1. SYSTEM PROMPT RELEVANCE
  ✅ Aligned: 44/50 (88.0%)
  Domain Breakdown:
    • Smart Home: 10 conversations (90% aligned)
    • EV Support: 12 conversations (100% aligned)
  ✅ GOOD: 88.0% alignment indicates strong matching

✓ 2. TOOL DEFINITION APPROPRIATENESS
  ✅ CORRECT: No action requests detected.
     NULL tool_definitions is appropriate.

✓ 3. CONTENT QUALITY METRICS
  Average Question length: 90 characters
  Average Answer length: 542 characters
  ✅ GOOD: Content has good depth and diversity

  📊 Key Metrics:
    ✅ System Prompt Alignment: 88.0%
    ✅ Tool Definitions: correct
    ✅ Content Quality: 3/3
```

## Decision Guide

**Use this skill when:**
- ✅ Agent should decide if quality assessment needed
- ✅ Agent chooses alignment mode based on context
- ✅ Multiple agents share quality service
- ✅ Workflow adapts to quality results

**Use direct Python import when:**
- ✅ Quality check always performed
- ✅ Fixed QA pipeline
- ✅ Automated quality reporting

## Relationship to Consistency Validator

```
Workflow Order:
1. validate-dataset-consistency (MANDATORY - must pass)
   ↓
2. validate-dataset-quality (ADVISORY - guides improvements)
   ↓
3. Proceed to evaluation (with quality insights)
```

## Related Skills

- **validate-dataset-consistency** - Run this FIRST (mandatory)
- This validator is advisory and doesn't block evaluation

## Documentation

See `../../DATASET_VALIDATION_README.md` for complete documentation.

## Tags

`validation` `dataset` `voice-agent` `quality-assurance` `content-quality` `advisory`
