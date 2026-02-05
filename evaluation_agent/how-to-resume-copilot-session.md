# How to Resume Copilot Session

Quick reference for continuing work on the VoiceLive Evaluation Agent.

## Session State Location

```
C:\Users\jagoerge\.copilot\session-state\ad0bbb13-3b7b-48a3-8bd6-bef5e9ee8112\
├── plan.md              # Current status and next steps
├── checkpoints/         # History of completed work
│   ├── index.md         # Checkpoint list
│   └── 008-*.md         # Latest checkpoint
└── files/               # Session artifacts
```

## To Resume

1. **Start Copilot CLI** in the project directory:
   ```bash
   cd C:\Localrepos\voicelive-evaluation\evaluation_agent_v3
   ```

2. **Tell Copilot to read the plan**:
   ```
   Read the plan.md and latest checkpoint to understand current state
   ```

3. **Or provide specific context**:
   ```
   Continue from checkpoint 008. We were working on Durable Functions 
   for async evaluations in v3.
   ```

## Key Resources

| Resource | Location |
|----------|----------|
| v3 Code | `evaluation_agent_v3/` |
| Functions | `evaluation_agent_v3/deploy/azure-functions/` |
| Bicep | `evaluation_agent_v3/infra/` |
| Agent Setup | `evaluation_agent_v3/setup_agent_openapi.py` |

## Quick Commands

```bash
# Deploy function changes
cd evaluation_agent_v3
azd deploy tools-api --no-prompt

# Update agent
python setup_agent_openapi.py \
  --function-url https://func-v3g7ywvldzjeo.azurewebsites.net/api \
  --connection-name "/subscriptions/2c2e6d10-4e48-40fd-8f4d-d9fb770d0c6d/resourceGroups/rg-jagoerge-voicelive-sec/providers/Microsoft.CognitiveServices/accounts/jagoerge-voicelive-sec-resource/projects/jagoerge-voicelive-sec/connections/voicelive-eval-api-key" \
  --update

# Test in Foundry Portal
# https://ai.azure.com → jagoerge-voicelive-sec → Agents → voicelive-evaluation-agent-cloud
```

## Current State (Feb 4, 2026)

- ✅ v3 deployed with Durable Functions
- ✅ Function Key auth via Foundry Connection
- ✅ 12 functions deployed (including async evaluation)
- 🔄 Next: Documentation + full azd automation
