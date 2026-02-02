# Voice Live Evaluation Agent

## Overview

An intelligent agent for automating Voice Live evaluation workflows, including dataset validation, audio testing, and Foundry evaluations. Built on Azure AI Agents SDK with Azure Identity for secure API access.

**Purpose:** Automate and orchestrate voice agent evaluation tasks through natural language commands and intelligent decision-making.

**Key Principle:** All API calls use Azure Identity - NO API KEYS.

**Current Status:** 🚀 Phase 1 Complete
- ✅ Project scope defined
- ✅ Implementation approaches analyzed  
- ✅ Skills created (3 skills in `skills/` folder)
- ✅ Agent implementation complete (`agent.py`)
- ✅ Smart session mode auto-detection
- ✅ Real-time console status output during tool execution
- ✅ Progress tracking for long-running evaluations

---

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r requirements.txt

# Option 1: Use .env file (recommended)
# Create/edit .env in this folder with:
PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
MODEL_DEPLOYMENT_NAME=gpt-4.1-mini

# Option 2: Set environment variables directly
$env:PROJECT_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"
$env:MODEL_DEPLOYMENT_NAME = "gpt-4.1-mini"
```

### Run the Agent

```bash
# Interactive mode
python agent.py

# Single message mode
python agent.py --message "What datasets are available?"
python agent.py --message "Validate the dataset at C:\datasets\test.jsonl"
python agent.py --message "Run evaluation on the Eiffel_Tower_Visit dataset"
```

### Example Session

```
You: What datasets are available?

⚙️  Searching for datasets...
✓ Found 6 datasets in 2 locations

Agent: Here are all 6 datasets found:

1. **BingChat_en_minimal_10** (10 entries) - recommended mode: per-file
   Path: prototype_v1/sample_evaluation_input/BingChat_7days_en

2. **DataOceanDemoComplexSession1** (3 entries) - recommended mode: per-conversation
   Path: prototype_v1/sample_evaluation_input/DataOceanDemoComplexSession1
   
[... complete list shown ...]

You: Validate the Eiffel_Tower_Visit dataset

⚙️  Running consistency validation on Eiffel_Tower_Visit.jsonl...
✓ Consistency validation PASSED

⚙️  Running quality validation on Eiffel_Tower_Visit.jsonl...
✓ Quality validation COMPLETED

Agent: The dataset passed both validations:
- **Consistency**: All 5 entries have valid structure
- **Quality**: 100% system prompt alignment, proper tool definitions

You: Run VoiceLive evaluation on it

⚙️  Starting VoiceLive evaluation on Eiffel_Tower_Visit.jsonl...
   Session mode: per-conversation (auto-detected)
   Entries: 5
   Timeout: 30 minutes
✓ Evaluation COMPLETED for Eiffel_Tower_Visit.jsonl (245.3s)

Agent: Evaluation completed successfully!
- **Session mode**: per-conversation (auto-detected from conversationID field)
- **Duration**: 4 minutes 5 seconds
- **Files processed**: 5
- **Output**: prototype_v1/output/evaluations/...
```

---

## Features

### Real-Time Console Status
Status messages print **immediately** when tools execute (not waiting for agent response):

| Tool | Console Output |
|------|----------------|
| `list_datasets` | `⚙️ Searching for datasets...` → `✓ Found N datasets` |
| `validate_dataset_consistency` | `⚙️ Running consistency validation...` → `✓/✗ result` |
| `validate_dataset_quality` | `⚙️ Running quality validation...` → `✓/✗ result` |
| `run_voicelive_evaluation` | `⚙️ Starting VoiceLive evaluation...` with details → `✓/✗ result` |

### Status Icons
- ⚙️ Tool is executing
- ✓ Success
- ⚠ Warning (e.g., timeout)
- ✗ Error/failure

### Progress Tracking for Long Evaluations
For VoiceLive evaluations (which can take several minutes), the agent shows:
- **Session mode** and whether it was auto-detected
- **Entry count** in the dataset
- **Timeout setting** (default 30 minutes)
- **Elapsed time** when complete
- **Files processed** count

---

## Agent Tools

The agent has 4 built-in tools:

| Tool | Purpose |
|------|---------|
| `list_datasets` | Find all JSONL datasets (always shows complete list with metadata) |
| `validate_dataset_consistency` | MANDATORY structural validation before evaluation |
| `validate_dataset_quality` | ADVISORY content quality assessment |
| `run_voicelive_evaluation` | Execute VoiceLive API tests with smart session mode and progress tracking |

---

## Session Mode Auto-Detection

When running VoiceLive evaluations, the session mode is **automatically detected** based on dataset structure:

| Dataset Structure | Auto-Selected Mode | Behavior |
|-------------------|-------------------|----------|
| Has `conversationID` field | `per-conversation` | Groups turns by conversationID, maintains context within each conversation |
| No `conversationID` field | `per-file` | Each file evaluated in isolation, no shared context |
| User explicitly requests | `single` | All files in one continuous session (only when asked) |

**Examples:**
```bash
# Auto-detects mode based on dataset
python agent.py --message "Run evaluation on dataset X"

