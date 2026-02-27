# Glossary

Key terms used across the Prior Authorization Intelligence Platform.

---

## Healthcare & Clinical

**Prior Authorization (PA)**
A requirement by health insurance payers that providers obtain approval before delivering certain procedures, medications, or services. Failure to obtain PA can result in claim denial.

**CPT Code**
Current Procedural Terminology — a standardized numeric code identifying a medical procedure or service (e.g. `27447` = Total Knee Arthroplasty). Maintained by the American Medical Association.

**ICD-10**
International Classification of Diseases, 10th Revision — a standardized diagnostic code system used to classify diseases and health conditions (e.g. `M17.11` = Primary osteoarthritis, right knee).

**HCPCS**
Healthcare Common Procedure Coding System — extends CPT codes to cover drugs, supplies, and non-physician services (e.g. `J0129` = Abatacept injection, a biologic).

**NPI (National Provider Identifier)**
A unique 10-digit identifier assigned to healthcare providers in the US. Verified via the NPPES registry.

**Payer**
A health insurance company or government program that pays for healthcare services (e.g. BCBS-IL, UHC Medicare Advantage, Cigna, Humana, Aetna).

**LCD (Local Coverage Determination)**
A CMS decision by a Medicare Administrative Contractor on whether a service is covered under Medicare in a specific geographic region.

**NCD (National Coverage Determination)**
A nationwide CMS decision on whether Medicare covers a specific service, item, or technology.

**PEND**
A PA decision status meaning the request is incomplete or requires additional documentation before a final approval or denial is issued.

**CO-50**
A Medicare denial code meaning "Not medically necessary as submitted." Commonly used in spinal fusion and other high-cost procedure denials.

**KOOS / KSS**
Knee Osteoarthritis Outcome Score / Knee Society Score — functional impairment scoring tools required by many payers before approving knee replacement surgery.

**BMI**
Body Mass Index — a numeric measure of body fat based on height and weight. Payers such as BCBS-IL require BMI documentation (e.g. BMI < 40) for TKA approval.

**Step Therapy**
A payer requirement that patients try lower-cost treatments (e.g. conventional DMARDs) before approving higher-cost biologics. Common in biologic drug PA requests.

**DMARD**
Disease-Modifying Antirheumatic Drug — a class of medications used to treat rheumatoid arthritis. Conventional DMARDs (methotrexate, hydroxychloroquine) must typically be trialed before biologic DMARDs are approved.

**Fleischner Criteria**
Evidence-based guidelines for the management of incidentally detected pulmonary nodules. Used by payers to assess medical necessity for CT-guided lung biopsies.

**Peer-to-Peer (P2P) Review**
A process where the treating physician speaks directly with the payer's medical director to discuss a denied or pended PA request and provide clinical justification.

**RCM (Revenue Cycle Management)**
The administrative and clinical processes healthcare providers use to manage claims, payments, and PA workflows.

---

## FHIR & Interoperability

**FHIR (Fast Healthcare Interoperability Resources)**
An HL7 standard for exchanging healthcare data electronically. This system builds FHIR R4 Claims for PA submission.

**Da Vinci PAS IG**
Prior Authorization Support Implementation Guide — a FHIR IG published by the Da Vinci Project that defines how to structure and exchange PA requests between providers and payers.

**FHIR R4 Claim**
A structured FHIR resource representing a PA or billing claim, containing procedure codes, diagnosis codes, provider info, and insurance coverage.

---

## AI & Technology

**MAF (Microsoft Agent Framework)**
The orchestration framework used to build and run the multi-agent pipeline. Provides `WorkflowBuilder`, `ChatAgent`, and event-driven agent coordination.

**Azure AI Foundry**
Microsoft's hosted AI agent service. Coverage Prediction and Submission agents run as persistent hosted agents using the threads + runs model via `AzureAIAgentClient`.

**APIM (Azure API Management)**
Azure's API gateway. Used to route Claude agent calls through a managed endpoint with subscription key authentication (`Ocp-Apim-Subscription-Key`).

**MCP (Model Context Protocol)**
An open protocol that allows AI agents to call external tools and data sources at runtime. Healthcare MCP servers (ICD-10, CMS Coverage, NPI Registry, PubMed) are used mid-pipeline.

**HostedMCPTool**
A MAF tool wrapper that connects to a remote MCP server over HTTP. Loaded from the Claude Code plugin registry at agent initialization.

**AzureAIAgentClient**
The MAF client for Azure AI Foundry's hosted agent service. Uses the threads + runs model; agents persist on Foundry between calls (`should_cleanup_agent=False`).

**AnthropicClient**
The MAF client for Claude models. Routed through Azure APIM via `AsyncAnthropic` with a custom `base_url`.

**Context Accumulation**
The pattern used in this pipeline where each agent's output is prepended to the next agent's prompt, giving downstream agents the full reasoning history of prior stages.

---

## Abbreviations Quick Reference

| Term | Meaning |
|---|---|
| PA | Prior Authorization |
| CPT | Current Procedural Terminology |
| ICD-10 | International Classification of Diseases, 10th Revision |
| HCPCS | Healthcare Common Procedure Coding System |
| NPI | National Provider Identifier |
| LCD | Local Coverage Determination |
| NCD | National Coverage Determination |
| FHIR | Fast Healthcare Interoperability Resources |
| PAS IG | Prior Authorization Support Implementation Guide |
| MAF | Microsoft Agent Framework |
| APIM | Azure API Management |
| MCP | Model Context Protocol |
| RCM | Revenue Cycle Management |
| P2P | Peer-to-Peer Review |
| DMARD | Disease-Modifying Antirheumatic Drug |
