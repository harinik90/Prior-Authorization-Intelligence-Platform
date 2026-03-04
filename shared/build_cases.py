"""
Build data/cases.json from FHIR bundles in usecases/.

Each bundle must contain a top-level "_pa_meta" object.
Files without "_pa_meta" are silently skipped.

Required _pa_meta fields
  label      (str) — cases.json key, e.g. "UC1 — Total Knee..."
  sort_order (int) — display order (1-based)
  type       (str) — pipeline | appeal | resubmission | single
  expected   (str) — human-readable expected outcome

Optional _pa_meta override fields (win over FHIR-extracted values)
  patient_token, cpt, cpt_desc, icd10, icd10_desc,
  payer, plan, npi, subscriber_id, clinical_summary,
  agent, pa_request_id, denial_code, denial_rationale

Usage
  python shared/build_cases.py               # rebuild data/cases.json
  from shared.build_cases import build_cases_json
  cases = build_cases_json()
"""
from __future__ import annotations

import json
import pathlib
import re

USECASES_DIR = pathlib.Path(__file__).parent.parent / "usecases"
CASES_JSON   = pathlib.Path(__file__).parent.parent / "data" / "cases.json"


# ── FHIR helpers ──────────────────────────────────────────────────────────────

def _index(bundle: dict) -> dict[str, list]:
    """Index all bundle entries by resourceType."""
    result: dict[str, list] = {}
    for entry in bundle.get("entry", []):
        r  = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt:
            result.setdefault(rt, []).append(r)
    return result


def _first(lst: list, default=None):
    return lst[0] if lst else default