# User explicitly requests single mode
python agent.py --message "Run evaluation on dataset X using single session mode"
```

---

## Project Scope

### Core Capabilities

1. **Dataset Validation**
   - Validate JSONL datasets for consistency and quality
   - Leverage existing `dataset_validator` scripts
   - Intelligent decisions about validation modes (strict/default, expected turns)

2. **VoiceLive Audio Testing**
   - Execute voice agent audio input evaluations
   - Run VoiceLive API tests with audio files
   - Smart session mode selection based on dataset structure
   - Monitor and report test results

3. **Workflow Orchestration**
   - Chain evaluation tasks intelligently (validate → evaluate)
   - Handle errors and suggest remediation
   - Provide status updates and insights

### Key Features

- ✅ **Natural Language Interface** - Commands in plain English
- ✅ **Intelligent Decision Making** - Auto-detects session mode from dataset
- ✅ **Complete Dataset Lists** - Never truncates or summarizes dataset listings
- ✅ **Secure Authentication** - Azure Identity (DefaultAzureCredential)
- ✅ **Error Handling** - Detect, explain, suggest fixes
- ✅ **Progress Tracking** - Real-time status updates
- ✅ **Result Reporting** - Comprehensive summaries

---

## Use Cases

### Use Case 1: Dataset Validation Workflow

**User:** "Validate the MultiConversationSample dataset for me."

**Agent Actions:**
1. Runs consistency validation (MANDATORY)
2. Analyzes results - finds 3 missing system_prompts
3. Reports: "Dataset failed consistency. 3 entries missing system_prompt. Cannot proceed to quality validation."
4. Suggests: "Fix missing prompts, then re-validate."

### Use Case 2: Complete Evaluation Pipeline

**User:** "Run a full evaluation on dataset X."

**Agent Actions:**
1. Validates dataset (consistency + quality)
2. If passed, runs VoiceLive audio tests
3. Triggers Foundry evaluation
4. Monitors progress
5. Reports comprehensive results

### Use Case 3: Batch Validation

**User:** "Validate all datasets in sample_evaluation_input folder."

**Agent Actions:**
1. Discovers all .jsonl files
2. Validates each (consistency + quality)
3. Generates comparison report
4. Highlights: "20260122-wave1-50 is ready. MultiConversationSample has errors."

### Use Case 4: Troubleshooting

**User:** "My evaluation failed. What went wrong?"

**Agent Actions:**
1. Retrieves logs
2. Analyzes errors
3. Identifies root cause
4. Suggests specific fixes

---

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────┐
│          User (Natural Language)                │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│      Azure Foundry Agent Service                │
│  ┌──────────────────────────────────────────┐   │
│  │   Voice Live Evaluation Agent            │   │
│  │   - Intent Understanding                 │   │
│  │   - Workflow Orchestration               │   │
│  │   - Decision Making                      │   │
│  └──────────────┬───────────────────────────┘   │
└─────────────────┼───────────────────────────────┘
                  │ Azure Identity
      ┌───────────┼───────────┐
      │           │           │
      ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│ Skills  │ │  APIs   │ │ Storage │
└─────────┘ └─────────┘ └─────────┘
      │           │           │
┌─────▼─────┐ ┌──▼──────┐ ┌──▼──────┐
│ Dataset   │ │VoiceLive│ │ Foundry │
│Validators │ │  API    │ │  Eval   │
│(.github/  │ │(Az ID)  │ │ (Az ID) │
│ skills/)  │ └─────────┘ └─────────┘
└───────────┘
```

