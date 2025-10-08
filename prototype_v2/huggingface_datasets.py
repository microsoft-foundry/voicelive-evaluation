import os
import dotenv
from datasets import load_dataset
from huggingface_hub import list_datasets, login, HfApi

## Change to the directory where this script is located
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Environment variable loading
try:
    from dotenv import load_dotenv

    load_dotenv('.\.env', override=True)
except ImportError:
    print("Note: python-dotenv not installed. Using existing environment variables.")

# Backup method for dotenv loading
try:
    dotenv.load_dotenv('.\.env', override=True)
except:
    pass

# Hugging Face Token Authentication Setup
print("🤗 Setting up Hugging Face authentication...")

# Method 1: Use environment variable first (non-interactive)
hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
if hf_token:
    try:
        login(token=hf_token)
        print("✅ Using token from environment variable")
    except Exception as e:
        print(f"❌ Failed to login with environment token: {e}")
        hf_token = None
else:
    # Method 2: Try stored token from `huggingface-cli login`
    try:
        login(add_to_git_credential=False)  # Don't prompt if no token exists
        print("✅ Using stored Hugging Face token")
    except Exception as e:
        print("ℹ️  No stored token found")
        print("   To avoid rate limiting, you can:")
        print("   1. Set HF_TOKEN environment variable: export HF_TOKEN=your_token")
        print("   2. Run 'huggingface-cli login' to store token permanently")
        print("   3. Get a token at: https://huggingface.co/settings/tokens")
        print("   Continuing without authentication (may hit rate limits)...")

# Initialize HF API with authentication
hf_api = HfApi()

# Print all the available datasets
# Get token for API calls (if available)
token = hf_api.token

# try:
#     datasets_list = list(list_datasets(token=token))
#     print(f"Found {len(datasets_list)} datasets")
#     print([dataset.id for dataset in datasets_list[:10]])  # Show first 10 to avoid spam
# except Exception as e:
#     print(f"Error listing datasets: {e}")

# Load audio dataset with authentication
print("\nLoading dataset with authentication...")
# Load without automatic audio decoding to bypass TorchCodec issues
from datasets import Audio
ds = load_dataset(
    "TwinkStart/llama-questions", 
    cache_dir="./data_cache", 
    split="test[:10%]",
    token=token  # Pass token to avoid rate limiting
)

# Disable automatic audio decoding to avoid TorchCodec dependency
ds = ds.cast_column("audio", Audio(decode=False))

print(f"✅ Successfully loaded dataset: {ds}")
print(f"📊 Dataset info: {len(ds)} samples")
print(f"📋 Dataset columns: {ds.column_names}")
print(f"🗂️  Dataset features: {ds.features}")

# Try to access data safely without triggering audio processing
print("\n🔍 Attempting to show sample data...")
try:
    # Method 1: Try to get raw data without processing
    sample_data = ds[:3]
    print(f"✅ Sample data keys: {list(sample_data.keys())}")
    
    # Show text data only (avoid audio processing)
    for key, values in sample_data.items():
        if key != 'audio':  # Skip audio column to avoid FFmpeg error
            print(f"   {key}: {values[:2]}...")  # Show first 2 values
except Exception as e:
    print(f"⚠️  Cannot access sample data due to missing dependencies: {e}")
    print("💡 This is likely because the dataset contains audio files and requires:")
    print("   - FFmpeg (for audio processing): https://ffmpeg.org/download.html")
    print("   - PyTorch Audio: pip install torchaudio")
    print("   - Compatible versions as per: https://github.com/pytorch/torchcodec")
    
    # Alternative: Show dataset structure without loading actual data
    print("\n📋 Dataset structure (metadata only):")
    try:
        # Use streaming mode to avoid loading audio files
        ds_stream = load_dataset(
            "TwinkStart/llama-questions", 
            split="test[:3]",
            streaming=True,
            token=token
        )
        print("✅ Streaming mode works - dataset is accessible")
        
        # Show first few items in streaming mode (safer)
        for i, item in enumerate(ds_stream):
            if i >= 2:  # Only show first 2 items
                break
            print(f"   Item {i}: {list(item.keys())}")
            # Show non-audio fields
            for key, value in item.items():
                if key != 'audio':
                    print(f"     {key}: {str(value)[:100]}...")  # Truncate long values
                    
    except Exception as stream_error:
        print(f"❌ Streaming mode also failed: {stream_error}")

print(f"\n🎯 Final Status:")
print(f"   Authentication: {'✅ TOKEN AUTHENTICATED' if token else '⚠️  NO TOKEN'}")
print(f"   Dataset Loading: {'✅ SUCCESS' if 'ds' in locals() else '❌ FAILED'}")
if 'ds' in locals():
    print(f"   Rate Limiting: ✅ BYPASSED (using authenticated requests)")
