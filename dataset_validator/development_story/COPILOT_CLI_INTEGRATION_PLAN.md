# Executable Plan: Integrate Dataset Validators as GitHub Copilot CLI Skills

## Overview
This plan outlines the steps to integrate the dataset validator skills into GitHub Copilot CLI, enabling direct validation from the CLI using natural language commands.

**Goal:** Validate datasets by asking Copilot CLI instead of running Python scripts manually.

**Example:**
```bash
# Instead of:
python validate_dataset_consistency.py dataset.jsonl

# Do this:
gh copilot suggest "validate the dataset at dataset.jsonl for consistency"
# Or simply:
@validate-dataset-consistency dataset.jsonl
```

---

## Prerequisites

✅ **Already Complete:**
- Dataset validators developed and tested
- Skills defined in `.github/skills/`
- Comprehensive documentation
- Self-contained package

⚠️ **Need to Verify:**
- GitHub Copilot CLI installed and configured
- Repository structure compatible with Copilot skill discovery

---

## Phase 1: Verify Copilot CLI Setup

### Step 1.1: Check Copilot CLI Installation

```bash
# Check if GitHub CLI is installed
gh --version

# Check if Copilot extension is installed
gh extension list | grep copilot

# If not installed, install it
gh extension install github/gh-copilot
```

### Step 1.2: Authenticate and Configure

```bash
# Authenticate with GitHub
gh auth login

# Configure Copilot
gh copilot config
```

### Step 1.3: Test Basic Copilot Functionality

```bash
# Test that Copilot CLI works
gh copilot suggest "list files in current directory"

# Test skill discovery (if available)
gh copilot skills list
```

**Expected Result:** Copilot CLI responds to commands

---

## Phase 2: Verify Skill Structure Compatibility

### Step 2.1: Review Copilot CLI Skill Requirements

**Research needed:**
- What format does Copilot CLI expect for skills?
- Is `.github/skills/` the correct location?
- Do our YAML files match the expected schema?
- Are there additional fields required?

**Action Items:**
1. Check Copilot CLI documentation: `gh copilot help`
2. Look for skill examples in GitHub repositories
3. Verify our skill.yaml format matches expected schema
4. Check if skills need to be in repository root or can be in subdirectory

### Step 2.2: Validate Our Skill Structure

**Current Structure:**
```
prototype_v1/
└── dataset_validator/
    └── .github/
        └── skills/
            ├── validate-dataset-consistency-py/
            │   ├── skill.yaml
            │   └── README.md
            └── validate-dataset-quality-py/
                ├── skill.yaml
                └── README.md
```

**Questions to Answer:**
- ❓ Should skills be at repo root `.github/skills/`?
- ❓ Does Copilot discover skills in subdirectories?
- ❓ Do we need a skills manifest file?

**Action:** Test both locations:
1. Keep in `dataset_validator/.github/skills/`
2. If not discovered, copy to `prototype_v1/.github/skills/`
3. If still not discovered, copy to repo root `.github/skills/`

---

## Phase 3: Install/Register Skills with Copilot CLI

### Step 3.1: Option A - Local Skill Discovery

If Copilot CLI auto-discovers skills in `.github/skills/`:

```bash
# Navigate to repository root
cd C:\Localrepos\voicelive-evaluation

# List discovered skills
gh copilot skills list

# Expected output:
# - validate-dataset-consistency
# - validate-dataset-quality
```

### Step 3.2: Option B - Manual Skill Registration

If manual registration is needed:

```bash
# Register consistency validator skill
gh copilot skills add ./prototype_v1/dataset_validator/.github/skills/validate-dataset-consistency-py

# Register quality validator skill
gh copilot skills add ./prototype_v1/dataset_validator/.github/skills/validate-dataset-quality-py

# Verify registration
gh copilot skills list
```

### Step 3.3: Option C - Skills as GitHub Copilot Extensions

If skills need to be formal extensions:

