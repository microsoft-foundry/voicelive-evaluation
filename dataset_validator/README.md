# Dataset Validation Scripts

Two Python scripts for automated validation of voice agent evaluation datasets in JSONL format.

**Available as:**
- ✅ Command-line tools (CLI)
- ✅ Python modules (programmatic import)
- ✅ Agent Skills (dynamic discovery)

## Scripts Overview

### 1. `validate_dataset_consistency.py`
**Purpose**: Validates basic dataset consistency and completeness

**Checks:**
- ✅ JSONL syntax correctness (valid JSON per line)
- ✅ Required field completeness (WavPath, Question, Answer, conversationID, system_prompt)
- ✅ Audio file presence (all referenced WAV files exist)
- ✅ Conversation structure (turn counts, system_prompt consistency)

### 2. `validate_dataset_quality.py`
**Purpose**: Validates content quality and appropriateness

**Checks:**
- ✅ System prompt relevance to conversation content
- ✅ Tool definition appropriateness (action requests vs. conversational)
- ✅ Question intent classification (action/instructional/general)
- ✅ Content quality metrics (length, diversity, depth)

## Installation

No additional dependencies required beyond Python 3.7+. Uses only standard library modules.

## Usage

### Basic Usage

```bash
# Validate a JSONL file directly
python validate_dataset_consistency.py path/to/dataset.jsonl
python validate_dataset_quality.py path/to/dataset.jsonl

# Validate by folder (auto-detects JSONL file)
python validate_dataset_consistency.py path/to/dataset_folder/
python validate_dataset_quality.py path/to/dataset_folder/
```

### Advanced Options (Quality Validator)

```bash
# Strict mode - conservative keyword-only alignment matching
python validate_dataset_quality.py dataset.jsonl --strict

# Verbose mode - detailed per-conversation breakdown
python validate_dataset_quality.py dataset.jsonl --verbose

# JSON export - save results for programmatic access
python validate_dataset_quality.py dataset.jsonl --json results.json

# Ignore comment lines - handle // or # comments (non-standard)
python validate_dataset_quality.py dataset.jsonl --ignore-comments

# Combine multiple flags
python validate_dataset_quality.py dataset.jsonl --strict --verbose --json output.json
```

**Consistency Validator Options:**

```bash
# Ignore comment lines in JSONL
python validate_dataset_consistency.py dataset.jsonl --ignore-comments

# Validate specific turn count (e.g., all conversations must have 3 turns)
python validate_dataset_consistency.py dataset.jsonl --expected-turns 3

# Combine flags
python validate_dataset_consistency.py dataset.jsonl --ignore-comments --expected-turns 3
```

**Flag Details:**

- `--strict`: Uses keyword-only domain matching (more conservative, ~50% vs default ~88%)
  - Removes generic support pattern detection
  - Requires domain-specific vocabulary in conversations
  - Useful for validating domain expertise

- `--verbose` / `-v`: Shows detailed per-conversation analysis
  - Lists each conversation with alignment status
  - Shows question previews for unaligned conversations
  - Helps identify specific conversations needing review

- `--json <file>`: Exports results to JSON file
  - Structured data for integration with other tools
  - Includes all metrics and domain breakdowns
  - Enables automated processing in CI/CD pipelines

- `--ignore-comments`: Skips lines starting with `//` or `#`
  - **Non-standard JSONL extension** (use with caution)
  - Useful for test datasets with inline documentation
  - Comment lines are silently skipped during processing
  - Validator reports number of skipped lines

- `--expected-turns N`: Validates all conversations have exactly N turns
  - **Default behavior (no flag)**: Analyzes and reports turn count distribution
  - **With flag**: Validates all conversations match the specified turn count
  - Use when dataset requires uniform conversation length
  - Provides warnings for conversations that don't match expected count
  - Example: `--expected-turns 3` ensures all conversations are 3-turn dialogs

### Example with Sample Dataset

```bash
# Consistency validation
python validate_dataset_consistency.py "local_datasets/DataOcean/20260122-wave1-50"

# Quality validation (default mode - permissive)
python validate_dataset_quality.py "local_datasets/DataOcean/20260122-wave1-50"

# Quality validation with strict mode
python validate_dataset_quality.py "local_datasets/DataOcean/20260122-wave1-50" --strict

# Detailed analysis with verbose output
python validate_dataset_quality.py "local_datasets/DataOcean/20260122-wave1-50" --verbose

# Export results for reporting
python validate_dataset_quality.py "local_datasets/DataOcean/20260122-wave1-50" --json report.json
```

### Run Both Validations

