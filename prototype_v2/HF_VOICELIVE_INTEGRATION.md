# HuggingFace Dataset → Azure VoiceLive Integration

This integration allows you to process audio datasets from HuggingFace through the Azure VoiceLive API for speech recognition, transcription, and conversation analysis.

## 📁 Files Location

All integration files are located in the `prototype_v2/` folder:

1. **`prototype_v2/hf_audio_loader.py`** - Refactored HuggingFace dataset loader as a reusable class
2. **`prototype_v2/hf_dataset_run_on_vl.py`** - Main integration script that processes HF datasets through VoiceLive API
3. **`prototype_v2/test_hf_integration.py`** - Test script to verify the integration works
4. **`prototype_v2/voicelive_processing.py`** - Azure VoiceLive API processing classes
5. **`prototype_v2/huggingface_datasets.py`** - Original HF dataset utilities (updated)

## 🚀 Quick Start

### 1. Setup Environment Variables

```bash
# In your .env file
HF_TOKEN=your_huggingface_token_here
AZURE_VOICELIVE_API_KEY=your_azure_voicelive_key_here
AZURE_VOICELIVE_ENDPOINT=wss://api.voicelive.com/v1
```

### 2. Test the Integration

```bash
# Navigate to prototype_v2 folder and verify everything works
cd prototype_v2
python test_hf_integration.py
```

### 3. Process a Dataset

```bash
# Basic usage - process 3 samples from the test dataset
cd prototype_v2
python hf_dataset_run_on_vl.py TwinkStart/llama-questions --sample-size 3

# Process with custom parameters
python hf_dataset_run_on_vl.py TwinkStart/llama-questions \
    --split test \
    --sample-size "10%" \
    --max-items 50 \
    --output results.json \
    --verbose

# Using Azure token credential instead of API key
python hf_dataset_run_on_vl.py TwinkStart/llama-questions \
    --use-token-credential \
    --sample-size 5
```

## 🔧 Usage Examples

### Processing Different Datasets

```bash
# Process CommonVoice dataset
python hf_dataset_run_on_vl.py mozilla-foundation/common_voice_11_0 \
    --split "test" \
    --sample-size "1%" \
    --output commonvoice_results.json

# Process LibriSpeech dataset  
python hf_dataset_run_on_vl.py librispeech_asr \
    --split "test.clean" \
    --sample-size "[:100]" \
    --output librispeech_results.json
```

### Batch Processing

```bash
# Process multiple small batches (from prototype_v2 folder)
cd prototype_v2
python hf_dataset_run_on_vl.py TwinkStart/llama-questions --max-items 10 --output batch1.json
python hf_dataset_run_on_vl.py TwinkStart/llama-questions --max-items 10 --output batch2.json
```

## 📊 Output Format

The script generates JSON output with the following structure:

```json
{
  "processing_summary": {
    "total_processed": 5,
    "errors": 0,
    "success_rate": 1.0
  },
  "results": [
    {
      "success": true,
      "transcription": {
        "transcript": "What is the capital of France?",
        "processing_time": 1.23,
        "parts_count": 1
      },
      "metadata": {
        "Questions": "What is the capital of France?",
        "Answer": "Paris",
        "Wav Filename": "1.wav",
        "WavPath": "1.wav",
        "QuestionText": "What is the capital of France?"
      },
      "audio_size_bytes": 64758,
      "dataset_index": 0
    }
  ]
}
```

## 🛠️ Architecture

### HuggingFaceAudioLoader Class

- **Authentication**: Handles HF token authentication automatically
- **Dataset Loading**: Loads datasets with configurable audio decoding
- **Audio Processing**: Extracts audio data and converts to base64 for API transmission
- **Iteration**: Provides efficient iteration over large datasets

### HFVoiceLiveProcessor Class

- **VoiceLive Integration**: Connects to Azure VoiceLive API
- **Batch Processing**: Handles multiple audio files efficiently
- **Error Handling**: Robust error handling with detailed logging
- **Results Management**: Collects and saves processing results

## 🔍 Features

### ✅ Implemented

- **HuggingFace Authentication**: Automatic token handling
- **Dataset Loading**: Support for any HF audio dataset
- **Audio Processing**: Base64 encoding for API transmission
- **VoiceLive Integration**: Full transcription pipeline
- **Batch Processing**: Efficient processing of multiple files
- **Error Handling**: Robust error handling and logging
- **Progress Tracking**: Real-time progress reporting
- **Results Export**: JSON output with detailed results

### 🚧 Future Enhancements

- **Real-time Streaming**: Process audio streams in real-time
- **Advanced Analysis**: Sentiment analysis, speaker identification
- **Multiple Output Formats**: CSV, Excel, database integration
- **Parallel Processing**: Multi-threaded processing for large datasets
- **Custom Models**: Support for custom VoiceLive models

## 🐛 Troubleshooting

### Common Issues

1. **FFmpeg Errors**: Install FFmpeg if you need to decode audio files
   ```bash
   choco install ffmpeg  # Windows
   brew install ffmpeg   # macOS
   ```

2. **Authentication Errors**: Ensure your tokens are set correctly
   ```bash
   # Check if tokens are set
   echo $HF_TOKEN
   echo $AZURE_VOICELIVE_API_KEY
   ```

3. **Dataset Not Found**: Verify the dataset name and split exist
   ```python
   from datasets import get_dataset_infos
   infos = get_dataset_infos("dataset-name")
   print(infos)
   ```

### Debug Mode

Enable verbose logging to see detailed processing information:

```bash
python hf_dataset_run_on_vl.py TwinkStart/llama-questions --verbose --sample-size 1
```

## 📈 Performance

- **Typical Processing Speed**: 1-3 audio files per second
- **Memory Usage**: ~100MB base + dataset size
- **Network**: Depends on audio file sizes and API latency

## 🤝 Contributing

The integration is modular and extensible:

1. **Add new datasets**: Modify `hf_audio_loader.py` for custom audio formats
2. **Enhance processing**: Extend `HFVoiceLiveProcessor` for additional analysis
3. **Output formats**: Add new export formats in the results saving logic

---

**Ready to process your audio datasets!** 🎙️✨