```bash
# This would require packaging as proper extensions
# Follow GitHub Copilot extension development guide
# May need additional manifest files
```

**Determine which option applies by:**
1. Reading `gh copilot skills --help`
2. Checking GitHub documentation
3. Testing each approach

---

## Phase 4: Test Skill Discovery and Invocation

### Step 4.1: Verify Skills Are Discovered

```bash
# List available skills
gh copilot skills list

# Get details about specific skill
gh copilot skills info validate-dataset-consistency

# Expected output: Show skill metadata, parameters, description
```

### Step 4.2: Test Skill Invocation (Natural Language)

```bash
# Test consistency validator via natural language
gh copilot suggest "validate the dataset consistency of the file at prototype_v1/local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl"

# Expected: Copilot recognizes request and suggests using validate-dataset-consistency skill
```

### Step 4.3: Test Direct Skill Execution

```bash
# If Copilot supports direct skill execution
gh copilot run validate-dataset-consistency --dataset-path "prototype_v1/local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl"

# Or with skill syntax
@validate-dataset-consistency "prototype_v1/local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl"
```

### Step 4.4: Test with Different Parameters

```bash
# Test with expected-turns flag
gh copilot run validate-dataset-consistency \
  --dataset-path "prototype_v1/local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl" \
  --expected-turns 3

# Test quality validator with strict mode
gh copilot run validate-dataset-quality \
  --dataset-path "prototype_v1/local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl" \
  --strict
```

---

## Phase 5: Adjust Skills Based on Findings

### Step 5.1: Fix Skill Definition if Needed

Based on testing, we may need to update:

**skill.yaml adjustments:**
- Add/remove required fields
- Adjust entry_point path format
- Add execution permissions
- Modify parameter schema

**Example potential changes:**
```yaml
# May need to specify execution method
execution:
  type: python
  script: ../validate_dataset_consistency.py
  
# May need permission declarations
permissions:
  - filesystem:read
  - filesystem:list
```

### Step 5.2: Add Skill Wrapper Script (if needed)

If Copilot can't execute Python directly, create wrapper:

```bash
# File: .github/skills/validate-dataset-consistency-py/run.sh
#!/bin/bash
cd "$(dirname "$0")/../../.."
python dataset_validator/validate_dataset_consistency.py "$@"
```

Update skill.yaml:
```yaml
entry_point: ./run.sh  # Instead of ../validate_dataset_consistency.py
```

### Step 5.3: Test Adjusted Skills

Re-run all tests from Phase 4 after adjustments.

---

## Phase 6: Create Workflow Examples

### Step 6.1: Document Copilot CLI Usage

Create: `dataset_validator/COPILOT_CLI_USAGE.md`

```markdown
# Using Dataset Validators via GitHub Copilot CLI

## Natural Language Commands

Ask Copilot to validate datasets:

```bash
gh copilot suggest "validate the consistency of my dataset"
gh copilot suggest "check if dataset quality is good with strict mode"
gh copilot suggest "analyze turn counts in my voice dataset"
```

## Direct Skill Invocation

Use skills directly:

```bash
# Consistency validation
@validate-dataset-consistency path/to/dataset.jsonl

# Quality validation with strict mode
@validate-dataset-quality path/to/dataset.jsonl --strict

# With expected turns
@validate-dataset-consistency path/to/dataset.jsonl --expected-turns 3
```
```

### Step 6.2: Create Example Workflows

**Example 1: Quick Dataset Check**
```bash
# User asks Copilot
gh copilot suggest "I have a new dataset at sample_data.jsonl, validate it"

# Copilot executes:
@validate-dataset-consistency sample_data.jsonl
# Then suggests:
# "Consistency passed! Would you like me to check quality too?"
```

**Example 2: Complete Validation Pipeline**
```bash
# User asks Copilot
gh copilot suggest "fully validate my voice evaluation dataset before running tests"

# Copilot executes in sequence:
@validate-dataset-consistency dataset.jsonl
@validate-dataset-quality dataset.jsonl --strict --verbose
# Then reports results and suggests next steps
```

