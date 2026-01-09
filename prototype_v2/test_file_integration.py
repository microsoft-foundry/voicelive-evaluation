"""
Test script to demonstrate FileVoiceAssistant with HuggingFace audio data
"""
import os
import sys
import asyncio
import logging
from azure.identity import DefaultAzureCredential

## Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv('.\.env', override=True)
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

from prototype_v1.hf_audio_loader import HuggingFaceAudioLoader
from voicelive_processing import FileVoiceAssistant
from azure.core.credentials import AzureKeyCredential

async def test_hf_file_integration():
    """Test FileVoiceAssistant with HuggingFace audio data."""
    print("🧪 Testing HuggingFace + FileVoiceAssistant Integration")
    print("=" * 60)
    
    # Setup logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Check credentials
    # Create client with appropriate credential
    credential = DefaultAzureCredential() 
    endpoint = os.getenv('AZURE_VOICELIVE_ENDPOINT', 'wss://api.voicelive.com/v1')
    try:
        # Load HuggingFace audio data
        print("\n📊 Loading HuggingFace dataset...")
        loader = HuggingFaceAudioLoader()
        dataset = loader.load_dataset(
            dataset_name="TwinkStart/llama-questions", 
            split="test", 
            sample_size="[:2]",  # Just first 2 samples
            decode_audio=False
        )
        
        # Create file assistant
        print("\n🎙️ Creating FileVoiceAssistant...")
        assistant = FileVoiceAssistant(
            endpoint=endpoint,
            credential=credential,
            model="gpt-realtime"
        )
        
        # Process first audio item
        print("\n🎵 Processing audio from HuggingFace dataset...")
        audio_item = loader.get_audio_item(0)
        
        if not audio_item['audio_data']:
            print("❌ No audio data found in first item")
            return False
        
        print(f"   Audio size: {len(audio_item['audio_data'])} bytes")
        print(f"   Metadata: {audio_item['metadata'].get('Questions', 'N/A')}")
        
        # Process through VoiceLive
        result = await assistant.process_audio_data(
            audio_data=audio_item['audio_data'],
            enable_playback=False
        )
        
        # Display results
        print(f"\n📝 Processing Results:")
        print(f"   Success: {result['success']}")
        if result['success']:
            print(f"   Transcription: '{result['transcription']}'")
            print(f"   Audio size: {result['audio_size']} bytes")
            print(f"   Events: {len(result['events'])} processed")
        else:
            print(f"   Error: {result.get('error', 'Unknown error')}")
        
        return result['success']
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔄 Running HuggingFace + VoiceLive File Integration Test")
    success = asyncio.run(test_hf_file_integration())
    
    if success:
        print(f"\n🎉 Integration test passed!")
        print(f"✅ FileVoiceAssistant can process HuggingFace audio data")
    else:
        print(f"\n❌ Integration test failed")
        sys.exit(1)