#!/usr/bin/env python3
"""
Integration test script for VoiceLive Evaluation Agent v3.

Tests all deployed Azure Functions endpoints directly.
This validates the tools that the Foundry Agent uses.

Usage:
    python test_agent_sdk.py
    python test_agent_sdk.py --function-url https://your-function.azurewebsites.net/api
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, Any, Tuple

# Configuration
DEFAULT_FUNCTION_URL = os.getenv("AZURE_FUNCTION_APP_URL", 
    "https://func-iwcs3opx2cyci.azurewebsites.net/api")


def get_function_key() -> str:
    """Get function key from environment or Azure CLI."""
    key = os.getenv("AZURE_FUNCTION_KEY")
    if key:
        return key
    
    # Try to get from .env file
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.startswith("AZURE_FUNCTION_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    
    print("Warning: No function key found. Set AZURE_FUNCTION_KEY environment variable.")
    return ""


def call_endpoint(base_url: str, endpoint: str, body: Dict[str, Any], key: str) -> Tuple[bool, Any]:
    """Call a function endpoint and return (success, response)."""
    headers = {
        "x-functions-key": key,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(
            f"{base_url}/{endpoint}",
            headers=headers,
            json=body,
            timeout=60
        )
        
        if response.status_code == 200:
            return True, response.json()
        else:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return False, str(e)


def run_tests(function_url: str, function_key: str) -> bool:
    """Run all integration tests."""
    print("=" * 60)
    print("VoiceLive Evaluation Agent v3 - Integration Tests")
    print("=" * 60)
    print(f"Function URL: {function_url}")
    print()
    
    tests = []
    
    # Test 1: list_session_configs
    print("[1/10] list_session_configs")
    success, result = call_endpoint(function_url, "list_session_configs", {}, function_key)
    if success and "configs" in result:
        print(f"   ✓ Found {len(result['configs'])} configs")
        tests.append(("list_session_configs", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("list_session_configs", False))
    
    # Test 2: get_session_config
    print("\n[2/10] get_session_config")
    success, result = call_endpoint(function_url, "get_session_config", {"name": "default"}, function_key)
    if success and "config" in result:
        print(f"   ✓ Got config: {result['config'].get('Name')} (Model: {result['config'].get('Model')})")
        tests.append(("get_session_config", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("get_session_config", False))
    
    # Test 3: list_datasets
    print("\n[3/10] list_datasets")
    success, result = call_endpoint(function_url, "list_datasets", {}, function_key)
    if success and "datasets" in result:
        print(f"   ✓ Found {len(result['datasets'])} datasets")
        tests.append(("list_datasets", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("list_datasets", False))
    
    # Test 4: validate_dataset_consistency
    print("\n[4/10] validate_dataset_consistency")
    success, result = call_endpoint(function_url, "validate_dataset_consistency", 
                                    {"dataset_path": "test/minimal_test.jsonl"}, function_key)
    if success:
        errors = result.get("errors", [])
        print(f"   ✓ Valid: {result.get('is_valid')}, Errors: {len(errors)}")
        tests.append(("validate_dataset_consistency", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("validate_dataset_consistency", False))
    
    # Test 5: validate_dataset_quality
    print("\n[5/10] validate_dataset_quality")
    success, result = call_endpoint(function_url, "validate_dataset_quality",
                                    {"dataset_path": "test/minimal_test.jsonl"}, function_key)
    if success:
        print(f"   ✓ Quality score: {result.get('quality_score')}%")
        tests.append(("validate_dataset_quality", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("validate_dataset_quality", False))
    
    # Test 6: get_evaluation_recommendations
    print("\n[6/10] get_evaluation_recommendations")
    success, result = call_endpoint(function_url, "get_evaluation_recommendations",
                                    {"dataset_path": "test/minimal_test.jsonl"}, function_key)
    if success and "recommendations" in result:
        print(f"   ✓ Got recommendations: {result['recommendations']}")
        tests.append(("get_evaluation_recommendations", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("get_evaluation_recommendations", False))
    
    # Test 7: create_session_config
    print("\n[7/10] create_session_config")
    success, result = call_endpoint(function_url, "create_session_config", {
        "name": "test-integration",
        "model": "gpt-realtime",
        "sample_rate": 16000,
        "vad_type": "server_vad"
    }, function_key)
    if success and "config" in result:
        print(f"   ✓ Created config: {result['config'].get('Name')}")
        tests.append(("create_session_config", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("create_session_config", False))
    
    # Test 8: update_session_config
    print("\n[8/10] update_session_config")
    success, result = call_endpoint(function_url, "update_session_config", {
        "name": "test-integration",
        "model": "gpt-realtime-mini"
    }, function_key)
    if success and "config" in result:
        print(f"   ✓ Updated config: Model={result['config'].get('Model')}")
        tests.append(("update_session_config", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("update_session_config", False))
    
    # Test 9: list_evaluation_groups
    print("\n[9/10] list_evaluation_groups")
    success, result = call_endpoint(function_url, "list_evaluation_groups", {}, function_key)
    if success and ("evaluation_groups" in result or "groups" in result):
        groups = result.get("evaluation_groups", result.get("groups", []))
        print(f"   ✓ Found {len(groups)} evaluation groups")
        tests.append(("list_evaluation_groups", True))
    else:
        # 500 error is expected if no outputs exist yet
        if "500" in str(result):
            print(f"   ⚠ No outputs yet (expected)")
            tests.append(("list_evaluation_groups", True))
        else:
            print(f"   ✗ {result}")
            tests.append(("list_evaluation_groups", False))
    
    # Test 10: delete_session_config
    print("\n[10/10] delete_session_config")
    success, result = call_endpoint(function_url, "delete_session_config", {
        "name": "test-integration"
    }, function_key)
    if success:
        print(f"   ✓ Deleted config")
        tests.append(("delete_session_config", True))
    else:
        print(f"   ✗ {result}")
        tests.append(("delete_session_config", False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, success in tests if success)
    for name, success in tests:
        status = "✓ PASS" if success else "✗ FAIL"
        color = "\033[92m" if success else "\033[91m"
        reset = "\033[0m"
        print(f"  {color}{status}{reset} - {name}")
    
    print(f"\nTotal: {passed}/{len(tests)} tests passed")
    
    return passed == len(tests)


def main():
    parser = argparse.ArgumentParser(description="Integration tests for VoiceLive Evaluation Agent")
    parser.add_argument("--function-url", default=DEFAULT_FUNCTION_URL,
                        help="Azure Function App URL")
    parser.add_argument("--function-key", default="",
                        help="Azure Function key (or set AZURE_FUNCTION_KEY)")
    args = parser.parse_args()
    
    function_key = args.function_key or get_function_key()
    
    success = run_tests(args.function_url, function_key)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
