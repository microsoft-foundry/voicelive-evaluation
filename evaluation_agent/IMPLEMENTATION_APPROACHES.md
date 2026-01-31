# Voice Live Evaluation Agent - Implementation Approaches

## Detailed Comparison of 4 Approaches

This document provides in-depth analysis of different ways to build the Voice Live Evaluation Agent using Azure Foundry Agent Service.

---

## Approach 1: Pure Foundry Agent Service (RECOMMENDED)

### Overview
Build the agent entirely using Azure Foundry Agent Service native capabilities with minimal custom code.

### Architecture
```
Azure Foundry Agent Service
├── Agent Definition (agent.yaml)
│   ├── Name & description
│   ├── Capabilities
│   └── Conversation flows
├── Skills (auto-discovered)
│   ├── validate-dataset-consistency
│   ├── validate-dataset-quality
│   └── Custom VoiceLive skills (to be created)
├── Connectors (built-in)
│   ├── Azure OpenAI (for LLM)
│   ├── Azure Storage (for datasets)
│   └── Custom API connectors
└── Authentication
    └── Managed Identity (system-assigned)
```

### Implementation Details

**Step 1: Agent Definition**
```yaml
# agent.yaml
name: voicelive-evaluation-agent
version: 1.0.0
description: Automates Voice Live evaluation workflows
llm:
  provider: azure-openai
  deployment: gpt-4
  auth: managed-identity

skills:
  discovery_paths:
    - ../dataset_validator/.github/skills/
  
capabilities:
  - dataset_validation
  - voicelive_testing
  - foundry_evaluation
  - workflow_orchestration

conversation:
  greeting: "I can help validate datasets and run Voice Live evaluations."
  error_handling: detailed
  context_retention: true
```

**Step 2: Azure Identity Setup**
```python
from azure.identity import ManagedIdentityCredential

# Foundry automatically uses this
credential = ManagedIdentityCredential()

# All API calls use:
# - VoiceLive API: credential.get_token("https://api.voicelive.azure.com/.default")
# - Storage: credential for Azure Storage SDK
# - Foundry: credential for Foundry API
```

**Step 3: Custom Connectors (if needed)**
```yaml
# connectors/voicelive.yaml
name: voicelive-api
type: rest-api
base_url: https://api.voicelive.azure.com
authentication:
  type: azure-identity
  scope: https://api.voicelive.azure.com/.default

endpoints:
  - name: run_audio_test
    method: POST
    path: /evaluations
    parameters:
      - name: dataset_path
      - name: audio_files
```

### Pros & Cons

**Advantages:**
- ✅ Zero credential management (Managed Identity handles it)
- ✅ Minimal code (YAML-driven)
- ✅ Built-in conversation management
- ✅ Auto-scaling and monitoring
- ✅ Native skill discovery
- ✅ Easy deployment

**Disadvantages:**
- ⚠️ Learning Foundry-specific patterns
- ⚠️ Constrained to Foundry capabilities
- ⚠️ Custom logic requires extensions

### Code Required

**Minimal - mostly configuration:**
- Agent definition YAML (~100 lines)
- Connector definitions (~50 lines each)
- Custom workflows (~200 lines)

**Total:** ~500 lines of YAML/config

### Timeline

- Setup: 1-2 days
- Skill integration: 3-4 days
- API connectors: 1 week
- Testing: 1 week
- **Total: 3-4 weeks**

---

## Approach 2: Semantic Kernel + Foundry Hosting

### Overview
Build agent using Microsoft Semantic Kernel framework, deploy to Foundry Agent Service.

### Architecture
```
Semantic Kernel Application (Python/C#)
├── Kernel
│   ├── LLM (Azure OpenAI via Az Identity)
│   ├── Memory (conversation state)
│   └── Planners (auto-workflow)
├── Plugins
│   ├── DatasetValidationPlugin
│   │   └── Wraps dataset_validator scripts
│   ├── VoiceLivePlugin
│   │   └── API client with Azure Identity
│   └── FoundryEvaluationPlugin
│       └── API client with Azure Identity
└── Deployment Package
    └── Foundry-compatible container
```

