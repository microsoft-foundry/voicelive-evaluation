"""
Test script for HuggingFace → VoiceLive integration
Tests the HuggingFaceAudioLoader class independently.
"""
import os
import sys
import asyncio
import logging

## Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv('.\.env', override=True)
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

from prototype_v1.hf_audio_loader import HuggingFaceAudioLoader

def test_hf_loader():
    """Test the HuggingFace audio loader functionality."""
    print("🧪 Testing HuggingFace Audio Loader")
    print("=" * 50)
    
    # Setup basic logging
    logging.basicConfig(level=logging.INFO)
    
    try:
        # Create loader
        loader = HuggingFaceAudioLoader()
        
        # Test dataset loading
        print("\n📊 Loading sample dataset...")
        dataset = loader.load_dataset(
            dataset_name="TwinkStart/llama-questions", 
            split="test", 
            sample_size="[:5]",  # Just first 5 samples for testing
            decode_audio=False
        )
        
        # Show dataset info
        info = loader.get_dataset_info()
        print(f"✅ Dataset loaded successfully!")
        print(f"   Size: {info['size']} samples")
        print(f"   Columns: {info['columns']}")
        print(f"   Audio config: {info.get('audio_config', 'N/A')}")
        
        # Test getting individual items
        print(f"\n🎵 Testing audio item retrieval...")
        for i in range(min(3, info['size'])):
            try:
                item = loader.get_audio_item(i)
                print(f"\n   Item {i}:")
                print(f"     Metadata keys: {list(item['metadata'].keys())}")
                print(f"     Has audio data: {'Yes' if item['audio_data'] else 'No'}")
                
                if item['audio_data']:
                    print(f"     Audio size: {len(item['audio_data'])} bytes")
                    
                    # Test base64 encoding
                    audio_b64 = loader.get_audio_base64(i)
                    if audio_b64:
                        print(f"     Base64 length: {len(audio_b64)} chars")
                
                # Show some metadata
                for key, value in list(item['metadata'].items())[:3]:
                    print(f"     {key}: {str(value)[:50]}...")
                    
            except Exception as e:
                print(f"   ❌ Error with item {i}: {e}")
        
        print(f"\n✅ HuggingFace loader test completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_integration_setup():
    """Test that all required dependencies are available."""
    print("\n🔧 Testing Integration Dependencies")
    print("=" * 50)
    
    # Test imports
    required_modules = [
        ("datasets", "HuggingFace Datasets"),
        ("huggingface_hub", "HuggingFace Hub"),
        ("azure.core.credentials", "Azure Core"),
        ("azure.identity", "Azure Identity"),
    ]
    
    missing = []
    for module, name in required_modules:
        try:
            __import__(module)
            print(f"   ✅ {name}: Available")
        except ImportError:
            print(f"   ❌ {name}: Missing")
            missing.append(name)
    
    # Check environment variables
    print(f"\n🔑 Environment Variables:")
    env_vars = [
        "HF_TOKEN",
        "AZURE_VOICELIVE_API_KEY",
        "AZURE_VOICELIVE_ENDPOINT"
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: Set (length: {len(value)})")
        else:
            print(f"   ⚠️  {var}: Not set")
    
    return len(missing) == 0

if __name__ == "__main__":
    print("🧪 HuggingFace → VoiceLive Integration Test")
    print("=" * 60)
    
    # Test setup
    setup_ok = test_integration_setup()
    
    if setup_ok:
        # Test HF loader
        loader_ok = test_hf_loader()
        
        if loader_ok:
            print(f"\n🎉 All tests passed!")
            print(f"\n🚀 Ready to run: python hf_dataset_run_on_vl.py TwinkStart/llama-questions --sample-size 3")
        else:
            print(f"\n❌ HF Loader test failed")
            sys.exit(1)
    else:
        print(f"\n❌ Setup test failed - missing dependencies")
        sys.exit(1)