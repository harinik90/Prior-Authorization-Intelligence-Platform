"""
Documentation completeness tools.

Provides check_payer_criteria() and get_fhir_documents() used by the
Documentation Completeness agent.
"""
from __future__ import annotations

import json
import pathlib
from typing import Annotated

from pydantic import Field

DATA_FILE = pathlib.Path(__file__).parent.parent.parent / "data" / "payer_criteria.json"

_criteria: dict | None = None


def _load_criteria() -> dict:
    global _criteria
    if _criteria is None:
        _criteria = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return _criteria


def check_payer_criteria(
    payer_id: Annotated[str, Field(description="Payer identifier (e.g. 'BCBS-IL', 'CIGNA-COMM')")],
    cpt_code: Annotated[str, Field(description="CPT or HCPCS procedure code")],
    icd10_code: Annotated[str, Field(description="Primary ICD-10-CM diagnosis code")] = "",
) -> dict:
    """Return the documentation checklist and step therapy requirements for a payer + CPT combination.

    Returns:
      - policy_reference: str — the LCD/NCD or payer policy ID
      - required_docs: list[str] — checklist of required documentation items
      - optional_docs: list[str] — additional supporting docs that strengthen the case
      - step_therapy: dict | None — step therapy requirements if applicable
      - found: bool — whether a matching criteria entry was found
    """
    criteria = _load_criteria()
    payer_criteria = criteria.get(payer_id)

    if payer_criteria is None:
        return {
            "found": False,
            "policy_reference": None,
            "required_docs": [],
            "optional_docs": [],
            "step_therapy": None,
            "note": f"No criteria found for payer '{payer_id}'. Use CMS LCD/NCD as fallback via cms-coverage MCP.",
        }

    cpt_criteria = payer_criteria.get(cpt_code)

    if cpt_criteria is None:
        return {
            "found": False,
            "policy_reference": None,
            "required_docs": [],
            "optional_docs": [],
            "step_therapy": None,
            "note": f"No criteria found for CPT {cpt_code} under payer '{payer_id}'. "
                    "Use cms-coverage MCP to look up LCD/NCD criteria.",
        }

    return {
        "found": True,
        "policy_reference": cpt_criteria.get("policy_reference"),
        "required_docs": cpt_criteria.get("required_docs", []),
        "optional_docs": cpt_criteria.get("optional_docs", []),
        "step_therapy": cpt_criteria.get("step_therapy"),
        "note": None,
    }


def get_fhir_documents(
    patient_token: Annotated[str, Field(description="De-identified patient token (e.g. 'PT-78432')")],
    doc_types: Annotated[
        list[str],
        Field(description="Document types to retrieve. Options: 'clinical_notes', 'imaging', 'labs', 'medications', 'observations'"),
    ],
    bundle_path: Annotated[
        str,
        Field(description="Path to the FHIR bundle JSON file for this patient"),
    ] = "",
) -> list[dict]:
    """Retrieve FHIR DocumentReference, Observation, and MedicationRequest resources
    from the patient's FHIR bundle for documentation completeness review.

    Returns a list of simplified resource summaries with type, date, and description.
    """
    if not bundle_path:
        return [{"error": "bundle_path is required to load patient FHIR documents"}]

    bundle_file = pathlib.Path(bundle_path)
    if not bundle_file.exists():
        return [{"error": f"Bundle file not found: {bundle_path}"}]

    try:
        bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [{"error": f"Failed to read bundle: {e}"}]

    type_map = {
        "clinical_notes": ["DocumentReference"],
        "imaging":        ["DocumentReference"],
        "labs":           ["Observation"],
        "medications":    ["MedicationRequest"],
        "observations":   ["Observation"],
    }

    target_types: set[str] = set()
    for dt in doc_types:
        target_types.update(type_map.get(dt, []))

    results: list[dict] = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType", "")
        if rtype not in target_types:
            continue

        summary: dict = {"resourceType": rtype, "id": res.get("id")}

        if rtype == "DocumentReference":
            summary["date"] = res.get("date")
            summary["description"] = res.get("description")
            summary["type"] = res.get("type", {}).get("coding", [{}])[0].get("display")

        elif rtype == "Observation":
            summary["effectiveDateTime"] = res.get("effectiveDateTime")
            summary["code"] = res.get("code", {}).get("coding", [{}])[0].get("display")
            summary["valueString"] = res.get("valueString") or str(
                res.get("valueQuantity", {}).get("value", "")
            )
            summary["note"] = res.get("note", [{}])[0].get("text") if res.get("note") else None

        elif rtype == "MedicationRequest":
            summary["medication"] = (
                res.get("medicationCodeableConcept", {}).get("coding", [{}])[0].get("display")
            )
            summary["note"] = res.get("note", [{}])[0].get("text") if res.get("note") else None

        results.append(summary)

    return results