### Implementation Details

**Plugin Example:**
```python
from semantic_kernel.plugin import kernel_function
from azure.identity import DefaultAzureCredential
import sys
sys.path.append('../dataset_validator')
from validate_dataset_consistency import DatasetConsistencyValidator

class DatasetValidationPlugin:
    """SK plugin wrapping dataset validators."""
    
    @kernel_function(
        name="validate_consistency",
        description="Validates dataset structural integrity"
    )
    def validate_consistency(self, dataset_path: str, expected_turns: int = None) -> dict:
        validator = DatasetConsistencyValidator(
            dataset_path,
            expected_turns=expected_turns
        )
        success = validator.validate()
        return {
            'success': success,
            'errors': validator.errors,
            'warnings': validator.warnings
        }
    
    @kernel_function(
        name="validate_quality",
        description="Validates dataset content quality"
    )
    def validate_quality(self, dataset_path: str, strict: bool = False) -> dict:
        # Similar implementation
        pass

class VoiceLivePlugin:
    """SK plugin for VoiceLive API."""
    
    def __init__(self):
        self.credential = DefaultAzureCredential()
        self.api_base = "https://api.voicelive.azure.com"
    
    @kernel_function(
        name="run_audio_test",
        description="Executes VoiceLive audio evaluation"
    )
    async def run_audio_test(self, dataset_path: str) -> dict:
        # Get Azure AD token
        token = self.credential.get_token("https://api.voicelive.azure.com/.default")
        
        # Make API call with token
        headers = {'Authorization': f'Bearer {token.token}'}
        # ... API call logic
        pass
```

**Kernel Setup:**
```python
from semantic_kernel import Kernel
from azure.identity import DefaultAzureCredential

kernel = Kernel()

# Add Azure OpenAI (with Azure Identity)
credential = DefaultAzureCredential()
kernel.add_chat_service(
    "gpt4",
    AzureChatCompletion(
        deployment_name="gpt-4",
        endpoint="https://your-openai.openai.azure.com",
        credential=credential  # NO API KEY
    )
)

# Register plugins
kernel.import_plugin(DatasetValidationPlugin(), "dataset")
kernel.import_plugin(VoiceLivePlugin(), "voicelive")

# Auto-planning
planner = SequentialPlanner(kernel)
plan = await planner.create_plan("Validate dataset and run evaluation")
result = await plan.invoke()
```

### Pros & Cons

**Advantages:**
- ✅ Powerful auto-planning
- ✅ Rich plugin ecosystem
- ✅ Azure Identity well-supported
- ✅ Flexible and extensible
- ✅ Good documentation

**Disadvantages:**
- ⚠️ ~2000 lines of Python code
- ⚠️ Need to package for Foundry
- ⚠️ More complexity
- ⚠️ Plugin wrapping overhead

### Code Required

- Plugin implementations (~800 lines)
- Kernel setup (~200 lines)
- API clients (~600 lines)
- Deployment config (~400 lines)

**Total:** ~2000 lines Python + config

### Timeline

- SK learning: 1 week
- Plugin development: 2 weeks
- Testing: 1 week
- Foundry packaging: 1 week
- **Total: 5-6 weeks**

---

## Approach 3: LangChain + Foundry Hosting

### Overview
Build with LangChain framework, deploy to Foundry.

### Architecture
```
LangChain Application (Python)
├── LLM (Azure OpenAI + Az Identity)
├── Tools
│   ├── DatasetValidationTool
│   ├── VoiceLiveTool
│   └── FoundryEvalTool
├── Chains (evaluation workflows)
├── Memory (conversation buffer)
└── Agent (ReAct or similar)
```

### Implementation Details

