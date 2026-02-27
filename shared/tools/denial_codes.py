"""
Denial code tools.

Provides lookup_denial_reason() and get_appeal_template() used by the
Appeal Strategy agent.
"""
from __future__ import annotations

import json
import pathlib
from typing import Annotated

from pydantic import Field

DATA_FILE = pathlib.Path(__file__).parent.parent.parent / "data" / "denial_codes.json"

_codes: dict | None = None


def _load_codes() -> dict:
    global _codes
    if _codes is None:
        _codes = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return _codes


def lookup_denial_reason(
    denial_code: Annotated[str, Field(description="Denial reason code (e.g. 'CO-50', 'PR-96', 'CO-97')")],
    payer_id: Annotated[str, Field(description="Payer identifier — used for payer-specific appeal guidance")] = "",
) -> dict:
    """Decode a denial reason code into its full description and recommended appeal pathway.

    Returns:
      - code: str
      - category: str ("CO" | "PR" | "OA")
      - description: str
      - appeal_type: str ("CLINICAL" | "BILLING" | "COVERAGE" | "ADMINISTRATIVE")
      - p2p_recommended: bool
      - p2p_success_rate: float | None
      - appeal_pathway: str
      - deadline_days: int
      - letter_type: str
      - tips: list[str]
      - found: bool
    """
    codes = _load_codes()
    entry = codes.get(denial_code)

    if not entry:
        # Try normalising the code
        normalised = denial_code.upper().replace(" ", "-")
        entry = codes.get(normalised)

    if not entry:
        return {
            "found": False,
            "code": denial_code,
            "category": denial_code.split("-")[0] if "-" in denial_code else "UNKNOWN",
            "description": f"Denial code '{denial_code}' not found in reference database.",
            "appeal_type": "UNKNOWN",
            "p2p_recommended": False,
            "p2p_success_rate": None,
            "appeal_pathway": "Contact payer for specific denial rationale before appealing.",
            "deadline_days": 60,
            "letter_type": "generic",
            "tips": ["Request detailed denial letter from payer", "Verify EOB remark codes for additional context"],
        }

    return {
        "found": True,
        "code": denial_code,
        **{k: v for k, v in entry.items() if not k.startswith("_")},
    }


def get_appeal_template(
    denial_code: Annotated[str, Field(description="Denial reason code (e.g. 'CO-50')")],
    cpt_code: Annotated[str, Field(description="CPT or HCPCS procedure code being appealed")],
    payer_id: Annotated[str, Field(description="Payer identifier")] = "",
) -> str:
    """Return a base appeal letter template for the given denial code and procedure.

    The Appeal Strategy agent should fill in the bracketed placeholders with
    patient-specific clinical evidence before sending.
    """
    codes = _load_codes()
    entry = codes.get(denial_code, {})
    letter_type = entry.get("letter_type", "generic")
    deadline_days = entry.get("deadline_days", 60)
    appeal_type = entry.get("appeal_type", "CLINICAL")

    templates = {
        "medical_necessity": f"""
RE: Appeal of Prior Authorization Denial — CPT {cpt_code}
Denial Code: {denial_code} | Payer: {payer_id}

Dear Medical Director,

We are writing to formally appeal the denial of prior authorization for [PROCEDURE NAME]
(CPT {cpt_code}) for patient [PATIENT TOKEN] under denial code {denial_code}.

CLINICAL JUSTIFICATION:
[Insert specific clinical evidence addressing each denied criterion]
- Diagnosis: [ICD-10 CODE] — [DIAGNOSIS DESCRIPTION]
- Clinical findings: [RELEVANT CLINICAL OBSERVATIONS]
- Policy criteria met: [LIST CRITERIA MET FROM LCD/NCD]

SUPPORTING EVIDENCE:
- [CLINICAL NOTE DATE]: [RELEVANT FINDING]
- [IMAGING REPORT]: [RELEVANT FINDING]
- [LAB/TEST RESULT]: [RELEVANT VALUE]

LITERATURE SUPPORT:
[Insert PubMed citations supporting medical necessity for this procedure]

We respectfully request reconsideration and approval of this PA request within
{deadline_days} days as outlined in your appeals process.

Sincerely,
[RENDERING PROVIDER NAME], [CREDENTIALS]
NPI: [RENDERING NPI]
""",
        "corrected_claim": f"""
RE: Corrected Claim Submission — CPT {cpt_code}
Original Denial Code: {denial_code} | Payer: {payer_id}

Dear Claims Department,

Please process the attached corrected claim for [PROCEDURE NAME] (CPT {cpt_code}).

CORRECTION DETAILS:
- Original claim date: [ORIGINAL SUBMISSION DATE]
- Correction reason: [SPECIFIC BILLING/CODING CORRECTION]
- Corrected field(s): [FIELD NAME] changed from [OLD VALUE] to [NEW VALUE]

The original claim was denied with code {denial_code}. This corrected submission
addresses the identified issue.

Sincerely,
[BILLING DEPARTMENT CONTACT]
""",
        "coverage_exception": f"""
RE: Coverage Exception Request — CPT {cpt_code}
Denial Code: {denial_code} | Payer: {payer_id}

Dear Coverage Review Team,

We are requesting a coverage exception for [PROCEDURE/DRUG NAME] (CPT/HCPCS {cpt_code})
for patient [PATIENT TOKEN].

EXCEPTION BASIS:
- Standard alternatives have been tried and failed: [LIST ALTERNATIVES TRIED]
- Medical necessity for this specific service: [CLINICAL RATIONALE]
- Risk of denial: [PATIENT SAFETY CONCERN IF DENIED]

SUPPORTING DOCUMENTATION:
[List attached documents]

Sincerely,
[REQUESTING PROVIDER]
""",
        "resubmission": f"""
RE: Claim Resubmission — CPT {cpt_code}
Original Denial Code: {denial_code} | Payer: {payer_id}

Dear Claims Department,

Please process the attached resubmission for [PROCEDURE NAME] (CPT {cpt_code}).

This resubmission includes: [LIST ADDITIONAL DOCUMENTATION / CORRECTIONS]

Original claim reference: [ORIGINAL ICN/CLAIM NUMBER]
Date of Service: [DOS]

Sincerely,
[BILLING CONTACT]
""",
        "generic": f"""
RE: Appeal — CPT {cpt_code}
Denial Code: {denial_code} | Payer: {payer_id}

Dear Review Department,

We are appealing the denial of [PROCEDURE NAME] (CPT {cpt_code}) for patient
[PATIENT TOKEN].

[Insert specific clinical, billing, or coverage rationale based on denial reason]

Please respond within {deadline_days} days.

Sincerely,
[PROVIDER / BILLING CONTACT]
""",
    }

    return templates.get(letter_type, templates["generic"]).strip()
