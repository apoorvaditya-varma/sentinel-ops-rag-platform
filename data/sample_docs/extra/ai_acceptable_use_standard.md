# Generative AI Acceptable Use Standard
Northwind Cloud Ltd. - Internal - Version 1.1 - Effective 2026-09-01

## 1. Scope
Applies to all staff and contractors using generative AI tools (chat assistants, code assistants,
image generators) for company work, whether company-provided or public.

## 2. Approved tools
- Approved: the internal Sentinel assistant, GitHub Copilot Business, and Gemini Enterprise under the company tenant.
- Public consumer chatbots may be used only with public information.

## 3. Data rules
- Never enter Restricted or Confidential data (customer PII, credentials, source code of core services,
  incident details) into a public AI tool.
- Prompts and outputs in approved tools are logged for 90 days for security review.

## 4. Use in engineering
- AI-generated code must go through the normal code review and SAST scan; the author remains accountable.
- AI must not approve pull requests, merge code or run production changes without a human decision.

## 5. Model and application risk
- Any product feature that uses an LLM requires a model risk assessment and red-team testing for prompt
  injection, data leakage and excessive agency before launch, following the NIST AI RMF and ISO/IEC 42001.
- Internal LLM applications must treat retrieved documents as untrusted input and cite their sources.

## 6. Reporting
Suspected data leaks through AI tools are security incidents: report within 1 hour to the SOC
(see the incident response plan). Policy owner: Head of Security. Review: annually.
