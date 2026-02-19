# Voice Agent Audio Input Evaluation — Architecture

*Last updated: February 19, 2026*

## Overview

Single-file CLI tool that processes pre-recorded audio through Azure VoiceLive SDK for evaluation.
Pure async Python — no threading, no legacy wrappers.
Aligned with the cloud container-app implementation in `evaluation_agent/deploy/container-app/`.

## Component Architecture

```mermaid
flowchart TD
    CLI["CLI args (argparse)"] --> main["main()"]
    main --> main_async["main_async(args)"]
    main_async --> read["Read dataset JSONL"]
    read --> group["Group entries by conversation_id"]
    group --> loop["For each conversation"]
    loop --> connect["Create VoiceLive connection"]
    connect --> configure["configure_session(connection, config)"]
    configure --> process_conv["process_conversation(entries, connection, config, output_dir)"]
    process_conv --> turn_loop["For each DatasetEntry"]
    turn_loop --> load["Load audio WAV file"]
    load --> process["process_audio(connection, audio_data, config, push_to_talk, ...)"]
    process --> collect["Collect ConversationTurn data"]
    collect --> turn_loop
    process_conv --> write["Write results to JSONL"]
```

## Data Model

```mermaid
classDiagram
    class SessionConfig {
        +str instructions
        +str model
        +str voice
        +str voice_type
        +int sample_rate
        +bool push_to_talk
        +Optional~List~ tools
        +Optional~List~ tool_definitions
    }
    class ConversationTurn {
        +int turn_number
        +str user_transcription
        +str assistant_response
        +bool assistant_audio_received
        +List~Dict~ tool_calls
        +List~Dict~ tool_results
        +Optional~datetime~ audio_send_end_time
        +Optional~datetime~ transcription_complete_time
        +Optional~datetime~ first_text_response_time
        +Optional~datetime~ first_audio_response_time
    }
    class DatasetEntry {
        +str audio_path
        +Optional~str~ ground_truth
        +Optional~str~ question
        +Optional~List~ tool_definitions
        +str conversation_id
        +Optional~str~ system_prompt
    }
    DatasetEntry --> SessionConfig : configures
    SessionConfig --> ConversationTurn : produces
```

## VAD Mode Processing Flow

```mermaid
flowchart TD
    start([Start VAD Mode]) --> conn["Create connection"]
    conn --> cfg["configure_session\n(turn_detection = AzureSemanticVad)"]
    cfg --> prep["Prepare silence_chunk\n(zero-filled audio frame)"]
    prep --> concurrent["Start concurrent tasks"]
    concurrent --> send["send_audio()\naudio chunks + asyncio.sleep(0.02)"]
    concurrent --> silence["send_silence()\nwait for audio_send_complete\nthen send silent frames every 100ms"]
    concurrent --> events["Event collection loop"]

    events --> check{Event type?}
    check --> |SESSION_CREATED| log1["Log session ID"]
    check --> |SPEECH_STARTED| log2["Log VAD speech start"]
    check --> |SPEECH_STOPPED| stop_silence["Cancel silence_task\nRecord timing"]
    check --> |TRANSCRIPTION_COMPLETED| store_tx["Store user_transcription"]
    check --> |CONVERSATION_ITEM_CREATED| capture_id["Capture function_call item ID\nas pending_tool_item_id"]
    check --> |RESPONSE_TEXT_DELTA| buf_text["Buffer text_buffer"]
    check --> |RESPONSE_TEXT_DONE| fin_text["Finalize assistant_response"]
    check --> |RESPONSE_AUDIO_TRANSCRIPT_DELTA| buf_audio["Buffer audio_transcript_buffer"]
    check --> |RESPONSE_AUDIO_TRANSCRIPT_DONE| fin_audio["Finalize assistant_response"]
    check --> |RESPONSE_AUDIO_DELTA| rec_time["Record first_audio_response_time"]
    check --> |FUNCTION_CALL_ARGUMENTS_DONE| store_tool["Store pending_tool_call"]
    check --> |RESPONSE_DONE| done_check{"pending_tool_call?"}
    check --> |ERROR| err["Log error and break"]

    done_check --> |Yes| exec_tool["_execute_and_send_tool_result()\ncontinue collecting"]
    done_check --> |No| drain["_drain_late_events()\n(up to 2 seconds)"]
    drain --> cancel["Cancel send/silence tasks"]
    cancel --> ret([Return ConversationTurn])

    log1 --> events
    log2 --> events
    stop_silence --> events
    store_tx --> events
    capture_id --> events
    buf_text --> events
    fin_text --> events
    buf_audio --> events
    fin_audio --> events
    rec_time --> events
    store_tool --> events
    exec_tool --> events
```

## PTT Mode Processing Flow

