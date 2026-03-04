#!/usr/bin/env python3
"""
Example usage of Azure AI Foundry evaluators in the voicelive-evaluation framework.

This example shows how to use the new Azure AI evaluation SDK integration
for voice evaluation tasks.
"""

import os
import sys
import json
from pathlib import Path

# Add the audio_evals module path
sys.path.insert(0, str(Path(__file__).parent.parent))

from audio_evals.evaluator.azure_ai_foundry import (
    AzureAIFoundryEvaluator,
    AzureAIRelevanceEvaluator,
    AzureAICoherenceEvaluator,
    AzureAIFluencyEvaluator,
    AzureAIGroundednessEvaluator
)


def test_azure_ai_evaluator():
    """Test the Azure AI Foundry evaluators with sample data."""
    
    # Sample data for testing
    sample_data = {
        "query": "What is the capital of France?",
        "pred": "The capital of France is Paris, which is known for its beautiful architecture and the Eiffel Tower.",
        "label": "Paris is the capital city of France.",
        "context": "France is a country in Western Europe. Its capital and largest city is Paris."
    }
    
    # Check if Azure AI configuration is available
    required_env_vars = ["AOAI_ENDPOINT", "AOAI_API_KEY", "AOAI_DEPLOYMENT_NAME"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        print("Please set the following environment variables:")
        for var in missing_vars:
            print(f"  {var}=<your_value>")
        return False
    
    print("✅ Azure AI configuration found")
    
    try:
        # Test different evaluator types
        evaluators = {
            "relevance": AzureAIRelevanceEvaluator(threshold=3),
            "coherence": AzureAICoherenceEvaluator(threshold=3),
            "fluency": AzureAIFluencyEvaluator(threshold=3),
            "groundedness": AzureAIGroundednessEvaluator(threshold=3)
        }
        
        results = {}
        
        for eval_type, evaluator in evaluators.items():
            print(f"\n🔍 Testing {eval_type} evaluator...")
            
            # Run evaluation
            result = evaluator(
                pred=sample_data["pred"],
                ref=sample_data["label"],
                query=sample_data["query"],
                context=sample_data["context"]
            )
            
            results[eval_type] = result
            
            # Print results
            print(f"   Score: {result.get('score', 'N/A')}")
            print(f"   Rating: {result.get('rating', 'N/A')}")
            print(f"   Pass: {result.get('pass', 'N/A')}")
            
            if 'error' in result:
                print(f"   ❌ Error: {result['error']}")
            else:
                print(f"   ✅ Success")
        
        # Save results
        output_file = Path(__file__).parent / "azure_ai_test_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n📊 Results saved to: {output_file}")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Please install the Azure AI evaluation SDK:")
        print("  pip install azure-ai-evaluation")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_registry_integration():
    """Test the registry integration of Azure AI evaluators."""
    
    try:
        # Import registry
        from audio_evals.registry import Registry
        
        # Create registry instance
        registry = Registry()
        
        # Test if our evaluators are registered
        azure_evaluators = [
            "azure-ai-relevance",
            "azure-ai-coherence", 
            "azure-ai-fluency",
            "azure-ai-groundedness",
            "azure-ai-foundry"
        ]
        
        print("\n🔧 Testing registry integration...")
        
        for eval_name in azure_evaluators:
            try:
                evaluator = registry.get_evaluator(eval_name)
                print(f"   ✅ {eval_name}: {type(evaluator).__name__}")
            except Exception as e:
                print(f"   ❌ {eval_name}: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Registry test error: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Azure AI Foundry Evaluator Test")
    print("=" * 50)
    
    # Test direct evaluator usage
    success1 = test_azure_ai_evaluator()
    
    # Test registry integration
    success2 = test_registry_integration()
    
    if success1 and success2:
        print("\n🎉 All tests passed!")
    else:
        print("\n❌ Some tests failed. Check the output above.")
        sys.exit(1)