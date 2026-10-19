# PRD: Payroll & HR Helpdesk Agent

**Owner:** Ben Huxley · **Status:** v1 build, week of 19 Oct 2026 · **Data:** synthetic only (fictional employer "Kestrel Bay Health")

## Problem
Payroll helpdesks at large shift-based employers (hospitals, aged care) get a spike of tickets after every pay run.
Most are the same few questions: *"Why is my pay short?"*, *"What's my leave balance?"*, *"Has my leave been approved?"*,
*"When's my next shift?"*. Each one needs a payroll officer to open the WFM system, line up timecards against pay lines
and explain the result. These answers are high-stakes. A wrong explanation destroys trust in payroll, and showing one
employee's data to another is a privacy incident under the Australian Privacy Principles.

## Users
| User | Need |
|---|---|
| **Employee** (primary) | A fast, correct, plain-English answer about *their own* pay, leave and roster, any time of day |
| **Payroll officer** | Fewer repetitive tickets. The escalations that do arrive come with the evidence attached (dates, hours, pay codes) |
| **Payroll/HRIS manager** (owner) | Deflection without risk: no data leaks, no unauthorised changes, an audit trail for every answer |

## In scope (v1)
- Identity verification (employee ID + date of birth + postcode) before *any* personal data is shown.
- Pay statement explanations that **reconcile timecards against pay lines**: penalty rates, overtime tiers, allowances,
  public holidays, missed punches, late approvals.
- Leave balances, leave request status, and **submitting a leave request**. The request is only written after the
  employee explicitly confirms the exact details.
- Roster lookups (next shift, shifts in a date range).
- Escalation into ticketing (Zendesk, with a mock for CI): `create_ticket` for routine follow-ups, `escalate_to_human` for
  payroll errors, distressed users, explicit requests for a person, low confidence and verification lockout.
- A JSONL trace per conversation, plus an eval/regression suite that runs in CI.

## Out of scope (v1)
Changing pay rates, bank or tax details. Approving or cancelling leave. Tax, financial or legal advice. Any other
employee's data, including for managers. Real SSO authentication. Voice channel (stretch goal). Real client data, ever.

## Success metrics (measured by the eval suite, see README)
| Metric | Definition | Target |
|---|---|---|
| **Resolution rate** | Bot-resolvable cases fully resolved with no human needed | ≥ 80% |
| **Correct-escalation rate** | Cases that policy says must escalate, escalated with an acceptable reason | ≥ 95% |
| **False-escalation rate** | Cases that should *not* escalate, but did | ≤ 10% |
| **Guardrail violations** | Data shown before verification, personal data in output or traces, unconfirmed writes, other employees' data | **= 0** |
| **Answer accuracy / tone** | LLM-judge rubric score against a human-written reference answer (1–5) | ≥ 4.0 / ≥ 4.0 |
| **Cost and latency** | Measured from API `usage` and timings per conversation | Reported every run |

## Approach (one line each)
- **Agent:** Claude (Opus 5.5) in a hand-written tool-use loop. Every tool call passes through one policy choke point.
- **Guardrails in layers, each testable alone:** input screen → tool-access policy (verification, own-data-only) →
  write-confirmation gate → output check → escalation backstop → log redaction. Capability restriction first:
  there is no tool that *can* change a pay rate.
- **Evals as a payroll parallel run:** each agent version runs the same conversations against the same synthetic ground
  truth, and differences are reconciled case by case before a change ships.

## Risks and mitigations
| Risk | Mitigation |
|---|---|
| Hallucinated pay explanation | Answers grounded only in tool data. Judge scores accuracy against reference answers. The agent must escalate (`low_confidence`) rather than guess |
| Privacy leak (other employee, PII in logs) | Verification gate enforced in code, not just the prompt. Employee-ID match on every call. Output check. Redaction at trace-write time |
| Prompt injection / social engineering ("I'm her manager") | The policy layer ignores what the model *claims*. Guardrail notes go in the system role. No tools exist beyond the employee's own data |
| Wrong or unwanted write | Two-phase leave submission: preview → explicit user "yes" (checked deterministically) → submit |
| Over-escalation kills deflection | Eval cases in both directions (must escalate / must not escalate) |
| Regressions when the prompt or model changes | Regression suite on every push (smoke subset) and a full parallel-run comparison report between versions |
| Weak knowledge-based auth (DOB + postcode) | Acceptable for a demo only. Production would sit behind SSO, and verification would become a session claim |

## Milestones
Mon–Tue: PRD, mock WFM API, CLI agent loop · Wed: guardrails, ticketing · Thu: evals, CI, traces, fix findings ·
Fri: web UI, README, demo video.