**Tool Wrappers:**
```python
from langchain.tools import Tool
from azure.identity import DefaultAzureCredential
import sys
sys.path.append('../dataset_validator')
from validate_dataset_consistency import DatasetConsistencyValidator

# Tool wrapper
def validate_dataset_consistency_tool(dataset_path: str, expected_turns: int = None):
    """Validates dataset structural integrity."""
    validator = DatasetConsistencyValidator(dataset_path, expected_turns=expected_turns)
    success = validator.validate()
    
    if success:
        return "Dataset consistency validation PASSED."
    else:
        errors_str = "\n".join(validator.errors)
        return f"Dataset validation FAILED:\n{errors_str}"

consistency_tool = Tool(
    name="validate_dataset_consistency",
    func=validate_dataset_consistency_tool,
    description="Validates JSONL dataset for structural integrity. Use BEFORE quality validation."
)

# VoiceLive API tool
class VoiceLiveTool:
    def __init__(self):
        self.credential = DefaultAzureCredential()
    
    def run_audio_test(self, dataset_path: str):
        # Get token
        token = self.credential.get_token("https://api.voicelive.azure.com/.default")
        
        # Make API call
        # ... implementation
        pass

voicelive_tool = Tool(
    name="run_voicelive_test",
    func=VoiceLiveTool().run_audio_test,
    description="Executes VoiceLive audio evaluation tests."
)
```

**Agent Setup:**
```python
from langchain.agents import initialize_agent, AgentType
from langchain_openai import AzureChatOpenAI
from azure.identity import DefaultAzureCredential

# LLM with Azure Identity
credential = DefaultAzureCredential()
# Note: LangChain may require token provider function
llm = AzureChatOpenAI(
    deployment_name="gpt-4",
    azure_endpoint="https://your-openai.openai.azure.com",
    azure_ad_token_provider=lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token
)

# Create agent
agent = initialize_agent(
    tools=[consistency_tool, quality_tool, voicelive_tool],
    llm=llm,
    agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# Use
response = agent.run("Validate the MultiConversationSample dataset")
```

### Pros & Cons

**Advantages:**
- ✅ Rich tooling ecosystem
- ✅ Great for LLM-driven workflows
- ✅ Flexible tool integration
- ✅ Strong community

**Disadvantages:**
- ⚠️ Tool wrapping needed
- ⚠️ ~2500 lines of code
- ⚠️ Packaging for Foundry
- ⚠️ Azure Identity integration less native

### Code Required

- Tool wrappers (~1000 lines)
- API clients (~600 lines)
- Agent setup (~300 lines)
- Chains/workflows (~400 lines)
- Deployment (~200 lines)

**Total:** ~2500 lines Python

### Timeline

- LangChain learning: 1 week
- Tool development: 2 weeks
- Testing: 1 week
- Foundry deployment: 1 week
- **Total: 5-6 weeks**

---

## Approach 4: Hybrid (Foundry + Python Extensions)

### Overview
Primary agent in Foundry, Python extensions for complex logic.

### Architecture
```
Foundry Agent Service (Primary)
├── Core agent (YAML)
├── Skill discovery
└── Extensions API
    ↓
Python Extension Package
├── dataset_validator_wrapper.py
├── voicelive_client.py (Azure Identity)
├── foundry_eval_client.py (Azure Identity)
└── custom_workflows.py
```

### Implementation Details

**Foundry Agent + Extension Interface:**
```yaml
# agent.yaml
name: voicelive-evaluation-agent
skills:
  discovery: auto
extensions:
  - name: voicelive-extension
    type: python
    package: voicelive_agent_ext
    entry: main.py
```

**Python Extension:**
```python
# voicelive_agent_ext/main.py
from azure.identity import DefaultAzureCredential
import sys
sys.path.append('../../dataset_validator')

class VoiceLiveExtension:
    """Python extension for Foundry Agent."""
    
    def __init__(self):
        self.credential = DefaultAzureCredential()
    
    def validate_dataset(self, path: str, mode: str = "default"):
        """Wrapper for dataset validators."""
        # Import and use existing validators
        from validate_dataset_consistency import DatasetConsistencyValidator
        from validate_dataset_quality import DatasetQualityValidator
        
        # Run validations
        consistency = DatasetConsistencyValidator(path)
        if not consistency.validate():
            return {'status': 'failed', 'stage': 'consistency', 'errors': consistency.errors}
        
        quality = DatasetQualityValidator(path, strict=(mode == 'strict'))
        results = quality.validate()
        return results
    
    def run_voicelive_test(self, dataset_path: str):
        """Execute VoiceLive API test with Azure Identity."""
        token = self.credential.get_token("https://api.voicelive.azure.com/.default")
        # API call with token
        pass
    
    def trigger_foundry_eval(self, dataset_path: str):
        """Trigger Foundry evaluation with Azure Identity."""
        token = self.credential.get_token("https://foundry.api.azure.com/.default")
        # API call with token
        pass

# Export functions for Foundry
extension = VoiceLiveExtension()
```