**Example 3: Troubleshooting**
```bash
# User asks Copilot
gh copilot suggest "my dataset validation failed, what's wrong?"

# Copilot re-runs with verbose output:
@validate-dataset-consistency dataset.jsonl
# Analyzes error messages
# Suggests fixes based on error types
```

---

## Phase 7: Integration Testing

### Step 7.1: Test Complete Workflow

**Scenario 1: New Dataset Validation**
1. User: "I have a new dataset to validate"
2. Copilot: Asks for path
3. User: Provides path
4. Copilot: Runs consistency check
5. Copilot: If passed, offers quality check
6. Copilot: Reports results and next steps

**Scenario 2: Failed Validation**
1. User: "Validate this dataset"
2. Copilot: Runs validation
3. Validation fails
4. Copilot: Explains errors
5. Copilot: Suggests fixes
6. User: Fixes issues
7. Copilot: Re-validates

**Scenario 3: Choosing Options**
1. User: "Validate dataset quality strictly"
2. Copilot: Recognizes "strictly" → uses --strict flag
3. Copilot: Executes with appropriate parameters
4. Copilot: Reports domain alignment results

### Step 7.2: Compare Manual vs Copilot CLI

**Before (Manual):**
```bash
cd prototype_v1/dataset_validator
python validate_dataset_consistency.py ../local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl
python validate_dataset_quality.py ../local_datasets/DataOcean/20260122-wave1-50/20260122-wave1-50.jsonl --strict
```

**After (Copilot CLI):**
```bash
# From anywhere in the repo
gh copilot suggest "validate the DataOcean wave1-50 dataset with strict quality check"
```

**Benefits:**
- ✅ Natural language interface
- ✅ No need to remember paths
- ✅ No need to remember exact command syntax
- ✅ Copilot suggests next steps
- ✅ Context-aware parameter selection

---

## Phase 8: Documentation and Knowledge Base

### Step 8.1: Update Main README

Add section to `dataset_validator/DATASET_VALIDATION_README.md`:

```markdown
## Option 4: GitHub Copilot CLI (Conversational)

**Best for:** Natural language interaction, guided workflows

```bash
# Ask Copilot to validate
gh copilot suggest "validate my voice dataset for consistency"

# Copilot discovers skills, asks for details, runs validation
```

**When to use:**
- ✅ Prefer natural language over commands
- ✅ Want guided validation workflow
- ✅ Need help choosing right parameters
- ✅ Want Copilot to suggest next steps

**Advantages:**
- Natural conversation
- Context-aware suggestions
- Guided parameter selection
- Automated workflow recommendations
```

### Step 8.2: Create Troubleshooting Guide

Document common issues and solutions:

**Issue 1: Skills Not Discovered**
- Solution: Move to repo root `.github/skills/`
- Solution: Check skill.yaml format
- Solution: Restart Copilot session

**Issue 2: Execution Permissions**
- Solution: Add execution permissions to Python scripts
- Solution: Create wrapper scripts with proper permissions

**Issue 3: Path Resolution**
- Solution: Use absolute paths in skill invocations
- Solution: Adjust working directory in skill definition

---

## Phase 9: Rollout and Training

### Step 9.1: Team Training

Create training materials:
1. "Using Dataset Validators via Copilot CLI" guide
2. Video walkthrough of common scenarios
3. Quick reference card for common commands

### Step 9.2: Gradual Adoption

**Week 1:** Pilot with 1-2 team members
- Test all scenarios
- Gather feedback
- Document issues

**Week 2:** Expand to team
- Share lessons learned
- Provide training session
- Monitor usage

**Week 3:** Full adoption
- Deprecate manual script usage
- Update CI/CD to use Copilot CLI
- Measure time savings

---

## Success Criteria

### Phase Completion Checklist

