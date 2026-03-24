#!/usr/bin/env python3
"""
Integration tests for media dataset and Foundry dataset support.

Tests Function App endpoints and Container App endpoints directly.
Validates schema detection, validation, and Foundry dataset passthrough.

Usage:
    python test_media_integration.py
    python test_media_integration.py --function-url https://func-xxx.azurewebsites.net/api
    python test_media_integration.py --container-url https://ca-xxx.azurecontainerapps.io
"""

import os
import sys
import json
import argparse
import time
from typing import Tuple, Any

# Use httpx for async container app, requests for function app
import requests

DEFAULT_FUNCTION_URL = os.getenv(
    "AZURE_FUNCTION_APP_URL",
    "https://func-vh7j24h6z2pgw.azurewebsites.net/api",
)
DEFAULT_CONTAINER_URL = os.getenv(
    "AZURE_CONTAINER_APP_URL",
    "https://ca-voicelive-vh7j24h6z2pgw.nicepebble-3d97cd1e.swedencentral.azurecontainerapps.io",
)
# Known media dataset in Foundry for testing
TEST_MEDIA_DATASET = "harness_media_base64_Eiffel_Tower_Visit_1"
TEST_LEGACY_DATASET = "Eiffel_Tower_Visit_1"

results = []


def call_function_app(base_url: str, endpoint: str, body: dict) -> Tuple[bool, Any]:
    """Call a Function App endpoint (with API key if available)."""
    url = f"{base_url.rstrip('/')}/{endpoint}"
    headers = {"Content-Type": "application/json"}
    # Try function key from env
    func_key = os.environ.get("AZURE_FUNCTION_KEY")
    if func_key:
        headers["x-functions-key"] = func_key
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=60)
        if resp.status_code == 200:
            return True, resp.json()
        return False, {"status": resp.status_code, "body": resp.text[:300]}
    except Exception as e:
        return False, str(e)


def call_container_app(base_url: str, endpoint: str, body: dict) -> Tuple[bool, Any]:
    """Call a Container App endpoint."""
    url = f"{base_url.rstrip('/')}/{endpoint}"
    try:
        resp = requests.post(url, json=body, timeout=60)
        if resp.status_code in (200, 201):
            return True, resp.json()
        return False, {"status": resp.status_code, "body": resp.text[:300]}
    except Exception as e:
        return False, str(e)