```bash
# Windows PowerShell
python validate_dataset_consistency.py dataset.jsonl && python validate_dataset_quality.py dataset.jsonl

# Linux/Mac
python validate_dataset_consistency.py dataset.jsonl && python validate_dataset_quality.py dataset.jsonl
```

---

## Integration Options

These validators can be integrated into your workflow in **three different ways**, depending on your use case.

### Option 1: Command-Line Tools (CLI)

**Best for:** Manual validation, ad-hoc checks, scripting

```bash
# Run from command line
python validate_dataset_consistency.py dataset.jsonl
python validate_dataset_quality.py dataset.jsonl --strict
```

**When to use:**
- ✅ Manual dataset validation
- ✅ Quick checks during development
- ✅ Shell scripts and automation
- ✅ CI/CD pipelines (via shell commands)

---

### Option 2: Python Modules (Programmatic)

**Best for:** Hard-coded workflows, guaranteed validation, fixed pipelines

```python
from dataset_validator.validate_dataset_consistency import DatasetConsistencyValidator
from dataset_validator.validate_dataset_quality import DatasetQualityValidator

def prepare_dataset_for_evaluation(dataset_path):
    # Step 1: Consistency (MANDATORY - must pass)
    consistency = DatasetConsistencyValidator(dataset_path)
    if not consistency.validate():
        raise ValueError(f"Dataset invalid: {consistency.errors}")
    
    # Step 2: Quality (ADVISORY - guides improvements)
    quality = DatasetQualityValidator(dataset_path, strict=True)
    results = quality.validate()
    
    # Step 3: Make decision based on quality
    if results['prompt_alignment'] >= 70:
        return {'status': 'ready', 'quality': 'good'}
    else:
        return {'status': 'ready', 'quality': 'needs_review', 'results': results}
```

**When to use:**
- ✅ Validation is always required (mandatory gate)
- ✅ Fixed CI/CD pipelines
- ✅ Automated testing frameworks
- ✅ Single-purpose scripts
- ✅ Need direct access to result attributes

**Advantages:**
- Direct function calls (fast)
- Full control over execution
- Rich return values accessible
- Easy debugging
- No additional abstractions

---

### Option 3: Agent Skills (Dynamic Discovery)

**Best for:** Autonomous agents, flexible workflows, context-aware validation

**Skill Definitions Location:** `../.github/skills/`
- `validate-dataset-consistency-py/`
- `validate-dataset-quality-py/`

**How agents use skills:**

```yaml
Agent Workflow:
  1. User: "Run evaluation on my dataset"
  2. Agent discovers available skills
  3. Agent reads skill definitions:
     - when_to_use: "BEFORE running voice agent evaluations"
     - description: What the skill does
     - parameters: Available options
  4. Agent decides: "I should validate first"
  5. Agent calls skill with appropriate parameters
  6. Based on results, agent decides next action
```

**Example: Foundry Agent Integration**

```python
# Agent discovers skills dynamically
skills = agent.discover_skills()

# Agent reads skill metadata
consistency_skill = skills['validate-dataset-consistency']
when_to_use = consistency_skill.when_to_use  # "BEFORE running evaluations"

# Agent decides to use skill
if 'dataset' in user_request and 'evaluation' in user_request:
    # Call skill
    result = agent.call_skill('validate-dataset-consistency', {
        'dataset_path': extracted_path,
        'expected_turns': 3
    })
    
    if result.exit_code == 0:
        # Proceed to quality check
        quality_result = agent.call_skill('validate-dataset-quality', {
            'dataset_path': extracted_path,
            'strict': True
        })
```

**Example: GitHub Copilot CLI**

```bash
# Natural language - ask Copilot to validate
gh copilot suggest "validate the dataset at sample_data.jsonl for consistency"

# Copilot discovers skills, suggests command, and can execute:
# python dataset_validator/validate_dataset_consistency.py sample_data.jsonl

# Ask for complete validation workflow
gh copilot suggest "fully validate my voice dataset with strict quality checking"

# Copilot can chain commands:
# 1. Run consistency check
# 2. If passed, run quality check with --strict
# 3. Report results and suggest next steps

# Context-aware parameter selection
gh copilot suggest "validate MultiConversationSample dataset, it has variable turn counts"

# Copilot recognizes context and suggests appropriate flags:
# python validate_dataset_consistency.py MultiConversationSample
# (without --expected-turns, since user mentioned variable turns)

# Troubleshooting with Copilot
gh copilot suggest "my dataset validation failed, help me understand the errors"

# Copilot can:
# - Re-run validation with verbose output
# - Explain error messages
# - Suggest specific fixes
```

