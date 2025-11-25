## Open Issues

### Platform-Specific Issues
- Cross-Platform Windows multi-threading support not working properly
- Huggingface data download does not happen on Windows (works on mac)

### Feature Enhancements
- Update to latest Voice live processing best practice TBD
- Add logger info messages for foundry evaluation processing
- Make Foundry eval name dynamic based on dataset evaluator model used

## Recently Resolved Issues

### ✅ Fixed: Groundedness and ResponseCompleteness Evaluator Data Handling (Nov 24, 2025)
**Issue**: Context vs Ground Truth confusion in Azure AI Foundry evaluators
- Groundedness was incorrectly falling back to ground_truth when context was missing
- This caused semantic confusion: evaluating if response is grounded in the expected answer instead of RAG documents

**Resolution**:
- **Groundedness**: Now requires `context` field (RAG documents), raises ValueError with clear message if missing
- **ResponseCompleteness**: Correctly uses `ground_truth` field with fallback to label (expected answer)
- **Multi/Batch Evaluators**: No longer use ground_truth as context fallback, use empty string instead
- Added validation and warning messages for missing required fields

**Impact**:
- Groundedness evaluator only works with RAG datasets that have actual retrieved context
- ResponseCompleteness works with any QA dataset (RAG or non-RAG)
- Clear error messages guide users to use correct evaluators for their dataset type
- No more silent fallbacks producing semantically incorrect evaluations