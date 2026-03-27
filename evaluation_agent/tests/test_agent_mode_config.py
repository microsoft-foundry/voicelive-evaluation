"""
Unit tests for agent mode configuration.
Tests AgentConfig, SessionConfig.is_agent_mode, build_agent_config(),
from_dict(), to_dict(), and VoiceLiveClient.from_session_config() factory.

No Azure credentials or live endpoints required.

Usage:
    python test_agent_mode_config.py
    python test_agent_mode_config.py --test agent_config_defaults
"""
import argparse
import os
import sys
import traceback

# Allow imports from the container app package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "deploy", "container-app"))

from app.config import AgentConfig, SessionConfig, ProcessorMode


# ---------------------------------------------------------------------------
# 1. AgentConfig dataclass tests
# ---------------------------------------------------------------------------

def test_agent_config_defaults() -> tuple:
    """AgentConfig defaults are empty/None."""
    cfg = AgentConfig()
    checks = [
        cfg.agent_name == "",
        cfg.project_name == "",
        cfg.agent_version is None,
        cfg.conversation_id is None,
        cfg.foundry_resource_override is None,
        cfg.authentication_identity_client_id is None,
    ]
    ok = all(checks)
    print(f"  defaults correct: {ok}")
    return ok, ok


def test_agent_config_full_construction() -> tuple:
    """AgentConfig constructed with all fields retains values."""
    cfg = AgentConfig(
        agent_name="my-agent",
        project_name="my-project",
        agent_version="v2",
        conversation_id="conv-123",
        foundry_resource_override="https://override.services.ai.azure.com/",
        authentication_identity_client_id="client-id-abc",
    )
    checks = [
        cfg.agent_name == "my-agent",
        cfg.project_name == "my-project",
        cfg.agent_version == "v2",
        cfg.conversation_id == "conv-123",
        cfg.foundry_resource_override == "https://override.services.ai.azure.com/",
        cfg.authentication_identity_client_id == "client-id-abc",
    ]
    ok = all(checks)
    print(f"  all fields retained: {ok}")
    return ok, ok


# ---------------------------------------------------------------------------
# 2. SessionConfig.is_agent_mode tests
# ---------------------------------------------------------------------------

def test_is_agent_mode_false_by_default() -> tuple:
    """is_agent_mode is False when no agent config is set."""
    cfg = SessionConfig()
    ok = cfg.is_agent_mode is False
    print(f"  default is_agent_mode=False: {ok}")
    return ok, ok


def test_is_agent_mode_false_only_agent_name() -> tuple:
    """is_agent_mode is False when only agent_name is set."""
    cfg = SessionConfig(agent=AgentConfig(agent_name="agent-only"))
    ok = cfg.is_agent_mode is False
    print(f"  agent_name only -> False: {ok}")
    return ok, ok


def test_is_agent_mode_false_only_project_name() -> tuple:
    """is_agent_mode is False when only project_name is set."""
    cfg = SessionConfig(agent=AgentConfig(project_name="project-only"))
    ok = cfg.is_agent_mode is False
    print(f"  project_name only -> False: {ok}")
    return ok, ok


def test_is_agent_mode_true_both_set() -> tuple:
    """is_agent_mode is True when both agent_name and project_name are set."""
    cfg = SessionConfig(agent=AgentConfig(agent_name="a", project_name="p"))
    ok = cfg.is_agent_mode is True
    print(f"  both set -> True: {ok}")
    return ok, ok


def test_is_agent_mode_true_via_from_dict() -> tuple:
    """is_agent_mode is True when agent section provided via from_dict()."""
    cfg = SessionConfig.from_dict({
        "agent": {"agent_name": "a", "project_name": "p"},
    })
    ok = cfg.is_agent_mode is True
    print(f"  from_dict agent section -> True: {ok}")
    return ok, ok


# ---------------------------------------------------------------------------
# 3. SessionConfig.build_agent_config() tests
# ---------------------------------------------------------------------------

def test_build_agent_config_none_when_not_agent_mode() -> tuple:
    """build_agent_config() returns None when not in agent mode."""
    cfg = SessionConfig()
    ok = cfg.build_agent_config() is None
    print(f"  returns None: {ok}")
    return ok, ok


def test_build_agent_config_minimal() -> tuple:
    """build_agent_config() returns dict with agent_name + project_name."""
    cfg = SessionConfig(agent=AgentConfig(agent_name="a", project_name="p"))
    result = cfg.build_agent_config()
    checks = [
        result is not None,
        result.get("agent_name") == "a",
        result.get("project_name") == "p",
        len(result) == 2,
    ]
    ok = all(checks)
    print(f"  minimal dict: {ok}  keys={list(result.keys()) if result else None}")
    return ok, ok


