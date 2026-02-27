"""
FHIR Claim builder tool (PAS IG).

Provides build_fhir_claim() used by the Submission agent to construct a
FHIR Claim resource conforming to the Prior Authorization Support (PAS) IG.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from pydantic import Field


def build_fhir_claim(
    patient_token: Annotated[str, Field(description="De-identified patient token (e.g. 'PT-78432')")],
    payer_id: Annotated[str, Field(description="Payer identifier (e.g. 'BCBS-IL')")],
    cpt_codes: Annotated[list[str], Field(description="List of CPT or HCPCS procedure codes")],
    icd10_codes: Annotated[list[str], Field(description="List of ICD-10-CM diagnosis codes")],
    rendering_npi: Annotated[str, Field(description="Rendering provider NPI number")],
    subscriber_id: Annotated[str, Field(description="Payer member/subscriber ID")],
    service_date: Annotated[str, Field(description="Requested service date (YYYY-MM-DD)")] = "",
    clinical_summary: Annotated[str, Field(description="Brief clinical summary for the PA request")] = "",
) -> dict:
    """Construct a FHIR Claim resource (PAS IG) from PA package data.

    Returns a FHIR R4 Claim resource dict ready for submission.
    """
    claim_id = f"claim-{uuid.uuid4().hex[:8]}"
    svc_date = service_date or date.today().isoformat()

    # Build diagnosis entries
    diagnoses = [
        {
            "sequence": i + 1,
            "diagnosisCodeableConcept": {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/sid/icd-10-cm",
                        "code": code,
                    }
                ]
            },
        }
        for i, code in enumerate(icd10_codes)
    ]

    # Build line items for each CPT code
    items = []
    for i, cpt in enumerate(cpt_codes):
        system = (
            "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets"
            if cpt.startswith(("J", "G", "A", "B", "C", "D", "E", "K", "L", "M", "P", "Q", "R", "S", "T", "V"))
            else "http://www.ama-assn.org/go/cpt"
        )
        items.append(
            {
                "sequence": i + 1,
                "productOrService": {"coding": [{"system": system, "code": cpt}]},
                "servicedDate": svc_date,
                "diagnosisLinkId": list(range(1, len(icd10_codes) + 1)),
            }
        )

    claim = {
        "resourceType": "Claim",
        "id": claim_id,
        "meta": {
            "profile": [
                "http://hl7.org/fhir/us/davinci-pas/StructureDefinition/profile-claim"
            ]
        },
        "status": "active",
        "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/claim-type", "code": "professional"}]},
        "use": "preauthorization",
        "patient": {
            "identifier": {"system": "urn:pa-system:patient-token", "value": patient_token}
        },
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "insurer": {
            "identifier": {"system": "urn:pa-system:payer-id", "value": payer_id}
        },
        "provider": {
            "identifier": {"system": "http://hl7.org/fhir/sid/us-npi", "value": rendering_npi}
        },
        "priority": {"coding": [{"code": "normal"}]},
        "insurance": [
            {
                "sequence": 1,
                "focal": True,
                "coverage": {
                    "identifier": {
                        "system": "urn:pa-system:subscriber-id",
                        "value": subscriber_id,
                    }
                },
            }
        ],
        "diagnosis": diagnoses,
        "item": items,
    }

    if clinical_summary:
        claim["supportingInfo"] = [
            {
                "sequence": 1,
                "category": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/claiminformationcategory", "code": "info"}]
                },
                "valueString": clinical_summary,
            }
        ]

    return claim
