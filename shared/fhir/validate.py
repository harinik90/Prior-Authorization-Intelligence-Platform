"""
FHIR R4 resource structure validators.

Lightweight validation helpers — check required fields and coding system
URIs before submitting to payer endpoints. Profile validation failures
cause silent rejections at payer FHIR endpoints.
"""
from __future__ import annotations


REQUIRED_FIELDS = {
    "Claim": ["resourceType", "status", "type", "use", "patient", "created",
              "insurer", "provider", "priority", "insurance", "item"],
    "Patient": ["resourceType", "id"],
    "Coverage": ["resourceType", "status", "beneficiary", "payor"],
    "ServiceRequest": ["resourceType", "status", "intent", "code", "subject"],
    "Condition": ["resourceType", "clinicalStatus", "code", "subject"],
    "Practitioner": ["resourceType", "identifier"],
}

VALID_CODING_SYSTEMS = {
    "icd10": "http://hl7.org/fhir/sid/icd-10-cm",
    "cpt": "http://www.ama-assn.org/go/cpt",
    "hcpcs": "https://www.cms.gov/Medicare/Coding/HCPCSReleaseCodeSets",
    "npi": "http://hl7.org/fhir/sid/us-npi",
    "loinc": "http://loinc.org",
    "snomed": "http://snomed.info/sct",
    "nucc": "http://nucc.org/provider-taxonomy",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
}


def validate_resource(resource: dict) -> dict:
    """Validate a FHIR R4 resource for required fields and known coding systems.

    Returns:
      - valid: bool
      - errors: list[str] — blocking issues
      - warnings: list[str] — non-blocking issues
    """
    rtype = resource.get("resourceType", "UNKNOWN")
    errors: list[str] = []
    warnings: list[str] = []

    # Check required fields
    required = REQUIRED_FIELDS.get(rtype, [])
    for field in required:
        if field not in resource:
            errors.append(f"Missing required field: '{field}' in {rtype}")

    # Check Claim-specific rules (PAS IG)
    if rtype == "Claim":
        use = resource.get("use")
        if use != "preauthorization":
            errors.append(f"Claim.use must be 'preauthorization' for PA submission, got: '{use}'")

        items = resource.get("item", [])
        if not items:
            errors.append("Claim.item must contain at least one line item")

        for i, item in enumerate(items):
            coding = item.get("productOrService", {}).get("coding", [])
            if not coding:
                errors.append(f"Claim.item[{i}].productOrService.coding is empty")
            else:
                system = coding[0].get("system", "")
                valid_systems = [VALID_CODING_SYSTEMS["cpt"], VALID_CODING_SYSTEMS["hcpcs"]]
                if system not in valid_systems:
                    warnings.append(
                        f"Claim.item[{i}].productOrService.coding.system '{system}' "
                        "is not a standard CPT or HCPCS system URI"
                    )

        diagnoses = resource.get("diagnosis", [])
        if not diagnoses:
            errors.append("Claim must include at least one diagnosis")

        for i, dx in enumerate(diagnoses):
            coding = dx.get("diagnosisCodeableConcept", {}).get("coding", [])
            if coding:
                system = coding[0].get("system", "")
                if system != VALID_CODING_SYSTEMS["icd10"]:
                    warnings.append(
                        f"diagnosis[{i}].coding.system should be '{VALID_CODING_SYSTEMS['icd10']}'"
                    )

    # Check Condition coding
    if rtype == "Condition":
        coding = resource.get("code", {}).get("coding", [])
        if coding:
            system = coding[0].get("system", "")
            if system != VALID_CODING_SYSTEMS["icd10"]:
                warnings.append(
                    f"Condition.code.coding.system should be '{VALID_CODING_SYSTEMS['icd10']}', got '{system}'"
                )

    # Check Practitioner NPI
    if rtype == "Practitioner":
        identifiers = resource.get("identifier", [])
        has_npi = any(
            id_.get("system") == VALID_CODING_SYSTEMS["npi"]
            for id_ in identifiers
        )
        if not has_npi:
            warnings.append("Practitioner identifier should include an NPI with system 'http://hl7.org/fhir/sid/us-npi'")

    return {
        "valid": len(errors) == 0,
        "resourceType": rtype,
        "errors": errors,
        "warnings": warnings,
    }


def validate_bundle(bundle: dict) -> dict:
    """Validate all resources in a FHIR Bundle.

    Returns:
      - valid: bool
      - total_errors: int
      - total_warnings: int
      - results: list of per-resource validation results
    """
    if bundle.get("resourceType") != "Bundle":
        return {
            "valid": False,
            "total_errors": 1,
            "total_warnings": 0,
            "results": [{"error": "Root resource must be a FHIR Bundle"}],
        }

    results = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource:
            results.append(validate_resource(resource))

    total_errors = sum(len(r.get("errors", [])) for r in results)
    total_warnings = sum(len(r.get("warnings", [])) for r in results)

    return {
        "valid": total_errors == 0,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "results": results,
    }
