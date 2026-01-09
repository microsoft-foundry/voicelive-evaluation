"""
HuggingFace Dataset Audio Processing with Azure VoiceLive API

This script loads audio datasets from HuggingFace and processes them through
Azure VoiceLive API for speech recognition, transcription, and conversation analysis.
"""
import os
import sys
import asyncio
import argparse
import logging
from pathlib import Path
from typing import Union, Optional, Dict, Any, List
from datetime import datetime

## Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv('.\.env', override=True)
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

# Import our custom classes
from prototype_v1.hf_audio_loader import HuggingFaceAudioLoader

# Import VoiceLive classes
try:
    from voicelive_processing import BasicVoiceAssistant, AudioProcessor
    from azure.core.credentials import AzureKeyCredential, TokenCredential
    from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    from azure.ai.voicelive.models import (
        RequestSession, ServerVad, AzureStandardVoice, Modality,
        InputAudioFormat, OutputAudioFormat, AudioInputTranscriptionOptions,
        ServerEventType
    )
    from azure.ai.voicelive.aio import connect
except ImportError as e:
    print(f"❌ Missing Azure VoiceLive dependencies: {e}")
    print("Please install: pip install azure-ai-voicelive")
    sys.exit(1)

# Setup logging
def setup_logging(verbose: bool = False) -> str:
    """Setup logging configuration and return log filename."""
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_filename = f'logs/{timestamp}_hf_voicelive.log'
    
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        filename=log_filename,
        filemode="w",
        format='%(asctime)s:%(name)s:%(levelname)s:%(message)s',
        level=level
    )
    
    # Also log to console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(formatter)
    logging.getLogger().addHandler(console_handler)
    
    return log_filename

logger = logging.getLogger(__name__)


