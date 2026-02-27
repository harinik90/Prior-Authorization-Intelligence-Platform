"""
Policy matching tools.

Provides get_payer_policy() and score_clinical_evidence() used by the
Policy Matching agent.
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Annotated

from pydantic import Field

CRITERIA_FILE = pathlib.Path(__file__).parent.parent.parent / "data" / "payer_criteria.json"

_criteria: dict | None = None


def _load_criteria() -> dict:
    global _criteria
    if _criteria is None:
        _criteria = json.loads(CRITERIA_FILE.read_text(encoding="utf-8"))
    return _criteria


def get_payer_policy(
    payer_id: Annotated[str, Field(description="Payer identifier (e.g. 'BCBS-IL', 'HUMANA-MA')")],
    cpt_code: Annotated[str, Field(description="CPT or HCPCS procedure code")],
    icd10_code: Annotated[str, Field(description="Primary ICD-10-CM diagnosis code")] = "",
) -> dict:
    """Return payer coverage policy with scored criteria for the Policy Matching agent.

    Returns:
      - policy_reference: str
      - criteria: list of criterion dicts with weight and description
      - step_therapy: dict | None
      - found: bool
    """
    criteria = _load_criteria()
    payer_data = criteria.get(payer_id, {})
    cpt_data = payer_data.get(cpt_code)

    if not cpt_data:
        return {
            "found": False,
            "policy_reference": None,
            "criteria": [],
            "step_therapy": None,
            "note": (
                f"No local policy found for {payer_id} / CPT {cpt_code}. "
                "Query cms-coverage MCP for LCD/NCD fallback."
            ),
        }

    required_docs = cpt_data.get("required_docs", [])
    # Assign equal weight to each criterion; step_therapy gets a higher weight
    base_weight = round(1.0 / max(len(required_docs), 1), 3)
    criteria_list = [
        {"criterion": doc, "weight": base_weight, "met": None}
        for doc in required_docs
    ]

    return {
        "found": True,
        "policy_reference": cpt_data.get("policy_reference"),
        "criteria": criteria_list,
        "optional_docs": cpt_data.get("optional_docs", []),
        "step_therapy": cpt_data.get("step_therapy"),
    }


def score_clinical_evidence(
    criteria: Annotated[
        list[dict],
        Field(description="List of criterion dicts from get_payer_policy(), each with 'criterion', 'weight', and 'met' (bool or null)"),
    ],
    clinical_summary: Annotated[
        str,
        Field(description="Summary of the clinical documentation submitted for this PA request"),
    ],
) -> dict:
    """Score submitted clinical evidence against each policy criterion.

    Uses keyword matching against the clinical_summary to determine which
    criteria appear to be met. Returns a structured scoring result.

    Returns:
      - criteria_met: list[str]
      - criteria_not_met: list[str]
      - score: float (0.0–1.0)
      - approval_probability: int (0–100)
      - assessment: str ("APPROVE" | "DENY" | "PEND")
    """
    summary_lower = clinical_summary.lower()

    # Keyword maps for common criterion patterns
    keyword_hints = {
        "physical therapy": ["physical therapy", "pt ", "physiotherapy", " pt ×", "pt x"],
        "conservative treatment": ["conservative", "physical therapy", "chiropractic", "nsaid", "injection"],
        "x-ray": ["x-ray", "xray", "radiograph", "weight-bearing ap", "kellgren"],
        "mri": ["mri", "magnetic resonance"],
        "bmi": ["bmi", "body mass index"],
        "functional": ["koos", "kss", "odi", "vas", "das28", "functional"],
        "nsaid": ["nsaid", "ibuprofen", "naproxen", "diclofenac", "meloxicam"],
        "injection": ["injection", "epi", "epidural", "steroid"],
        "stress test": ["stress test", "treadmill", "nuclear stress", "bruce protocol"],
        "ecg": ["ecg", "ekg", "electrocardiogram"],
        "specialist": ["cardiolog", "orthopedic", "pulmonolog", "rheumatolog", "neurosurg"],
        "npi": ["npi", "provider", "physician"],
        "methotrexate": ["methotrexate", "mtx"],
        "dmard": ["dmard", "leflunomide", "hydroxychloroquine", "sulfasalazine"],
        "anti-ccp": ["anti-ccp", "rf ", "rheumatoid factor", "das28"],
        "smoking": ["smoking", "tobacco", "pack-year", "nicotine"],
        "nodule": ["nodule", "fleischner", "growth"],
        "ct": ["ct ", "computed tomography", "ct chest"],
        "radiculopathy": ["radiculopathy", "nerve root", "radicular", "emg"],
        "neurological": ["neurological", "motor deficit", "myelopathy", "numbness"],
    }

    met: list[str] = []
    not_met: list[str] = []
    total_weight = 0.0
    met_weight = 0.0

    for c in criteria:
        criterion_text = c.get("criterion", "").lower()
        weight = c.get("weight", 0.1)
        total_weight += weight

        # Check if the criterion appears met based on keywords
        found = False
        for hint_key, hint_words in keyword_hints.items():
            if hint_key in criterion_text:
                if any(hw in summary_lower for hw in hint_words):
                    found = True
                    break

        # Fallback: check if any significant word from the criterion appears in the summary
        if not found:
            words = re.findall(r"\b\w{5,}\b", criterion_text)
            found = any(w in summary_lower for w in words)

        if found:
            met.append(c.get("criterion", ""))
            met_weight += weight
        else:
            not_met.append(c.get("criterion", ""))

    score = round(met_weight / total_weight, 2) if total_weight > 0 else 0.0
    approval_probability = int(score * 100)

    if score >= 0.85:
        assessment = "APPROVE"
    elif score >= 0.60:
        assessment = "PEND"
    else:
        assessment = "DENY"

    return {
        "criteria_met": met,
        "criteria_not_met": not_met,
        "score": score,
        "approval_probability": approval_probability,
        "assessment": assessment,
        "note": (
            "Score is keyword-based estimate. Claude should verify each criterion "
            "against actual documentation using icd10-codes and cms-coverage MCP tools."
        ),
    }
