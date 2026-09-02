"""Decision Criticality - how much it matters if the model is wrong.

Criticality is not inferred from the response. It is a property of the
action type, registered once by the enterprise in
config/action_registry.json. That has two consequences worth stating:

  1. It needs no model, so it costs no inference latency.
  2. It cannot be manipulated by the content of a response, which makes
     it the one input an attacker cannot move.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from src.models import DecisionCriticality

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "action_registry.json"


@lru_cache(maxsize=1)
def _registry() -> Dict:
    with open(_REGISTRY_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def get_criticality(action_type: str) -> DecisionCriticality:
    data = _registry()
    entry = data["actions"].get(action_type, data["default"])
    return DecisionCriticality(
        impact=entry["impact"],
        reversibility=entry["reversibility"],
        label=entry["label"],
    )


def known_action_types() -> list:
    return sorted(_registry()["actions"].keys())