```mermaid
flowchart TD
    start([Start PTT Mode]) --> conn["Create connection"]
    conn --> cfg["configure_session\n(turn_detection = AzureSemanticVad)\nNote: VoiceLive requires turn_detection"]
    cfg --> send["Send all audio chunks synchronously\nawait connection.input_audio_buffer.append()\nawait asyncio.sleep(0.02)"]
    send --> timing["Record audio_send_end_time"]
    timing --> commit["await connection.input_audio_buffer.commit()"]
    commit --> create["await connection.response.create()"]
    create --> events["Event collection loop\n(same handlers as VAD)"]

    events --> check{Event type?}
    check --> |SESSION_CREATED| log1["Log session ID"]
    check --> |TRANSCRIPTION_COMPLETED| store_tx["Store user_transcription"]
    check --> |CONVERSATION_ITEM_CREATED| capture_id["Capture function_call item ID"]
    check --> |RESPONSE_TEXT_DELTA| buf_text["Buffer text"]
    check --> |RESPONSE_TEXT_DONE| fin_text["Finalize text response"]
    check --> |RESPONSE_AUDIO_TRANSCRIPT_DELTA| buf_audio["Buffer audio transcript"]
    check --> |RESPONSE_AUDIO_TRANSCRIPT_DONE| fin_audio["Finalize audio response"]
    check --> |RESPONSE_AUDIO_DELTA| rec_time["Record timing"]
    check --> |FUNCTION_CALL_ARGUMENTS_DONE| store_tool["Store pending_tool_call"]
    check --> |RESPONSE_DONE| done_check{"pending_tool_call?"}
    check --> |ERROR| err["Log error and break"]

    done_check --> |Yes| exec_tool["_execute_and_send_tool_result()\ncontinue collecting"]
    done_check --> |No| drain["_drain_late_events()"]
    drain --> ret([Return ConversationTurn])

    log1 --> events
    store_tx --> events
    capture_id --> events
    buf_text --> events
    fin_text --> events
    buf_audio --> events
    fin_audio --> events
    rec_time --> events
    store_tool --> events
    exec_tool --> events
```

## Tool Call Handling Flow

```mermaid
sequenceDiagram
    participant SDK as VoiceLive SDK
    participant Script as process_audio()
    participant Registry as Tool Registry

    SDK->>Script: CONVERSATION_ITEM_CREATED (type=function_call)
    Note right of Script: Capture item.id as pending_tool_item_id

    SDK->>Script: RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE
    Note right of Script: Store event as pending_tool_call<br/>Append to turn.tool_calls

    SDK->>Script: RESPONSE_DONE
    Note right of Script: Detected pending_tool_call is not None

    Script->>Registry: execute_tool(name, arguments)
    Registry-->>Script: result_text

    Note right of Script: Append to turn.tool_results

    Script->>SDK: conversation.item.create(<br/>FunctionCallOutputItem(call_id, output),<br/>previous_item_id=pending_tool_item_id)
    Script->>SDK: response.create()

    Note over SDK,Script: Collect follow-up response events

    SDK->>Script: RESPONSE_TEXT_DELTA / RESPONSE_AUDIO_TRANSCRIPT_DELTA
    SDK->>Script: RESPONSE_DONE (final)
    Note right of Script: No pending tool → drain late events → return
```

## Event Handling

| Event | Handler | Purpose |
|-------|---------|---------|
| `SESSION_CREATED` | Log session ID | Connection confirmation |
| `INPUT_AUDIO_BUFFER_SPEECH_STARTED` | Log | VAD detected speech |
| `INPUT_AUDIO_BUFFER_SPEECH_STOPPED` | Cancel silence task, record timing | VAD detected end of speech |
| `CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED` | Store `user_transcription` | Speech-to-text done |
| `CONVERSATION_ITEM_CREATED` | Capture function_call item ID | Tool call detection |
| `RESPONSE_TEXT_DELTA` | Buffer `text_buffer` | Streaming text response |
| `RESPONSE_TEXT_DONE` | Finalize `assistant_response` | Text complete |
| `RESPONSE_AUDIO_TRANSCRIPT_DELTA` | Buffer `audio_transcript_buffer` | Streaming audio transcript |
| `RESPONSE_AUDIO_TRANSCRIPT_DONE` | Finalize `assistant_response` | Audio transcript complete |
| `RESPONSE_AUDIO_DELTA` | Record `first_audio_response_time` | Audio data timing (not saved) |
| `RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE` | Store `pending_tool_call` | Tool arguments ready |
| `RESPONSE_DONE` | Execute tool or drain late events, break | Turn complete |
| `ERROR` | Log and break | Error handling |

## Late Event Drain

After `RESPONSE_DONE`, `_drain_late_events()` waits up to 2 seconds for late-arriving events:

- Transcription events that arrive after response completion
- Additional text/audio transcript deltas
- Uses longest response (max of text vs audio transcript) to avoid truncation

## Design Decisions

### 1. Pure Async (No Threading)

Old prototype used threading (background event loop + main thread orchestration).
New: pure `async`/`await` — simpler, fewer race conditions.

### 2. VAD Always Required

VoiceLive SDK requires `turn_detection` to be set. Setting `None` breaks sessions.
PTT mode keeps VAD configured but adds `commit()` + `response.create()`.

### 3. Tool Execution After RESPONSE_DONE

Official SDK sample pattern. Executing during response stream causes issues.
Wait for `RESPONSE_DONE` → execute → send result → request follow-up.

### 4. Silence Keepalive (VAD Only)

After audio send completes, `send_silence()` sends zero-filled frames every 100ms to keep VAD active.
Without this, VAD may time out before response is complete.
PTT doesn't need this since it uses explicit `commit()`/`create()`.

### 5. Single-File Architecture

Unlike the container-app (split into client/processor/config/storage/jobs),
the prototype keeps everything in one file for ease of use and portability.

## Known Platform Limitations

1. `turn_detection=None` not supported — breaks sessions entirely
2. PTT achieves 4/6 vs VAD 6/6 due to VAD interference on early turns
3. No official SDK sample for PTT or pre-recorded audio processing
4. Tool definitions as single dict silently ignored — normalize to list

## Comparison with Container App

| Aspect | Prototype | Container App |
|--------|-----------|---------------|
| Architecture | Single file CLI | FastAPI service (4+ modules) |
| Storage | Local filesystem | Azure Blob Storage |
| Job management | None | Async job queue |
| Concurrency | Sequential conversations | Configurable workers |
| Audio source | Local WAV files | Blob-downloaded WAV |
| Output | Local JSONL | Blob-uploaded JSONL |
| Core patterns | Identical | Identical |
| SDK integration | Identical | Identical |
| PTT/VAD | Identical | Identical |
| Tool handling | Identical | Identical |