class HFVoiceLiveProcessor:
    """
    Processes HuggingFace audio datasets through Azure VoiceLive API.
    Handles batch processing of audio files with transcription and analysis.
    """
    
    def __init__(self, 
                 endpoint: str,
                 credential: Union[AzureKeyCredential, TokenCredential],
                 model: str = "gpt-realtime",
                 voice: str = "en-US-Ava:DragonHDLatestNeural"):
        
        self.endpoint = endpoint
        self.credential = credential
        self.model = model
        self.voice = voice
        self.hf_loader = HuggingFaceAudioLoader()
        
        # Processing results
        self.results: List[Dict[str, Any]] = []
        self.processed_count = 0
        self.error_count = 0
    
    async def process_dataset(self, 
                            dataset_name: str,
                            split: str = "test",
                            sample_size: Optional[str] = None,
                            max_items: Optional[int] = None,
                            output_file: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Process an entire HuggingFace dataset through VoiceLive API.
        
        Args:
            dataset_name: HuggingFace dataset identifier
            split: Dataset split to process
            sample_size: Sample size (e.g., "10%" or "[:100]")
            max_items: Maximum number of items to process
            output_file: Optional file to save results
            
        Returns:
            List of processing results
        """
        try:
            # Load dataset
            logger.info(f"🔄 Loading dataset: {dataset_name}")
            dataset = self.hf_loader.load_dataset(
                dataset_name=dataset_name,
                split=split,
                sample_size=sample_size,
                decode_audio=False  # We'll handle audio manually
            )
            
            # Show dataset info
            info = self.hf_loader.get_dataset_info()
            logger.info(f"📊 Dataset loaded: {info}")
            
            # Determine processing range
            total_items = len(dataset) if hasattr(dataset, '__len__') else info.get('size', 0)
            if max_items:
                total_items = min(total_items, max_items)
            
            logger.info(f"🎯 Processing {total_items} audio items...")
            
            # Process items
            async for item in self._process_audio_items(total_items):
                self.results.append(item)
                
                # Progress reporting
                self.processed_count += 1
                if self.processed_count % 5 == 0:
                    logger.info(f"✅ Processed {self.processed_count}/{total_items} items")
            
            logger.info(f"🎉 Processing complete!")
            logger.info(f"   Total processed: {self.processed_count}")
            logger.info(f"   Errors: {self.error_count}")
            
            # Save results if requested
            if output_file:
                await self._save_results(output_file)
            
            return self.results
            
        except Exception as e:
            logger.error(f"❌ Dataset processing failed: {e}")
            raise
    
    async def _process_audio_items(self, max_items: int):
        """Process individual audio items through VoiceLive API."""
        
        for i, audio_item in enumerate(self.hf_loader.iterate_audio_items(0, max_items)):
            try:
                logger.debug(f"Processing item {i}: {list(audio_item['metadata'].keys())}")
                
                # Skip if no audio data
                if not audio_item['audio_data']:
                    logger.warning(f"Item {i}: No audio data, skipping")
                    self.error_count += 1
                    continue
                
                # Process through VoiceLive API
                result = await self._process_single_audio(audio_item)
                result['dataset_index'] = i
                
                yield result
                
            except Exception as e:
                logger.error(f"Error processing item {i}: {e}")
                self.error_count += 1
                yield {
                    'dataset_index': i,
                    'error': str(e),
                    'metadata': audio_item.get('metadata', {}),
                    'success': False
                }
    
    async def _process_single_audio(self, audio_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single audio item through VoiceLive API using FileVoiceAssistant.
        
        Args:
            audio_item: Audio item from HuggingFace dataset
            
        Returns:
            Processing results with transcription and analysis
        """
        try:
            # Import FileVoiceAssistant
            from voicelive_processing import FileVoiceAssistant
            
            # Create file voice assistant
            file_assistant = FileVoiceAssistant(
                endpoint=self.endpoint,
                credential=self.credential,
                model=self.model,
                voice=os.getenv("AZURE_VOICELIVE_VOICE", "en-US-Ava:DragonHDLatestNeural"),
                instructions=os.getenv("AZURE_VOICELIVE_INSTRUCTIONS", "You are a helpful AI assistant. Respond naturally and conversationally. Keep your responses concise but engaging.")
            )
            
            # Process audio data through FileVoiceAssistant
            result = await file_assistant.process_audio_data(
                audio_data=audio_item['audio_data'],
                enable_playback=False
            )
            
            # Convert FileVoiceAssistant result to our expected format
            if result['success']:
                return {
                    'success': True,
                    'transcription': {
                        'role': result['role'],
                        'transcript': result['transcription'],
                        'processing_time': 0,  # FileVoiceAssistant doesn't track this yet
                        'parts_count': 1 if result['transcription'] else 0
                    },
                    'metadata': audio_item['metadata'],
                    'audio_size_bytes': len(audio_item['audio_data']) if audio_item['audio_data'] else 0
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Unknown error'),
                    'metadata': audio_item['metadata'],
                    'audio_size_bytes': len(audio_item['audio_data']) if audio_item['audio_data'] else 0
                }
                
        except Exception as e:
            logger.error(f"VoiceLive processing error: {e}")
            return {
                'success': False,
                'error': str(e),
                'metadata': audio_item['metadata'],
                'audio_size_bytes': len(audio_item['audio_data']) if audio_item['audio_data'] else 0
            }
    
    async def _setup_transcription_session(self, connection):
        """Setup VoiceLive session for audio transcription."""
        
        # Configure for transcription-only mode
        session_config = RequestSession(
            turn_detection=ServerVad(threshold=0.3, silence_duration_ms=1000),
            input_audio_transcription=AudioInputTranscriptionOptions(model="gpt-4o-transcribe"),
        )
        
        await connection.session.update(session=session_config)
        logger.debug("Transcription session configured")
    
    async def _transcribe_audio(self, connection, audio_base64: str) -> Dict[str, Any]:
        """
        Send audio to VoiceLive and collect transcription results.
        
        Args:
            connection: VoiceLive connection
            audio_base64: Base64 encoded audio data
            
        Returns:
            Transcription results
        """
        start_time = asyncio.get_event_loop().time()
        transcription_parts = []
        
        try:
            # Send audio data
            await connection.input_audio_buffer.append(audio=audio_base64)
            await connection.input_audio_buffer.commit()
            
            # Listen for transcription events
            async for event in connection:
                if event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                    transcript = event.get('transcript', '')
                    if transcript:
                        transcription_parts.append(transcript)
                        logger.debug(f"Transcription: {transcript}")
                    break
                elif event.type == ServerEventType.ERROR:
                    raise Exception(f"VoiceLive error: {event.error.message}")
            
            processing_time = asyncio.get_event_loop().time() - start_time
            
            return {
                'transcript': ' '.join(transcription_parts),
                'processing_time': processing_time,
                'parts_count': len(transcription_parts)
            }
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
    
    async def _save_results(self, output_file: str):
        """Save processing results to file."""
        import json
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'processing_summary': {
                        'total_processed': self.processed_count,
                        'errors': self.error_count,
                        'success_rate': (self.processed_count - self.error_count) / max(self.processed_count, 1)
                    },
                    'results': self.results
                }, f, indent=2, ensure_ascii=False)
            
            logger.info(f"💾 Results saved to {output_file}")
            
        except Exception as e:
            logger.error(f"Failed to save results: {e}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Process HuggingFace audio datasets through Azure VoiceLive API",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    
    # Dataset arguments
    parser.add_argument(
        "dataset",
        help="HuggingFace dataset name (e.g., 'TwinkStart/llama-questions')",
        type=str
    )
    
    parser.add_argument(
        "--split",
        help="Dataset split to process",
        type=str,
        default="test"
    )
    
    parser.add_argument(
        "--sample-size",
        help="Sample size to process (e.g., '10%' or '[:100]')",
        type=str
    )
    
    parser.add_argument(
        "--max-items",
        help="Maximum number of items to process",
        type=int
    )
    
    # Azure VoiceLive arguments
    parser.add_argument(
        "--api-key",
        help="Azure VoiceLive API key",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_API_KEY"),
    )
    
    parser.add_argument(
        "--endpoint",
        help="Azure VoiceLive endpoint",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_ENDPOINT", "wss://api.voicelive.com/v1"),
    )
    
    parser.add_argument(
        "--model",
        help="VoiceLive model to use",
        type=str,
        default=os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-realtime"),
    )
    
    parser.add_argument(
        "--use-token-credential",
        help="Use Azure token credential instead of API key",
        action="store_true",
        default=False
    )
    
    # Output arguments
    parser.add_argument(
        "--output",
        help="Output file for results (JSON format)",
        type=str
    )
    
    parser.add_argument(
        "--verbose",
        help="Enable verbose logging",
        action="store_true"
    )
    
    return parser.parse_args()


async def main():
    """Main function."""
    args = parse_arguments()
    
    # Setup logging
    log_filename = setup_logging(args.verbose)
    logger.info(f"📝 Logging to: {log_filename}")
    
    # Validate credentials
    if not args.api_key and not args.use_token_credential:
        logger.error("❌ No authentication provided")
        print("Please provide --api-key or set AZURE_VOICELIVE_API_KEY environment variable")
        print("Or use --use-token-credential for Azure authentication")
        sys.exit(1)
    
    try:
        # Setup credential
        credential = DefaultAzureCredential()
        
        # Create processor
        processor = HFVoiceLiveProcessor(
            endpoint=args.endpoint,
            credential=credential,
            model=args.model
        )
        
        print(f"🚀 Starting HuggingFace → VoiceLive processing...")
        print(f"📊 Dataset: {args.dataset}")
        print(f"🔄 Split: {args.split}")
        if args.sample_size:
            print(f"📏 Sample size: {args.sample_size}")
        if args.max_items:
            print(f"🎯 Max items: {args.max_items}")
        
        # Process dataset
        results = await processor.process_dataset(
            dataset_name=args.dataset,
            split=args.split,
            sample_size=args.sample_size,
            max_items=args.max_items,
            output_file=args.output
        )
        
        # Summary
        success_count = sum(1 for r in results if r.get('success', False))
        print(f"\n🎉 Processing Complete!")
        print(f"   ✅ Successful: {success_count}")
        print(f"   ❌ Errors: {len(results) - success_count}")
        
        if args.output:
            print(f"   💾 Results saved: {args.output}")
        
        # Show sample results
        if results and success_count > 0:
            print(f"\n📋 Sample Results:")
            for i, result in enumerate(results[:3]):
                if result.get('success', False):
                    transcript = result.get('transcription', {}).get('transcript', 'N/A')
                    print(f"   {i+1}. {transcript[:100]}...")
        
    except KeyboardInterrupt:
        logger.info("Processing interrupted by user")
        print("\n👋 Processing interrupted. Goodbye!")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Check dependencies
    missing_deps = []
    required_packages = [
        ("datasets", "HuggingFace Datasets"),
        ("azure.ai.voicelive", "Azure VoiceLive SDK"),
        ("azure.core", "Azure Core libraries"),
    ]
    
    for package, description in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing_deps.append(f"{package} ({description})")
    
    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nInstall with: pip install datasets azure-ai-voicelive python-dotenv")
        sys.exit(1)
    
    print("🎙️ HuggingFace Dataset → Azure VoiceLive Processor")
    print("=" * 60)
    
    # Run the processor
    asyncio.run(main())