def test_build_agent_config_optional_fields() -> tuple:
    """build_agent_config() includes optional fields when set."""
    cfg = SessionConfig(agent=AgentConfig(
        agent_name="a",
        project_name="p",
        agent_version="v3",
        conversation_id="conv-1",
        foundry_resource_override="https://override/",
    ))
    result = cfg.build_agent_config()
    checks = [
        result is not None,
        result.get("agent_version") == "v3",
        result.get("conversation_id") == "conv-1",
        result.get("foundry_resource_override") == "https://override/",
    ]
    ok = all(checks)
    print(f"  optional fields included: {ok}")
    return ok, ok


def test_build_agent_config_client_id_requires_foundry_override() -> tuple:
    """authentication_identity_client_id only included when foundry_resource_override also set."""
    # client_id set but foundry_resource_override NOT set → client_id excluded
    cfg_no_override = SessionConfig(agent=AgentConfig(
        agent_name="a", project_name="p",
        authentication_identity_client_id="cid-123",
    ))
    result_no = cfg_no_override.build_agent_config()
    excluded = "authentication_identity_client_id" not in (result_no or {})

    # Both set → client_id included
    cfg_with_override = SessionConfig(agent=AgentConfig(
        agent_name="a", project_name="p",
        foundry_resource_override="https://override/",
        authentication_identity_client_id="cid-123",
    ))
    result_yes = cfg_with_override.build_agent_config()
    included = (result_yes or {}).get("authentication_identity_client_id") == "cid-123"

    ok = excluded and included
    print(f"  excluded without override: {excluded}, included with override: {included}")
    return ok, ok


# ---------------------------------------------------------------------------
# 4. SessionConfig.from_dict() with agent section
# ---------------------------------------------------------------------------

def test_from_dict_parses_agent_section() -> tuple:
    """from_dict() parses agent section correctly."""
    cfg = SessionConfig.from_dict({
        "agent": {
            "agent_name": "eval-agent",
            "project_name": "eval-project",
            "agent_version": "v1",
            "conversation_id": "conv-42",
            "foundry_resource_override": "https://fr/",
            "authentication_identity_client_id": "abc",
        },
    })
    a = cfg.agent
    checks = [
        a is not None,
        a.agent_name == "eval-agent",
        a.project_name == "eval-project",
        a.agent_version == "v1",
        a.conversation_id == "conv-42",
        a.foundry_resource_override == "https://fr/",
        a.authentication_identity_client_id == "abc",
    ]
    ok = all(checks)
    print(f"  all agent fields parsed: {ok}")
    return ok, ok


def test_from_dict_sets_agent_mode() -> tuple:
    """from_dict() sets mode to AGENT_MODE when agent section present."""
    cfg = SessionConfig.from_dict({
        "agent": {"agent_name": "a", "project_name": "p"},
    })
    ok = cfg.mode == ProcessorMode.AGENT_MODE
    print(f"  mode=AGENT_MODE: {ok}")
    return ok, ok


def test_from_dict_missing_optional_agent_fields() -> tuple:
    """from_dict() handles missing optional agent fields gracefully."""
    cfg = SessionConfig.from_dict({
        "agent": {"agent_name": "a", "project_name": "p"},
    })
    a = cfg.agent
    checks = [
        a is not None,
        a.agent_name == "a",
        a.project_name == "p",
        a.agent_version is None,
        a.conversation_id is None,
        a.foundry_resource_override is None,
        a.authentication_identity_client_id is None,
    ]
    ok = all(checks)
    print(f"  optional fields default to None: {ok}")
    return ok, ok


# ---------------------------------------------------------------------------
# 5. SessionConfig.to_dict() with agent
# ---------------------------------------------------------------------------

def test_to_dict_includes_agent_when_set() -> tuple:
    """to_dict() includes agent info when set."""
    cfg = SessionConfig(agent=AgentConfig(
        agent_name="a", project_name="p", agent_version="v1",
    ))
    d = cfg.to_dict()
    agent_d = d.get("agent")
    checks = [
        agent_d is not None,
        agent_d.get("agent_name") == "a",
        agent_d.get("project_name") == "p",
        agent_d.get("agent_version") == "v1",
    ]
    ok = all(checks)
    print(f"  agent in dict: {ok}")
    return ok, ok


def test_to_dict_agent_none_when_not_set() -> tuple:
    """to_dict() returns None for agent when not set."""
    cfg = SessionConfig()
    d = cfg.to_dict()
    ok = d.get("agent") is None
    print(f"  agent is None: {ok}")
    return ok, ok


# ---------------------------------------------------------------------------
# 6. VoiceLiveClient.from_session_config() tests
# ---------------------------------------------------------------------------

