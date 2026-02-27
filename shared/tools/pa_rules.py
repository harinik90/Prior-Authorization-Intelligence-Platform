"""
PA requirement rules tool.

Loads payer_pa_rules.json and provides check_pa_requirement() — the callable
tool used by the Coverage Prediction agent to determine if PA is needed.
"""
from __future__ import annotations

import json
import pathlib
from typing import Annotated

from pydantic import Field

DATA_FILE = pathlib.Path(__file__).parent.parent.parent / "data" / "payer_pa_rules.json"

_rules: dict | None = None


def _load_rules() -> dict:
    global _rules
    if _rules is None:
        _rules = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return _rules


def check_pa_requirement(
    cpt_code: Annotated[str, Field(description="CPT or HCPCS procedure code (e.g. '27447', 'J0135')")],
    icd10_code: Annotated[str, Field(description="Primary ICD-10-CM diagnosis code (e.g. 'M17.11')")],
    payer_id: Annotated[str, Field(description="Payer identifier (e.g. 'BCBS-IL', 'UHC-MA', 'AETNA-COMM')")],
    plan_type: Annotated[str, Field(description="Insurance plan type (e.g. 'PPO', 'HMO', 'Medicare Advantage')")],
) -> dict:
    """Determine whether prior authorization is required for a given CPT + payer combination.

    Returns a dict with:
      - pa_required: bool | "unknown"
      - confidence: float (0–1)
      - rationale: str
      - turnaround_days: int | None
      - step_therapy_required: bool
      - emergency_exempt: bool
      - expedited_available: bool
    """
    rules = _load_rules()
    payer_rules = rules.get(payer_id)

    if payer_rules is None:
        return {
            "pa_required": "unknown",
            "confidence": 0.3,
            "rationale": f"Payer '{payer_id}' not found in rules database. Contact payer directly.",
            "turnaround_days": None,
            "step_therapy_required": False,
            "emergency_exempt": False,
            "expedited_available": False,
        }

    cpt_rule = payer_rules.get(cpt_code)

    if cpt_rule is None:
        return {
            "pa_required": "unknown",
            "confidence": 0.4,
            "rationale": f"CPT {cpt_code} not found in {payer_id} rules. PA status is unknown — verify with payer.",
            "turnaround_days": None,
            "step_therapy_required": False,
            "emergency_exempt": False,
            "expedited_available": False,
        }

    pa_required = cpt_rule.get("pa_required", False)
    plan_types = cpt_rule.get("plan_types", [])

    # Check if this plan type requires PA (if plan_types list is populated)
    if plan_types and plan_type not in plan_types:
        return {
            "pa_required": False,
            "confidence": 0.85,
            "rationale": f"CPT {cpt_code} does not require PA under {payer_id} for plan type '{plan_type}'. "
                         f"PA required for: {', '.join(plan_types)}.",
            "turnaround_days": None,
            "step_therapy_required": False,
            "emergency_exempt": cpt_rule.get("emergency_exempt", False),
            "expedited_available": cpt_rule.get("expedited_available", False),
        }

    return {
        "pa_required": pa_required,
        "confidence": 0.95,
        "rationale": cpt_rule.get("rationale", f"PA required for CPT {cpt_code} under {payer_id}"),
        "turnaround_days": cpt_rule.get("turnaround_days"),
        "step_therapy_required": cpt_rule.get("step_therapy_required", False),
        "dmard_failures_required": cpt_rule.get("dmard_failures_required"),
        "conservative_tx_months_required": cpt_rule.get("conservative_tx_months_required"),
        "biosimilar_preferred": cpt_rule.get("biosimilar_preferred", False),
        "emergency_exempt": cpt_rule.get("emergency_exempt", False),
        "expedited_available": cpt_rule.get("expedited_available", False),
    }
