# Open Ideas for Voice Agent Evaluation

This document tracks potential enhancements and ideas for future development.

## Parallel Processing / Multi-Worker Support

**Status:** Not Implemented  
**Priority:** High (for large dataset processing)

### Problem
The current `voice_agent_audio_input_evaluation_v2.py` script processes files sequentially, which is slow for large datasets (e.g., BingChat_AgentTestSet_FY26 with 3000+ files).

### Current Limitations
- Single WebSocket connection per session
- Global state variables (`response_complete_event`, `current_metrics`, `current_turn_number`, etc.)
- No `--workers` command line argument

### Proposed Solutions

#### Option 1: External Parallelism (Quick Win)
Create a helper script to split datasets and run multiple script instances:

```powershell
# Split dataset into N chunks
python split_dataset.py --input dataset.jsonl --chunks 4

# Run in parallel (separate terminals or background jobs)
python voice_agent_audio_input_evaluation_v2.py --test-files chunk1.jsonl --output-dir ./output/chunk1 --session-mode per-file
python voice_agent_audio_input_evaluation_v2.py --test-files chunk2.jsonl --output-dir ./output/chunk2 --session-mode per-file
python voice_agent_audio_input_evaluation_v2.py --test-files chunk3.jsonl --output-dir ./output/chunk3 --session-mode per-file
python voice_agent_audio_input_evaluation_v2.py --test-files chunk4.jsonl --output-dir ./output/chunk4 --session-mode per-file

# Merge results
python merge_results.py --input-dirs ./output/chunk* --output ./output/merged
```

**Pros:** No changes to main script, easy to implement  
**Cons:** Manual coordination, separate output directories, separate evaluation metrics

#### Key Consideration: Deferred Evaluation

Each parallel run currently triggers its own evaluation, making metrics hard to consolidate. The solution requires:

1. **Add `--skip-evaluation` flag** to the main script to only collect Voice Live responses without running evaluation
2. **Merge JSONL files** from all parallel runs into a single evaluation input file
3. **Run evaluation once** on the merged file via external script

```powershell
# Parallel collection (no evaluation)
python voice_agent_audio_input_evaluation_v2.py --test-files chunk1.jsonl --output-dir ./output/chunk1 --session-mode per-file --skip-evaluation
python voice_agent_audio_input_evaluation_v2.py --test-files chunk2.jsonl --output-dir ./output/chunk2 --session-mode per-file --skip-evaluation
# ... more workers

# After all workers complete: merge and evaluate
python merge_results.py --input-dirs ./output/chunk* --output ./output/merged
python voice_agent_evaluation_v1.py --input ./output/merged/merged_results.jsonl --output ./output/merged
```

**Implementation Steps:**
1. Add `--skip-evaluation` argument to `voice_agent_audio_input_evaluation_v2.py`
2. Create `split_dataset.py` to divide JSONL into N chunks
3. Create `merge_results.py` to combine JSONL outputs from parallel runs
4. Create `parallel_runner.py` orchestrator script that:
   - Splits the dataset
   - Spawns N parallel processes with `--skip-evaluation`
   - Waits for all to complete
   - Merges results
   - Runs single evaluation on merged output

#### Option 2: Built-in `--workers N` Flag (Larger Refactoring)
Add native parallel processing support:

```bash
python voice_agent_audio_input_evaluation_v2.py \
  --test-files dataset.jsonl \
  --output-dir ./output \
  --session-mode per-file \
  --workers 4
```

**Implementation Requirements:**
1. Use `multiprocessing.Pool` or `concurrent.futures.ProcessPoolExecutor`
2. Encapsulate all global state into a per-worker context class
3. Each worker needs its own WebSocket connection
4. Implement result aggregation from worker processes
5. Handle worker failures and retries

**Estimated Effort:** Medium-High

---

## Other Ideas

### Retry Logic for Failed Files
- Add `--retry-failed` flag to re-process files that failed in a previous run
- Read from operational summary to identify failures

### Progress Reporting
- Add progress bar (tqdm) for large datasets
- Estimated time remaining based on average processing time

### Batch API Support
- Investigate if Voice Live API supports batch processing
- Could be more efficient than individual WebSocket sessions

---

*Last Updated: 2025-11-26*