### Pros & Cons

**Advantages:**
- ✅ Managed Foundry service benefits
- ✅ Python for complex logic
- ✅ Direct use of existing validators
- ✅ Flexible and maintainable

**Disadvantages:**
- ⚠️ Need extension package (~1000 lines)
- ⚠️ Understanding both systems
- ⚠️ Extension deployment complexity

### Code Required

- Extension package (~1000 lines)
- API clients (~600 lines)
- Workflow logic (~400 lines)
- Foundry integration (~200 lines)

**Total:** ~2200 lines Python + YAML

### Timeline

- Foundry setup: 1 week
- Extension development: 2 weeks
- Integration: 1 week
- Testing: 1 week
- **Total: 5 weeks**

---

## Comparison Matrix

| Feature | Pure Foundry | Semantic Kernel | LangChain | Hybrid |
|---------|--------------|-----------------|-----------|--------|
| **Code to Maintain** | ~500 lines | ~2000 lines | ~2500 lines | ~2200 lines |
| **Azure Identity Integration** | Native | Good | Moderate | Good |
| **Skill Discovery** | Built-in | Manual | Manual | Built-in |
| **Learning Curve** | Moderate | Steep | Moderate | Steep |
| **Deployment Complexity** | Low | High | High | Moderate |
| **Flexibility** | Moderate | High | High | High |
| **Auto-Planning** | Basic | Excellent | Good | Basic |
| **Production Readiness** | Excellent | Good | Good | Good |
| **Operational Overhead** | Minimal | Moderate | Moderate | Low |
| **Timeline to MVP** | 3-4 weeks | 5-6 weeks | 5-6 weeks | 5 weeks |

---

## Decision Framework

### Choose Pure Foundry (Approach 1) When:

✅ Want minimal code to maintain  
✅ Need production-ready quickly (3-4 weeks)  
✅ Prefer managed service  
✅ Team comfortable with YAML/config-driven development  
✅ Workflows are relatively straightforward  
✅ Want native Azure integration  

**Best for:** Fast deployment, long-term maintainability, production stability

---

### Choose Semantic Kernel (Approach 2) When:

✅ Need powerful auto-planning capabilities  
✅ Have complex multi-step workflows  
✅ Team has SK experience  
✅ Want rich plugin ecosystem  
✅ Need extensive customization  
✅ Can invest 5-6 weeks development  

**Best for:** Complex orchestration, Microsoft stack, auto-planning needs

---

### Choose LangChain (Approach 3) When:

✅ Team has LangChain experience  
✅ Want rich tooling ecosystem  
✅ LLM-first workflow design  
✅ Rapid prototyping important  
✅ Community support valued  
✅ Can invest 5-6 weeks development  

**Best for:** Python-first teams, LLM-heavy workflows, prototyping

---

### Choose Hybrid (Approach 4) When:

✅ Want Foundry benefits + Python flexibility  
✅ Have complex custom logic needs  
✅ May migrate to full Foundry later  
✅ Need both managed service and control  
✅ Can invest 5 weeks development  

**Best for:** Gradual migration, complex custom requirements

---

## Recommendation

### **START WITH APPROACH 1: Pure Foundry Agent Service**

**Reasoning:**

1. **Fastest Time to Value:** 3-4 weeks vs 5-6 weeks
2. **Least Code:** 500 lines vs 2000-2500 lines
3. **Native Azure Identity:** No authentication code needed
4. **Built-in Skill Discovery:** Works with existing `.github/skills/`
5. **Production Ready:** Managed service with auto-scaling
6. **Maintainable:** Minimal code surface area

