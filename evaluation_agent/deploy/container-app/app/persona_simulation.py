"""Structured persona, scenario, and data assets for simulated-user runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

MAX_SIMULATION_TURNS = 100


class SimulationIncompleteError(RuntimeError):
    """Report an incomplete simulation while preserving completed turn results."""

    def __init__(self, message: str, partial_results: list[Dict[str, Any]]) -> None:
        super().__init__(message)
        self.partial_results = partial_results


@dataclass(frozen=True)
class SimulationAssets:
    """Resolved assets and runtime limits for a simulated user."""

    persona: Dict[str, Any]
    scenario: Dict[str, Any]
    data: Dict[str, Any]
    max_turns: int = 8
    model: str = "gpt-realtime"
    voice: str = "en-US-Andrew:DragonHDLatestNeural"
    voice_type: str = "azure-standard"


def simulation_assets_from_dict(value: Dict[str, Any]) -> SimulationAssets:
    """Validate resolved inline assets supplied to the processor API."""
    resolved: Dict[str, Dict[str, Any]] = {}
    for field_name in ("persona", "scenario", "data"):
        field_value = value.get(field_name)
        if not isinstance(field_value, dict):
            raise ValueError(f"{field_name} must be a JSON object")
        resolved[field_name] = field_value

    max_turns = value.get("max_turns", 8)
    if (
        not isinstance(max_turns, int)
        or isinstance(max_turns, bool)
        or not 1 <= max_turns <= MAX_SIMULATION_TURNS
    ):
        raise ValueError(
            f"max_turns must be an integer from 1 to {MAX_SIMULATION_TURNS}"
        )

    string_values = {
        field_name: value.get(field_name, default)
        for field_name, default in (
            ("model", "gpt-realtime"),
            ("voice", "en-US-Andrew:DragonHDLatestNeural"),
            ("voice_type", "azure-standard"),
        )
    }
    for field_name, field_value in string_values.items():
        if not isinstance(field_value, str) or not field_value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    return SimulationAssets(
        persona=resolved["persona"],
        scenario=resolved["scenario"],
        data=resolved["data"],
        max_turns=max_turns,
        model=string_values["model"],
        voice=string_values["voice"],
        voice_type=string_values["voice_type"],
    )


def build_simulator_instructions(assets: SimulationAssets) -> str:
    """Build deterministic instructions that keep the model in the user role."""
    payload = {
        "persona": assets.persona,
        "scenario": assets.scenario,
        "data": assets.data,
    }
    return (
        "Simulate the configured user in this VoiceLive evaluation. Reply only with "
        "the user's next spoken words. Never act as the assistant or explain the "
        "simulation. Stay consistent with the persona, scenario, opaque session data, "
        "and conversation history. Begin the scenario naturally when asked to start.\n"
        + json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    )