**When to use:**
- ✅ Agent needs to decide IF validation is needed
- ✅ Agent chooses WHICH mode to use (strict/default)
- ✅ Multiple agents share validation service
- ✅ Workflow is dynamic and context-dependent
- ✅ Agent discovers tools without hard-coding
- ✅ Natural language interface preferred (Copilot CLI)
- ✅ Want guided workflow with suggestions (Copilot CLI)

**Advantages:**
- Agent discovers automatically
- No hard-coding in agent logic
- Reusable across agents
- Version control per skill
- Context-aware decision making
- **Natural language commands** (Copilot CLI)
- **Guided workflows with suggestions** (Copilot CLI)
- **Automated error interpretation** (Copilot CLI)

---

## Integration Decision Guide

### Choose **CLI** when:
- Running manual checks
- Shell scripting
- Simple automation

### Choose **Python Modules** when:
- Validation always required (mandatory)
- Fixed CI/CD pipeline
- Direct programmatic control needed
- Single-purpose workflow

### Choose **Agent Skills** when:
- Agent decides when to validate
- Multiple agents using validators
- Dynamic, context-aware workflows
- Foundry Agents or similar platforms

### Can Use Multiple Approaches:
You can mix and match! For example:
- Use Skills for Foundry Agent (dynamic)
- Use Python Modules in CI/CD (fixed)
- Use CLI for manual testing

---

## Expected Dataset Format

### JSONL Structure
Each line should be a valid JSON object with these fields:

```json
{
  "WavPath": "conversation1-turn1.wav",
  "Question": "User question text",
  "Answer": "Expected answer or ground truth",
  "conversationID": "conversation1",
  "system_prompt": "System prompt defining agent behavior",
  "tool_definitions": null
}
```

### Required Fields
- **WavPath**: Filename of audio file (relative to JSONL location)
- **Question**: User's question/input text
- **Answer**: Expected answer for evaluation
- **conversationID**: Identifier grouping multi-turn conversations
- **system_prompt**: Agent instructions (must be consistent within a conversation)
- **tool_definitions**: Tool/function definitions (optional, can be null)

### Media Dataset Format (Foundry)

Datasets using the Foundry media format are also supported. Instead of `WavPath`, audio is provided inline via `input_audio`:

```json
{
  "messages": [
    {"role": "system", "content": "Agent instructions"},
    {"role": "user", "content": [
      {"type": "text", "text": "User query"},
      {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64,UklGR...", "format": "wav"}}
    ]}
  ],
  "expected_output": "Expected response",
  "conversationID": "conv1"
}
```

Audio can be a base64 data-URI (`data:audio/wav;base64,...`) or an Azure Blob Storage URL. The consistency validator detects both formats automatically.

### File Organization
```
dataset_folder/
├── dataset.jsonl              # Dataset metadata
├── conversation1-turn1.wav    # Input audio files
├── conversation1-turn2.wav
├── conversation1-turn3.wav
├── conversation1-turn1-response.wav  # Response audio (optional)
└── ...
```

## Output Examples

### Consistency Validation Output

```
================================================================================
  DATASET CONSISTENCY VALIDATION
  Dataset: 20260122-wave1-50.jsonl
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

✓ 4. CONVERSATION STRUCTURE VALIDATION
  Total conversations: 50
  Total entries: 150

  Turn Count Distribution:
    • 3 turns: 50 conversations (100.0%)
  ✅ CONSISTENT: All conversations have 3 turns
  ✅ PASSED: All conversations have consistent system_prompts

  🎯 STATUS: ✅ ALL CHECKS PASSED
```

**With `--expected-turns` flag:**
```
✓ 4. CONVERSATION STRUCTURE VALIDATION
  Total conversations: 50
  Total entries: 150
  ✅ PASSED: All conversations have exactly 3 turns
  ✅ PASSED: All conversations have consistent system_prompts

  🎯 STATUS: ✅ ALL CHECKS PASSED
```

**Variable turn counts (no flag):**
```
✓ 4. CONVERSATION STRUCTURE VALIDATION
  Total conversations: 2
  Total entries: 9

  Turn Count Distribution:
    • 3 turns: 1 conversations (50.0%)
    • 6 turns: 1 conversations (50.0%)
  ℹ  INFO: Dataset has variable turn counts across 2 different patterns
     (Use --expected-turns flag to validate specific turn count)
  ✅ PASSED: All conversations have consistent system_prompts
```

### Quality Validation Output