def _extract(bundle: dict) -> tuple[str, dict]:
    """Return (label, case_dict) from a bundle with _pa_meta."""
    meta = bundle.get("_pa_meta", {})
    res  = _index(bundle)

    def override(key: str, fhir_val):
        """Return meta[key] if present, otherwise fhir_val."""
        return meta[key] if key in meta else fhir_val

    # ── patient token ────────────────────────────────────────────────────────
    patient       = _first(res.get("Patient", []), {})
    patient_token = override("patient_token", patient.get("id", "N/A"))

    # ── CPT / HCPCS ─────────────────────────────────────────────────────────
    sr  = _first(res.get("ServiceRequest",   []))
    mr  = _first(res.get("MedicationRequest",[]))
    src = sr or mr
    if src:
        coding   = _first(src.get("code", {}).get("coding", []), {})
        cpt      = override("cpt",      coding.get("code",    "N/A"))
        cpt_desc = override("cpt_desc", coding.get("display", "N/A"))
    else:
        cpt      = override("cpt",      "N/A")
        cpt_desc = override("cpt_desc", "N/A")

    # ── ICD-10 from Conditions ───────────────────────────────────────────────
    conditions = res.get("Condition", [])
    codes = [_first(c.get("code", {}).get("coding", []), {}).get("code",    "") for c in conditions]
    descs = [_first(c.get("code", {}).get("coding", []), {}).get("display", "") for c in conditions]
    codes = [x for x in codes if x]
    descs = [x for x in descs if x]
    icd10      = override("icd10",      ", ".join(codes) if codes else "N/A")
    icd10_desc = override("icd10_desc", "; ".join(descs) if descs else "N/A")

    # ── Coverage ─────────────────────────────────────────────────────────────
    cov        = _first(res.get("Coverage", []), {})
    fhir_payer = _first(cov.get("payor", [{}]), {}).get("identifier", {}).get("value", "N/A")
    fhir_plan  = next(
        (cls.get("value", "N/A")
         for cls in cov.get("class", [])
         if _first(cls.get("type", {}).get("coding", []), {}).get("code") == "plan"),
        "N/A",
    )
    payer         = override("payer",         fhir_payer)
    plan          = override("plan",          fhir_plan)
    subscriber_id = override("subscriber_id", cov.get("subscriberId", "N/A"))

    # ── NPI from Practitioner ────────────────────────────────────────────────
    prac     = _first(res.get("Practitioner", []), {})
    fhir_npi = next(
        (i.get("value") for i in prac.get("identifier", [])
         if "npi" in i.get("system", "").lower()),
        _first(prac.get("identifier", [{}]), {}).get("value", "N/A"),
    )
    npi = override("npi", fhir_npi or "N/A")

    # ── Clinical summary ─────────────────────────────────────────────────────
    if "clinical_summary" in meta:
        clinical_summary = meta["clinical_summary"]
    else:
        notes = (
            [note.get("text", "").strip()
             for c in conditions
             for note in c.get("note", [])]
            + [note.get("text", "").strip()
               for obs in res.get("Observation", [])
               for note in obs.get("note", [])]
        )
        clinical_summary = " ".join(n for n in notes if n) or "No clinical notes found."

    # ── Appeal-specific fields ───────────────────────────────────────────────
    denial_code = meta.get("denial_code")
    if not denial_code:
        for cr in res.get("ClaimResponse", []):
            for item in cr.get("item", []):
                for adj in item.get("adjudication", []):
                    code = _first(adj.get("reason", {}).get("coding", [{}]), {}).get("code")
                    if code:
                        denial_code = code
                        break

    denial_rationale = meta.get("denial_rationale")
    if not denial_rationale:
        for cr in res.get("ClaimResponse", []):
            for note in cr.get("processNote", []):
                text = note.get("text", "")
                if text:
                    denial_rationale = text
                    break

    pa_request_id = meta.get("pa_request_id")
    if not pa_request_id:
        for comm in res.get("Communication", []):
            for payload in comm.get("payload", []):
                m = re.search(r"PA Request ID:\s*(\S+)", payload.get("contentString", ""))
                if m:
                    pa_request_id = m.group(1).rstrip(".,")
                    break

    # ── Assemble case dict ───────────────────────────────────────────────────
    case: dict = {
        "type":             meta.get("type", "pipeline"),
        "patient_token":    patient_token,
        "cpt":              cpt,
        "cpt_desc":         cpt_desc,
        "icd10":            icd10,
        "icd10_desc":       icd10_desc,
        "payer":            payer,
        "plan":             plan,
        "npi":              npi,
        "subscriber_id":    subscriber_id,
        "clinical_summary": clinical_summary,
        "expected":         meta.get("expected", ""),
    }
    if meta.get("agent"):
        case["agent"] = meta["agent"]
    if pa_request_id:
        case["pa_request_id"] = pa_request_id
    if denial_code:
        case["denial_code"] = denial_code
    if denial_rationale:
        case["denial_rationale"] = denial_rationale

    label = meta.get("label", bundle.get("id", "UNKNOWN"))
    return label, case


# ── Public API ─────────────────────────────────────────────────────────────────

def build_cases_json(
    usecases_dir: pathlib.Path = USECASES_DIR,
    output_path:  pathlib.Path = CASES_JSON,
) -> dict[str, dict]:
    """
    Parse every *.json bundle in usecases_dir that contains _pa_meta,
    extract structured case data, sort by sort_order, and write output_path.

    Returns the resulting cases dict.
    """
    entries: list[tuple[int, str, dict]] = []

    for path in sorted(usecases_dir.glob("*.json")):
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
            if "_pa_meta" not in bundle:
                continue  # bundle without meta — skip silently
            label, case = _extract(bundle)
            sort_order  = bundle["_pa_meta"].get("sort_order", 99)
            entries.append((sort_order, label, case))
        except Exception as exc:
            print(f"  [build_cases] skipped {path.name}: {exc}")

    entries.sort(key=lambda x: x[0])
    cases = {label: case for _, label, case in entries}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cases, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [build_cases] wrote {len(cases)} cases -> {output_path.name}")
    return cases


if __name__ == "__main__":
    build_cases_json()