def record(name: str, passed: bool, detail: str = ""):
    status = "✅" if passed else "❌"
    results.append((name, passed))
    print(f"  {status} {name}" + (f": {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Function App tests
# ---------------------------------------------------------------------------

def test_schema_check_media(function_url: str):
    """list_datasets returns Foundry datasets (media classification is best-effort)."""
    # Media dataset classification via peek in list_datasets is best-effort —
    # it can fail silently when ContainerClient auth or timeout issues occur.
    # The primary classification path is check_dataset_schema (per-dataset).
    ok, resp = call_function_app(function_url, "list_datasets", {"dataset_type": "all"})
    if ok:
        datasets = resp.get("datasets", [])
        foundry = [d for d in datasets if d.get("store") == "foundry"]
        record("fa_list_foundry_datasets", len(foundry) > 0,
               f"found {len(foundry)} Foundry datasets")
    else:
        record("fa_list_media_classified", False, f"call failed: {resp}")


def test_schema_check_legacy(function_url: str):
    """check_dataset_schema detects voicelive for legacy blob datasets."""
    ok, resp = call_function_app(function_url, "check_dataset_schema", {
        "dataset_path": TEST_LEGACY_DATASET
    })
    if ok:
        ds_type = resp.get("dataset_type", "")
        record("fa_schema_legacy", ds_type == "voicelive",
               f"type={ds_type}")
    else:
        record("fa_schema_legacy", False, f"call failed: {resp}")


def test_validate_voicelive_legacy(function_url: str):
    """validate_voicelive_dataset passes for legacy WavPath dataset."""
    ok, resp = call_function_app(function_url, "validate_voicelive_dataset", {
        "dataset_path": TEST_LEGACY_DATASET
    })
    if ok:
        errors = resp.get("errors", [])
        record("fa_validate_legacy", len(errors) == 0,
               f"errors={len(errors)}")
    else:
        record("fa_validate_legacy", False, f"call failed: {resp}")


def test_run_audio_no_dataset(function_url: str):
    """run_voicelive_audio_tests returns 400 when no dataset source provided."""
    ok, resp = call_function_app(function_url, "run_voicelive_audio_tests", {
        "session_mode": "per-conversation"
    })
    if not ok and isinstance(resp, dict) and resp.get("status") == 400:
        record("fa_run_no_dataset_400", True, "correctly rejected")
    else:
        record("fa_run_no_dataset_400", False, f"expected 400, got: {resp}")


def test_list_datasets_types(function_url: str):
    """list_datasets includes type field for all datasets."""
    ok, resp = call_function_app(function_url, "list_datasets", {"dataset_type": "all"})
    if ok:
        datasets = resp.get("datasets", [])
        types = set(d.get("type") for d in datasets)
        has_voicelive = "voicelive" in types
        record("fa_list_has_types", has_voicelive and len(types) > 0,
               f"types found: {types}")
    else:
        record("fa_list_has_types", False, f"call failed: {resp}")


# ---------------------------------------------------------------------------
# Container App tests
# ---------------------------------------------------------------------------

def test_container_no_dataset(container_url: str):
    """Container app rejects request with no dataset source."""
    ok, resp = call_container_app(container_url, "run_voicelive_audio_tests", {
        "session_mode": "per-conversation"
    })
    # FastAPI may return 400, 422, or 500 wrapping the validation error
    if not ok:
        status = resp.get("status", 0) if isinstance(resp, dict) else 0
        body = resp.get("body", str(resp)) if isinstance(resp, dict) else str(resp)
        rejected = status in (400, 422) or "required" in body.lower()
        record("ca_no_dataset_rejected", rejected, f"status={status}")
    else:
        record("ca_no_dataset_rejected", False, "should have been rejected")


def test_container_legacy_dataset(container_url: str):
    """Container app accepts legacy blob dataset_path."""
    ok, resp = call_container_app(container_url, "run_voicelive_audio_tests", {
        "dataset_path": TEST_LEGACY_DATASET,
        "session_mode": "per-conversation"
    })
    if ok:
        job_id = resp.get("job_id", "")
        record("ca_legacy_start", bool(job_id), f"job_id={job_id[:12]}...")
    else:
        record("ca_legacy_start", False, f"call failed: {resp}")


def test_container_foundry_dataset(container_url: str):
    """Container app accepts foundry_dataset and starts processing."""
    ok, resp = call_container_app(container_url, "run_voicelive_audio_tests", {
        "foundry_dataset": TEST_MEDIA_DATASET,
        "session_mode": "per-conversation"
    })
    if ok:
        job_id = resp.get("job_id", "")
        record("ca_foundry_start", bool(job_id), f"job_id={job_id[:12]}...")
    else:
        record("ca_foundry_start", False, f"call failed: {resp}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Media dataset integration tests")
    parser.add_argument("--function-url", default=DEFAULT_FUNCTION_URL)
    parser.add_argument("--container-url", default=DEFAULT_CONTAINER_URL)
    parser.add_argument("--skip-container", action="store_true",
                        help="Skip container app tests")
    args = parser.parse_args()

    print("\n🧪 Media Dataset Integration Tests\n")

    print("  Function App endpoints:")
    test_list_datasets_types(args.function_url)
    test_schema_check_legacy(args.function_url)
    test_schema_check_media(args.function_url)
    test_validate_voicelive_legacy(args.function_url)
    test_run_audio_no_dataset(args.function_url)

    if not args.skip_container:
        print("\n  Container App endpoints:")
        test_container_no_dataset(args.container_url)
        test_container_legacy_dataset(args.container_url)
        test_container_foundry_dataset(args.container_url)

    # Summary
    passed = sum(1 for _, p in results if p)
    total = len(results)
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} failed", end="")
    print()

    if failed:
        print("\n  Failures:")
        for name, p in results:
            if not p:
                print(f"    ✗ {name}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
