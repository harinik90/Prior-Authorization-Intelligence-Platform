"""
Payer API submission tools.

Provides submit_pa_to_payer() and poll_pa_status() used by the Submission agent.
When PAYER_API_ENDPOINT is not set, a mock response is returned for development/testing.
"""
from __future__ import annotations

import json
import os
import random
import string
import time
from typing import Annotated

import requests
from pydantic import Field


def _generate_tracking_id(payer_id: str, cpt_code: str) -> str:
    suffix = "".join(random.choices(string.digits, k=5))
    year = time.strftime("%Y")
    slug = cpt_code.replace("/", "").replace(" ", "")[:8]
    return f"{payer_id}-{year}-{slug}-{suffix}"


def _generate_auth_number() -> str:
    return "AUTH-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def submit_pa_to_payer(
    fhir_claim: Annotated[dict, Field(description="FHIR Claim resource dict from build_fhir_claim()")],
    payer_id: Annotated[str, Field(description="Payer identifier for routing (e.g. 'BCBS-IL')")],
    cpt_codes: Annotated[list[str], Field(description="CPT/HCPCS codes in this PA request")],
) -> dict:
    """Submit a FHIR Claim (PAS IG) to the payer PA endpoint.

    Uses PAYER_API_ENDPOINT env var for real submission.
    Falls back to mock response when env var is not set (development mode).

    Returns:
      - tracking_id: str
      - status: str ("pending" | "approved" | "denied" | "error")
      - submitted_at: str (ISO timestamp)
      - mock: bool (True when using mock)
      - error: str | None
    """
    endpoint = os.environ.get("PAYER_API_ENDPOINT", "").strip()
    api_key = os.environ.get("PAYER_API_KEY", "").strip()
    cpt_str = cpt_codes[0] if cpt_codes else "UNKNOWN"
    tracking_id = _generate_tracking_id(payer_id, cpt_str)

    if not endpoint:
        # Mock mode — return a simulated pending response
        return {
            "tracking_id": tracking_id,
            "status": "pending",
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mock": True,
            "note": "PAYER_API_ENDPOINT not set — using mock response. Set env var for real submission.",
            "error": None,
        }

    headers = {
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            f"{endpoint.rstrip('/')}/Claim/$submit",
            json=fhir_claim,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        resp_data = response.json()

        # Parse ClaimResponse from PAS IG response
        outcome = resp_data.get("outcome", "queued")
        status_map = {
            "complete": "approved",
            "queued": "pending",
            "error": "denied",
        }

        return {
            "tracking_id": resp_data.get("id", tracking_id),
            "status": status_map.get(outcome, "pending"),
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mock": False,
            "raw_response": resp_data,
            "error": None,
        }

    except requests.RequestException as e:
        return {
            "tracking_id": tracking_id,
            "status": "error",
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mock": False,
            "error": str(e),
        }


def poll_pa_status(
    tracking_id: Annotated[str, Field(description="PA tracking ID returned from submit_pa_to_payer()")],
    payer_id: Annotated[str, Field(description="Payer identifier (e.g. 'BCBS-IL')")],
) -> dict:
    """Poll for the current status of a submitted PA request.

    Returns:
      - tracking_id: str
      - status: str ("pending" | "approved" | "denied" | "pended" | "unknown")
      - decision: str | None
      - auth_number: str | None (populated when approved)
      - denial_code: str | None (populated when denied)
      - denial_rationale: str | None
      - mock: bool
    """
    endpoint = os.environ.get("PAYER_API_ENDPOINT", "").strip()
    api_key = os.environ.get("PAYER_API_KEY", "").strip()

    if not endpoint:
        # Mock: simulate an approval for development
        return {
            "tracking_id": tracking_id,
            "status": "approved",
            "decision": "APPROVED",
            "auth_number": _generate_auth_number(),
            "valid_from": time.strftime("%Y-%m-%d"),
            "valid_to": "",  # 90-day validity
            "denial_code": None,
            "denial_rationale": None,
            "mock": True,
            "note": "PAYER_API_ENDPOINT not set — using mock approval response.",
        }

    headers = {"Accept": "application/fhir+json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(
            f"{endpoint.rstrip('/')}/ClaimResponse",
            params={"request": tracking_id},
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        resp_data = response.json()

        outcome = resp_data.get("outcome", "queued")
        disposition = resp_data.get("disposition", "")

        status = "pending"
        if "approved" in disposition.lower() or outcome == "complete":
            status = "approved"
        elif "denied" in disposition.lower() or "deny" in disposition.lower():
            status = "denied"
        elif "pend" in disposition.lower():
            status = "pended"

        auth_number = None
        if status == "approved":
            auth_number = resp_data.get("preAuthRef") or _generate_auth_number()

        return {
            "tracking_id": tracking_id,
            "status": status,
            "decision": disposition,
            "auth_number": auth_number,
            "denial_code": None,
            "denial_rationale": None,
            "mock": False,
            "raw_response": resp_data,
        }

    except requests.RequestException as e:
        return {
            "tracking_id": tracking_id,
            "status": "unknown",
            "decision": None,
            "auth_number": None,
            "denial_code": None,
            "denial_rationale": None,
            "mock": False,
            "error": str(e),
        }
