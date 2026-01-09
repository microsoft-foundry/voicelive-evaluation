"""
HuggingFace Dataset Loader for Audio Processing
Provides a clean interface for loading and managing HF audio datasets.
"""
import os
import base64
from typing import Optional, Dict, Any, Iterator, List
import logging
from datetime import datetime
from datasets import load_dataset, Dataset, Audio
from huggingface_hub import login, HfApi

## Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv('.\.env', override=True)
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

class HuggingFaceAudioLoader:
    """
    Manages HuggingFace dataset loading with audio processing capabilities.
    Handles authentication, dataset loading, and audio data extraction.
    """
    
    def __init__(self, cache_dir: str = "./hf_data_cache"):
        self.cache_dir = cache_dir
        self.token: Optional[str] = None
        self.hf_api: Optional[HfApi] = None
        self.dataset: Optional[Dataset] = None
        self._setup_authentication()
    
    def _setup_authentication(self):
        """Set up HuggingFace authentication."""
        logger.info("🤗 Setting up Hugging Face authentication...")
        
        # Try environment variable first (non-interactive)
        hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
        if hf_token:
            try:
                login(token=hf_token)
                logger.info("✅ Using token from environment variable")
                self.token = hf_token
            except Exception as e:
                logger.error(f"❌ Failed to login with environment token: {e}")
                self.token = None
        else:
            # Try stored token from `huggingface-cli login`
            try:
                login(add_to_git_credential=False)  # Don't prompt if no token exists
                logger.info("✅ Using stored Hugging Face token")
            except Exception as e:
                logger.warning("ℹ️  No stored token found")
                logger.info("   To avoid rate limiting, you can:")
                logger.info("   1. Set HF_TOKEN environment variable")
                logger.info("   2. Run 'huggingface-cli login'")
        
        # Initialize HF API
        self.hf_api = HfApi()
        if not self.token:
            self.token = getattr(self.hf_api, 'token', None)
    
    def load_dataset(self, dataset_name: str, split: str = "test", 
                    sample_size: Optional[str] = None, decode_audio: bool = False) -> Dataset:
        """
        Load a HuggingFace dataset with audio support.
        
        Args:
            dataset_name: Name of the HuggingFace dataset
            split: Dataset split to load (train/test/validation)
            sample_size: Optional sample size (e.g., "10%" or "[:100]")
            decode_audio: Whether to decode audio automatically (requires FFmpeg/TorchCodec)
            
        Returns:
            Loaded dataset
        """
        try:
            # Construct split string
            split_str = split
            if sample_size:
                if sample_size.endswith('%'):
                    split_str = f"{split}[:{sample_size}]"
                elif sample_size.startswith('[') and sample_size.endswith(']'):
                    split_str = f"{split}{sample_size}"
                else:
                    # Treat as number of samples
                    split_str = f"{split}[:{sample_size}]"
            
            logger.info(f"Loading dataset: {dataset_name}, split: {split_str}")
            
            # Load dataset
            self.dataset = load_dataset(
                dataset_name,
                cache_dir=self.cache_dir,
                split=split_str,
                token=self.token
            )
            
            # Configure audio decoding
            if not decode_audio and 'audio' in self.dataset.features:
                logger.info("Disabling automatic audio decoding to avoid TorchCodec issues")
                self.dataset = self.dataset.cast_column("audio", Audio(decode=False))
            
            logger.info(f"✅ Dataset loaded: {len(self.dataset)} samples")
            logger.info(f"📋 Columns: {self.dataset.column_names}")
            
            return self.dataset
            
        except Exception as e:
            logger.error(f"❌ Failed to load dataset {dataset_name}: {e}")
            raise
    
    def get_audio_item(self, index: int) -> Dict[str, Any]:
        """
        Get a single audio item from the dataset.
        
        Args:
            index: Index of the item to retrieve
            
        Returns:
            Dictionary containing audio data and metadata
        """
        if not self.dataset:
            raise ValueError("No dataset loaded. Call load_dataset() first.")
        
        if index >= len(self.dataset):
            raise IndexError(f"Index {index} out of range for dataset of size {len(self.dataset)}")
        
        item = self.dataset[index]
        
        # Handle audio data
        audio_data = None
        if 'audio' in item:
            audio_info = item['audio']
            if isinstance(audio_info, dict):
                # Audio metadata without decoding
                if 'bytes' in audio_info and audio_info['bytes']:
                    audio_data = audio_info['bytes']
                elif 'path' in audio_info:
                    # Try to read audio file directly
                    try:
                        with open(audio_info['path'], 'rb') as f:
                            audio_data = f.read()
                    except Exception as e:
                        logger.warning(f"Could not read audio file {audio_info['path']}: {e}")
        
        result = {
            'index': index,
            'audio_data': audio_data,
            'metadata': {k: v for k, v in item.items() if k != 'audio'},
            'raw_item': item
        }
        
        return result
    
    def get_audio_base64(self, index: int) -> Optional[str]:
        """
        Get audio data as base64 string for API transmission.
        
        Args:
            index: Index of the audio item
            
        Returns:
            Base64 encoded audio data or None if no audio
        """
        item = self.get_audio_item(index)
        if item['audio_data']:
            return base64.b64encode(item['audio_data']).decode('utf-8')
        return None
    
    def iterate_audio_items(self, start: int = 0, end: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        """
        Iterate through audio items in the dataset.
        
        Args:
            start: Starting index
            end: Ending index (exclusive), None for all remaining
            
        Yields:
            Audio items with metadata
        """
        if not self.dataset:
            raise ValueError("No dataset loaded. Call load_dataset() first.")
        
        if end is None:
            end = len(self.dataset)
        
        for i in range(start, min(end, len(self.dataset))):
            try:
                yield self.get_audio_item(i)
            except Exception as e:
                logger.error(f"Error processing item {i}: {e}")
                continue
    
    def get_dataset_info(self) -> Dict[str, Any]:
        """Get information about the loaded dataset."""
        if not self.dataset:
            return {"error": "No dataset loaded"}
        
        info = {
            "size": len(self.dataset),
            "columns": self.dataset.column_names,
            "features": {k: str(v) for k, v in self.dataset.features.items()},
        }
        
        # Check for audio column
        if 'audio' in self.dataset.features:
            audio_feature = self.dataset.features['audio']
            info["audio_config"] = {
                "sampling_rate": getattr(audio_feature, 'sampling_rate', None),
                "decode": getattr(audio_feature, 'decode', None)
            }
        
        return info


# Standalone usage example
if __name__ == "__main__":
    import logging
from pydub import AudioSegment
from pydub.playback import play
import io

# Standalone usage example
if __name__ == "__main__":
# Setup logging
    if not os.path.exists('logs'):
        os.makedirs('logs')

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f'logs/{timestamp}_hf_voicelive.log'

    level = logging.DEBUG
    logging.basicConfig(
        filename=log_filename,
        filemode="w",
        format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
        level=level
    )

    logger = logging.getLogger(__name__)

# Create loader and test
loader = HuggingFaceAudioLoader()

# Standalone usage example
if __name__ == "__main__":
    dataset_name = "TwinkStart/llama-questions"
    # dataset_name = "TwinkStart/speech-web-questions"
    # dataset_name = "TwinkStart/speech-triavia-qa"
    audio_data_folder = "local_datasets"

try:
    # Load dataset
    # dataset = loader.load_dataset(f"{dataset_name}", split="test", sample_size="10%")
    dataset = loader.load_dataset(f"{dataset_name}", sample_size="100%")
    print(f"✅ Successfully loaded dataset: {dataset}")
    
    # Show dataset info
    info = loader.get_dataset_info()
    print(f"📊 Dataset Info: {info}")
    
    # Collect all items for combined JSONL file
    all_jsonl_records = []
    
    # Test getting a few audio items
    for i, item in enumerate(loader.iterate_audio_items(start=0, end=None)):
        print(f"\n🎵 Item {i}:")
        print(f"  Metadata: {list(item['metadata'].keys())}")
        print(f"  Has audio: {'Yes' if item['audio_data'] else 'No'}")
        if item['audio_data']:
            print(f"  Audio size: {len(item['audio_data'])} bytes")
            # Standalone usage example
            if __name__ == "__main__":
                # # Play audio using pydub
                # audio_segment = AudioSegment.from_file(io.BytesIO(item['audio_data']))
                # print(f"  Playing audio (duration: {len(audio_segment)}ms)...")
                # play(audio_segment)
                # Alternatively, save to file
                if not os.path.exists(f"./{audio_data_folder}/{dataset_name}/wav"):
                    os.makedirs(f"./{audio_data_folder}/{dataset_name}/wav")
                # if not os.path.exists(f"./{audio_data_folder}/{dataset_name}/json"):
                #     os.makedirs(f"./{audio_data_folder}/{dataset_name}/json")
                with open(f"./{audio_data_folder}/{dataset_name}/wav/{i}.wav", "wb") as f:
                    f.write(item['audio_data'])
                print(f"  Audio saved to ./audio_data/{dataset_name}/wav/{i}.wav")
                # Save QuestionText and AnswerText to a json file named with the same basename as the audio file and include a key with the audio filename if available
                import json
                
                # Define paths for JSONL record
                wav_filename = f"{i}.wav"
                wav_path = os.path.abspath(f"./{audio_data_folder}/{dataset_name}/wav/{wav_filename}")
                
                if dataset_name == "TwinkStart/llama-questions":
                    # json_data = {
                    #     "QuestionText": item['metadata'].get('Questions', ''),
                    #     "AnswerText": item['metadata'].get('Answer', ''),
                    #     "AudioFilename": wav_filename
                    # }
                    # Create JSONL record with combined structure
                    jsonl_record = {
                        "WavPath": wav_path,
                        "Question": item['metadata'].get('Questions', ''),
                        "Answer": item['metadata'].get('Answer', ''),
                        "Wav Filename": wav_filename
                    }
                elif dataset_name == "TwinkStart/speech-web-questions":
                    # json_data = {
                    #     "QuestionText": item['metadata'].get('question', ''),
                    #     "AnswerText": item['metadata'].get('answers', ''),
                    #     "AudioFilename": wav_filename
                    # }
                    # Create JSONL record with combined structure
                    jsonl_record = {
                        "WavPath": wav_path,
                        "Question": item['metadata'].get('question', ''),
                        "Answer": item['metadata'].get('answers', ''),
                        "Wav Filename": wav_filename
                    }
                elif dataset_name == "TwinkStart/speech-triavia-qa":
                    #  json_data = {
                    #     "QuestionText": item['metadata'].get('question', ''),
                    #     "AnswerText": item['metadata'].get('answer', ''),
                    #     "AudioFilename": wav_filename
                    # }
                     # Create JSONL record with combined structure
                     jsonl_record = {
                        "WavPath": wav_path,
                        "Question": item['metadata'].get('question', ''),
                        "Answer": item['metadata'].get('answer', ''),
                        "Wav Filename": wav_filename
                    }
                
                # Add record to list for combined JSONL
                all_jsonl_records.append(jsonl_record)
                
                # with open(f"./{audio_data_folder}/{dataset_name}/json/{i}.json", "w") as jf:
                #     json.dump(json_data, jf, indent=4)
                # print(f"  Metadata saved to ./audio_data/{dataset_name}/json/{i}.json")
    
    # Write combined JSONL file with all dataset elements
    if all_jsonl_records:
        jsonl_filename = f"{dataset_name.replace('/', '-')}.jsonl"
        jsonl_output_path = f"./{audio_data_folder}/{dataset_name}/{jsonl_filename}"
        with open(jsonl_output_path, "w", encoding="utf-8") as jsonl_file:
            for record in all_jsonl_records:
                jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\n✅ Combined JSONL file saved to {jsonl_output_path} ({len(all_jsonl_records)} records)")
    
except Exception as e:
    print(f"❌ Test failed: {e}")