```
================================================================================
  DATASET QUALITY VALIDATION
  Dataset: 20260122-wave1-50.jsonl
================================================================================

✓ 1. SYSTEM PROMPT RELEVANCE
  ✅ Aligned: 44/50 (88.0%)
  ✅ GOOD: 88.0% alignment indicates strong prompt-content matching

✓ 2. TOOL DEFINITION APPROPRIATENESS
  ✅ CORRECT: No action requests detected.
     Dataset is conversational/instructional support.

✓ 3. CONTENT QUALITY METRICS
  Average Question length: 90 characters
  Average Answer length: 542 characters
  ✅ GOOD: Content has good depth and diversity

  📊 Key Metrics:
    ✅ System Prompt Alignment: 88.0%
    ✅ Tool Definitions: correct
    ✅ Content Quality: 3/3
```

## Exit Codes

- **0**: Validation passed
- **1**: Validation failed or error occurred

Use exit codes in CI/CD pipelines:

```bash
python validate_dataset_consistency.py dataset.jsonl
if [ $? -eq 0 ]; then
    echo "Validation passed"
    python validate_dataset_quality.py dataset.jsonl
fi
```

## Interpretation Guide

### System Prompt Alignment

**Default Mode (Permissive):**
- **≥70%**: Good alignment - quality support responses detected
- **50-70%**: Moderate - review recommended
- **<50%**: Low - prompts may not match conversations

**Strict Mode (Conservative):**
- **≥60%**: Good alignment - domain keywords present
- **40-60%**: Moderate - mixed domain expertise
- **<40%**: Low - domain vocabulary missing

*Note: Default mode is recommended for general validation. Use `--strict` when validating domain-specific expertise.*

### Tool Definition Assessment
- **correct**: No action requests, NULL tools appropriate
- **needs_review**: Action requests present, consider adding tools
- **good**: Action requests have tool definitions
- **mixed**: Mixed dataset with both types

### Content Quality Score (0-3)
- **3**: Excellent - good length, depth, and diversity
- **2**: Good - meets quality standards
- **1**: Moderate - some concerns
- **0**: Needs improvement - quality issues detected

## Common Issues and Solutions

### Issue: "Multiple JSONL files found"
**Solution**: Specify the exact JSONL file path instead of folder

### Issue: "Missing audio files"
**Solution**: Ensure WAV files are in the same folder as JSONL, with exact filename matches

### Issue: "Inconsistent system_prompts"
**Solution**: Each conversation should use the same system_prompt across all turns

### Issue: Low alignment percentage
**Solution**: Review system prompts - may be too generic or mismatched to conversation topics

## Integration with Evaluation Pipeline

Use these scripts before running evaluations:

```bash
# 1. Validate consistency
python validate_dataset_consistency.py dataset.jsonl || exit 1

# 2. Validate quality
python validate_dataset_quality.py dataset.jsonl || exit 1

# 3. Run evaluation
python voice_agent_audio_input_evaluation.py --input dataset.jsonl
```

## Customization

Both scripts can be imported as modules for custom validation workflows:

```python
from validate_dataset_consistency import DatasetConsistencyValidator
from validate_dataset_quality import DatasetQualityValidator

# Custom validation pipeline
consistency = DatasetConsistencyValidator("dataset.jsonl")
if consistency.validate():
    # Use strict mode for domain-specific datasets
    quality = DatasetQualityValidator("dataset.jsonl", strict=True, verbose=True)
    results = quality.validate()
    
    # Access detailed results
    alignment = results['prompt_alignment']['alignment_percentage']
    print(f"Alignment: {alignment:.1f}%")
    
    # Check specific metrics
    domains = results['prompt_alignment']['domains']
    for domain, stats in domains.items():
        print(f"{domain}: {stats['aligned']}/{stats['total']}")
```

### JSON Output Structure

```json
{
  "status": "success",
  "prompt_alignment": {
    "total_conversations": 50,
    "aligned": 44,
    "unaligned": 6,
    "alignment_percentage": 88.0,
    "domains": {
      "Smart Home Tech Support": {"total": 10, "aligned": 9},
      ...
    }
  },
  "tool_appropriateness": {
    "with_tools": 0,
    "without_tools": 150,
    "action_requests": 0,
    "instructional": 49,
    "general": 101,
    "assessment": "correct"
  },
  "content_quality": {
    "avg_question_length": 89.6,
    "avg_answer_length": 541.6,
    "unique_prompts": 32,
    "total_conversations": 50,
    "total_entries": 150,
    "quality_score": 3
  }
}
```

## Support

For issues or questions about these validation scripts, refer to the main project documentation or create an issue in the repository.

---

**Last Updated**: 2026-01-30