def test_from_session_config_with_agent_mode() -> tuple:
    """from_session_config() creates client with agent_config when is_agent_mode."""
    from app.voicelive_client import VoiceLiveClient
    cfg = SessionConfig(agent=AgentConfig(agent_name="a", project_name="p"))
    client = VoiceLiveClient.from_session_config(
        endpoint="https://fake.endpoint.azure.com/",
        config=cfg,
    )
    checks = [
        isinstance(client, VoiceLiveClient),
        client._agent_config is not None,
        client._agent_config.get("agent_name") == "a",
        client._agent_config.get("project_name") == "p",
    ]
    ok = all(checks)
    print(f"  client has agent_config: {ok}")
    return ok, ok


def test_from_session_config_without_agent_mode() -> tuple:
    """from_session_config() creates client without agent_config when not agent mode."""
    from app.voicelive_client import VoiceLiveClient
    cfg = SessionConfig()
    client = VoiceLiveClient.from_session_config(
        endpoint="https://fake.endpoint.azure.com/",
        config=cfg,
    )
    checks = [
        isinstance(client, VoiceLiveClient),
        client._agent_config is None,
    ]
    ok = all(checks)
    print(f"  client without agent_config: {ok}")
    return ok, ok


def test_cross_resource_from_dict() -> tuple:
    """from_dict() with cross-resource agent config."""
    cfg = SessionConfig.from_dict({
        "agent": {
            "agent_name": "VoiceAgentwBingWebSearch",
            "project_name": "jagoerge-voicelive-sec",
            "agent_version": "14",
            "foundry_resource_override": "jagoerge-voicelive-sec-resource",
            "authentication_identity_client_id": "test-mi-id",
        }
    })
    agent_cfg = cfg.build_agent_config()
    ok = (
        agent_cfg is not None
        and agent_cfg["foundry_resource_override"] == "jagoerge-voicelive-sec-resource"
        and agent_cfg["authentication_identity_client_id"] == "test-mi-id"
        and agent_cfg["agent_version"] == "14"
    )
    print(f"  cross-resource config correct: {ok}")
    return ok, ok


# ---------------------------------------------------------------------------
# Test registry & runner
# ---------------------------------------------------------------------------

TESTS = {
    # 1. AgentConfig
    "agent_config_defaults": test_agent_config_defaults,
    "agent_config_full": test_agent_config_full_construction,
    # 2. is_agent_mode
    "is_agent_mode_default": test_is_agent_mode_false_by_default,
    "is_agent_mode_name_only": test_is_agent_mode_false_only_agent_name,
    "is_agent_mode_project_only": test_is_agent_mode_false_only_project_name,
    "is_agent_mode_both": test_is_agent_mode_true_both_set,
    "is_agent_mode_from_dict": test_is_agent_mode_true_via_from_dict,
    # 3. build_agent_config
    "build_none": test_build_agent_config_none_when_not_agent_mode,
    "build_minimal": test_build_agent_config_minimal,
    "build_optional": test_build_agent_config_optional_fields,
    "build_client_id_guard": test_build_agent_config_client_id_requires_foundry_override,
    # 4. from_dict
    "from_dict_agent": test_from_dict_parses_agent_section,
    "from_dict_mode": test_from_dict_sets_agent_mode,
    "from_dict_optional": test_from_dict_missing_optional_agent_fields,
    # 5. to_dict
    "to_dict_agent": test_to_dict_includes_agent_when_set,
    "to_dict_no_agent": test_to_dict_agent_none_when_not_set,
    # 6. VoiceLiveClient factory
    "client_agent_mode": test_from_session_config_with_agent_mode,
    "client_no_agent": test_from_session_config_without_agent_mode,
    # 7. Cross-resource
    "cross_resource": test_cross_resource_from_dict,
}


def main():
    parser = argparse.ArgumentParser(description="Unit tests for agent mode configuration")
    parser.add_argument("--test", choices=list(TESTS.keys()) + ["all"], default="all")
    parser.add_argument("--list-tests", action="store_true")
    args = parser.parse_args()

    if args.list_tests:
        print("Available tests:")
        for name, fn in TESTS.items():
            print(f"  {name}: {fn.__doc__}")
        return

    tests_to_run = TESTS if args.test == "all" else {args.test: TESTS[args.test]}
    results = []

    for name, test_fn in tests_to_run.items():
        print(f"\n{'=' * 60}")
        print(f"TEST: {name} — {test_fn.__doc__}")
        print("=" * 60)
        try:
            ok, behavior_ok = test_fn()
            results.append((name, ok, behavior_ok))
        except Exception as e:
            traceback.print_exc()
            results.append((name, False, False))

    # Summary
    print(f"\n{'=' * 60}")
    print("TEST SUMMARY")
    print("=" * 60)
    pass_count = sum(1 for _, ok, _ in results if ok)
    behavior_count = sum(1 for _, _, b in results if b)
    for name, ok, behavior_ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {name}: {status}")

    print(f"\nTotal: {pass_count}/{len(results)} passed")
    sys.exit(0 if pass_count == len(results) else 1)


if __name__ == "__main__":
    main()