- [ ] **Phase 1:** Copilot CLI installed and working
- [ ] **Phase 2:** Skill structure verified compatible
- [ ] **Phase 3:** Skills registered/discovered by Copilot
- [ ] **Phase 4:** Skills invokable via natural language
- [ ] **Phase 5:** Skills execute correctly with all parameters
- [ ] **Phase 6:** Documentation complete
- [ ] **Phase 7:** Integration testing passed
- [ ] **Phase 8:** Knowledge base updated
- [ ] **Phase 9:** Team trained and adopting

### Key Performance Indicators

**Before (Manual):**
- Time to validate: ~2-3 minutes (navigate, type command, review)
- Commands to remember: 2 scripts × multiple flags
- Documentation lookup: Frequent

**After (Copilot CLI):**
- Time to validate: ~30 seconds (ask Copilot)
- Commands to remember: 0 (natural language)
- Documentation lookup: Rare (Copilot guides)

**Target Metrics:**
- ✅ 70% reduction in validation time
- ✅ 100% reduction in syntax errors
- ✅ 90% reduction in documentation lookups
- ✅ Natural language success rate: >80%

---

## Rollback Plan

If Copilot CLI integration doesn't work as expected:

### Fallback Options

1. **Keep Python scripts** (already working)
2. **Create shell aliases** (bridge solution)
3. **Use Foundry Agents instead** (alternative platform)

### Decision Points

**Proceed with Copilot CLI if:**
- ✅ Skills discoverable automatically
- ✅ Natural language works reliably
- ✅ Execution is straightforward
- ✅ Team finds it intuitive

**Fall back to Python/Skills if:**
- ❌ Complex setup required
- ❌ Frequent failures or bugs
- ❌ Natural language unreliable
- ❌ Not significantly better than manual

---

## Next Actions

### Immediate (Do Now)

1. **Verify Copilot CLI setup**
   ```bash
   gh --version
   gh extension list
   gh copilot suggest "test command"
   ```

2. **Research skill format requirements**
   ```bash
   gh copilot skills --help
   gh copilot --help
   ```

3. **Test skill discovery**
   ```bash
   gh copilot skills list
   ```

### Short-term (This Week)

4. **Adjust skill structure if needed**
5. **Test skill invocation**
6. **Document findings**
7. **Create usage examples**

### Medium-term (Next Week)

8. **Complete integration testing**
9. **Update all documentation**
10. **Train team members**

---

## Appendix: Reference Commands

### GitHub Copilot CLI Commands

```bash
# Help
gh copilot --help
gh copilot skills --help

# Suggest commands
gh copilot suggest "your natural language request"

# Explain commands
gh copilot explain "command to explain"

# Skills management (if available)
gh copilot skills list
gh copilot skills info <skill-name>
gh copilot skills add <path>
gh copilot skills remove <skill-name>
```

### Our Validator Skills

```bash
# Consistency validation
@validate-dataset-consistency <path> [--expected-turns N] [--ignore-comments]

# Quality validation  
@validate-dataset-quality <path> [--strict] [--verbose] [--json output.json] [--ignore-comments]
```

### Natural Language Examples

```bash
gh copilot suggest "validate dataset consistency"
gh copilot suggest "check dataset quality with strict mode"
gh copilot suggest "analyze voice dataset turn counts"
gh copilot suggest "validate all datasets in this folder"
gh copilot suggest "my validation failed, help me fix it"
```

---

## Conclusion

This plan provides a clear path from our current Python-based validators to Copilot CLI integration. The key is maintaining flexibility - our validators work standalone, as Python modules, as formal skills, AND potentially via Copilot CLI natural language interface.

**Total Estimated Time:** 4-8 hours
- Research & setup: 2-3 hours
- Testing & adjustment: 2-3 hours  
- Documentation: 1-2 hours

**Expected Outcome:** Dataset validation via natural language commands through GitHub Copilot CLI.