### Components

**1. Agent Core (Foundry Agent Service)**
- Intent Parser
- Workflow Engine
- State Manager
- Decision Engine

**2. Skills Integration**
- Dataset validators (existing)
- Custom VoiceLive skills (new)

**3. API Clients (All using Azure Identity)**
- VoiceLive API Client
- Foundry Evaluation Client
- Azure Storage Client

**4. Authentication**
- Azure Managed Identity (preferred)
- DefaultAzureCredential (dev/local)
- NO API KEYS

---

## Implementation Approaches

### Approach 1: Pure Foundry Agent Service ✅ RECOMMENDED

**Description:** Native Foundry Agent Service with minimal custom code.

**Architecture:**
```
Azure Foundry Agent Service
├── Agent Definition (YAML)
├── Skills (auto-discovered)
├── Connectors (Azure APIs)
└── Workflows (declarative)
```

**Pros:**
- ✅ Fully managed
- ✅ Built-in skill discovery
- ✅ Native Azure Identity
- ✅ Minimal code to maintain
- ✅ Production-ready

**Cons:**
- ⚠️ Learning curve
- ⚠️ May need custom connectors

**Best For:** Production deployment, long-term maintainability

---

### Approach 2: Semantic Kernel + Foundry Hosting

**Description:** SK agent hosted on Foundry.

**Architecture:**
```
Semantic Kernel Agent
├── Kernel + Planners
├── Plugins (validators, VoiceLive)
└── Azure Identity auth
   ↓
Deployed to Foundry Agent Service
```

**Pros:**
- ✅ Auto-planning
- ✅ Rich ecosystem
- ✅ Flexible

**Cons:**
- ⚠️ More code
- ⚠️ Packaging complexity

**Best For:** Complex workflows, SK experience

---

### Approach 3: LangChain + Foundry Hosting

**Description:** LangChain agent on Foundry.

**Architecture:**
```
LangChain Agent
├── LLM + Chains
├── Tools (validators)
└── Azure OpenAI (Az ID)
   ↓
Deployed to Foundry
```

**Pros:**
- ✅ Rich tooling
- ✅ LLM-first

**Cons:**
- ⚠️ Tool wrapping needed
- ⚠️ More code

**Best For:** LLM-heavy, rapid prototyping

---

### Approach 4: Hybrid (Foundry + Python Extensions)

**Description:** Foundry core + Python for complex logic.

**Architecture:**
```
Foundry Agent (Primary)
└── Python Extensions
    ├── Dataset validator wrapper
    ├── VoiceLive client
    └── Custom logic
```

**Pros:**
- ✅ Best of both worlds
- ✅ Flexibility

**Cons:**
- ⚠️ Extension maintenance

**Best For:** Gradual migration, custom needs

---

## Recommended Approach

### **Approach 1: Pure Foundry Agent Service** ✅

**Why:**
1. Managed service - minimal ops overhead
2. Native Azure Identity integration
3. Works with existing `.github/skills/`
4. Less code to maintain
5. Built for production

**Migration Path:** Start pure Foundry, add extensions if needed.

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

**Goals:**
- Foundry Agent Service setup
- Azure Identity authentication
- Basic agent running

**Tasks:**
1. Create Foundry Agent Service instance
2. Configure Managed Identity
3. Create basic agent definition
4. Test Azure Identity with sample API

**Deliverables:**
- Working Foundry Agent
- Azure Identity auth verified
- "Hello world" agent responds

---

### Phase 2: Dataset Validation (Week 2)

**Goals:**
- Integrate dataset_validator skills
- Validation via natural language

**Tasks:**
1. Configure skill discovery for `../dataset_validator/.github/skills/`
2. Test skill invocation
3. Implement validation workflow
4. Add error handling

**Deliverables:**
- Agent discovers skills
- User can say: "Validate dataset X"
- Results explained clearly

---

### Phase 3: VoiceLive Integration (Week 3)

**Goals:**
- VoiceLive API connection
- Audio test execution