**Migration Strategy:**

```
Phase 1: Start with Pure Foundry (Approach 1)
  ↓
If limitations discovered:
  ↓
Phase 2: Add Python Extensions (Approach 4 - Hybrid)
  ↓
If still not sufficient:
  ↓
Phase 3: Full SK or LangChain (Approach 2 or 3)
```

**This de-risks development:**
- Start simple and fast
- Add complexity only if needed
- Can always extend later
- Don't over-engineer upfront

---

## Azure Identity Implementation Patterns

### Pattern 1: Managed Identity (Production)

```python
from azure.identity import ManagedIdentityCredential

# System-assigned (preferred)
credential = ManagedIdentityCredential()

# User-assigned (if needed)
credential = ManagedIdentityCredential(client_id="your-identity-id")

# Use with Azure SDK clients
from azure.storage.blob import BlobServiceClient
blob_client = BlobServiceClient(
    account_url="https://storage.blob.core.windows.net",
    credential=credential  # NO KEY
)
```

### Pattern 2: DefaultAzureCredential (Dev/Prod)

```python
from azure.identity import DefaultAzureCredential

# Tries multiple auth methods in order:
# 1. Environment variables
# 2. Managed Identity
# 3. Visual Studio
# 4. Azure CLI
# 5. Interactive browser
credential = DefaultAzureCredential()

# Use with any Azure SDK
token = credential.get_token("https://api.voicelive.azure.com/.default")
```

### Pattern 3: Custom API with Azure AD

```python
from azure.identity import DefaultAzureCredential
import requests

credential = DefaultAzureCredential()

def call_voicelive_api(endpoint: str, data: dict):
    # Get Azure AD token
    token = credential.get_token("https://api.voicelive.azure.com/.default")
    
    # Make API call
    headers = {
        'Authorization': f'Bearer {token.token}',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(
        f"https://api.voicelive.azure.com{endpoint}",
        json=data,
        headers=headers
    )
    return response.json()
```

### Token Refresh Handling

```python
from azure.core.credentials import AccessToken
from datetime import datetime, timedelta

class TokenManager:
    def __init__(self, credential, scope):
        self.credential = credential
        self.scope = scope
        self.token = None
        self.expires_at = None
    
    def get_valid_token(self):
        # Refresh if expired or about to expire
        if not self.token or datetime.now() >= self.expires_at - timedelta(minutes=5):
            access_token = self.credential.get_token(self.scope)
            self.token = access_token.token
            self.expires_at = datetime.fromtimestamp(access_token.expires_on)
        
        return self.token

# Usage
token_mgr = TokenManager(credential, "https://api.voicelive.azure.com/.default")
headers = {'Authorization': f'Bearer {token_mgr.get_valid_token()}'}
```

---

## Next Steps

### 1. Research Phase (1-2 days)

- [ ] Review Foundry Agent Service documentation
- [ ] Understand skill discovery mechanism
- [ ] Check deployment patterns
- [ ] Verify Azure Identity support
- [ ] Identify any limitations

### 2. Prototype Phase (1 week)

- [ ] Create minimal Foundry agent
- [ ] Test skill discovery with dataset_validators
- [ ] Implement Azure Identity authentication
- [ ] Execute simple validation workflow

### 3. Decision Point

Based on prototype results:
- ✅ If Foundry works well → Continue Approach 1
- ⚠️ If limitations found → Consider Approach 4 (Hybrid)
- ❌ If blockers found → Pivot to Approach 2 or 3

---

## Conclusion

**Recommended Path:** Start with **Pure Foundry Agent Service (Approach 1)**

**Key Advantages:**
- Fastest development (3-4 weeks)
- Least code (500 lines)
- Native Azure Identity (no auth code)
- Built-in skill discovery
- Production-ready managed service

**Risk Mitigation:**
- Can add Python extensions if needed (Approach 4)
- Can fully pivot to SK/LangChain if necessary
- Start simple, add complexity only when proven needed

**Next Action:** Begin research phase to validate Foundry Agent Service capabilities.