**Tasks:**
1. Create VoiceLive API client (Azure Identity)
2. Implement test execution
3. Progress monitoring
4. Result parsing

**Deliverables:**
- User can say: "Run audio tests on X"
- Progress updates work
- Results summarized

---

### Phase 4: Foundry Evaluation (Week 4)

**Goals:**
- Trigger Foundry evaluations
- Track progress

**Tasks:**
1. Foundry Evaluation API client (Azure Identity)
2. Evaluation triggering
3. Progress tracking
4. Result reporting

**Deliverables:**
- User can say: "Run Foundry eval on X"
- Status updates provided
- Results comprehensive

---

### Phase 5: Orchestration (Week 5)

**Goals:**
- Multi-step workflows
- Intelligent decisions

**Tasks:**
1. Workflow engine
2. Decision logic
3. Error recovery
4. Templates

**Deliverables:**
- User can say: "Fully evaluate X"
- Agent chains: validate → test → eval
- Errors handled intelligently

---

### Phase 6: Advanced (Week 6+)

**Goals:**
- Batch operations
- Analytics
- Recommendations

**Deliverables:**
- Batch validation
- Comparison reports
- Insights and suggestions

---

## Technical Requirements

### Azure Resources

1. **Foundry Agent Service**
   - Agent instance
   - Storage

2. **Azure Identity**
   - Managed Identity (preferred)
   - Permissions via RBAC

3. **Azure OpenAI**
   - GPT-4 deployment
   - Token quotas

4. **API Access**
   - VoiceLive API (Azure AD auth)
   - Foundry Evaluation API
   - Storage accounts

### RBAC Permissions

- `Cognitive Services User` (OpenAI)
- `Storage Blob Data Reader` (datasets)
- `Storage Blob Data Contributor` (results)
- Custom roles for VoiceLive/Foundry APIs

---

## Security

### Azure Identity Best Practices

1. **Use Managed Identity**
   - System or User-assigned
   - No credentials to manage
   - Auto rotation

2. **Least Privilege**
   - Grant only needed permissions
   - Scope to specific resources
   - Regular audits

3. **NO API KEYS**
   - All APIs via Azure AD tokens
   - Certificate auth if Service Principal
   - Key Vault for any secrets (certs only)

### API Security

- HTTPS only
- Input validation
- Rate limiting
- Audit logging
- Token refresh handling

---

## Success Criteria

### Must Have (Phases 1-3)
- ✅ Foundry Agent deployed
- ✅ Azure Identity working
- ✅ Dataset validation via NL
- ✅ VoiceLive tests executable
- ✅ Error handling

### Should Have (Phases 4-5)
- ✅ Foundry evals integrated
- ✅ Multi-step workflows
- ✅ Progress tracking
- ✅ Result reporting

### Nice to Have (Phase 6+)
- ✅ Batch operations
- ✅ Analytics
- ✅ Recommendations

---

## Next Steps

### Immediate Actions

1. **Research Foundry Agent Service**
   - Documentation review
   - Capabilities assessment
   - Gap identification

2. **Azure Setup**
   - Create Foundry instance
   - Configure Managed Identity
   - Set permissions

3. **Proof of Concept**
   - Simple dataset validation
   - Test Azure Identity
   - Verify skill discovery

4. **Define Agent Schema**
   - Agent definition
   - Skill registrations
   - Conversation flows

### Questions to Answer

- ❓ Exact Foundry Agent API?
- ❓ Skill discovery mechanism?
- ❓ Deployment patterns?
- ❓ Available LLM models?
- ❓ State management?

---

## Resources

### Related Projects

- **Dataset Validators:** `../dataset_validator/`
- **VoiceLive Tests:** `../prototype_v1/voice_agent_audio_input_evaluation.py`
- **Skills:** `../dataset_validator/.github/skills/`

### Documentation

- [Azure Identity Docs](https://learn.microsoft.com/azure/developer/python/sdk/authentication-overview)
- Foundry Agent Service - TBD
- VoiceLive API - TBD

---

## Benefits

**Automation:** 70%+ reduction in manual work
**Intelligence:** Context-aware decisions
**Security:** Azure Identity, no keys
**Insights:** Actionable recommendations
**Scalability:** Production-ready

**Ready to implement Phase 1!**
