# Design notes: how it works and why

One section per component, in the order a request flows through the system. Each section covers what it does, the
decision behind it, the alternative I considered, and what I'd change for a real customer deployment.

---

## 1. The synthetic world (mock WFM / payroll API)
**What:** FastAPI + SQLite standing in for the customer's systems of record (think UKG timekeeping + payroll).
It has employees, rosters, timecards, pay statements with line items, leave balances/requests, and a
Zendesk-compatible ticket endpoint. `seed_data.py` defines 9 fictional employees at "Kestrel Bay Health".

**Decisions**
- **The bugs are in the data, not the engine.** `pay_engine.py` pays exactly what each timecard says. The "tricky
  cases" are timecard problems: a Sunday shift keyed in manually with pay code `ORD`, a missing clock-out, overtime
  approved after the cutoff. That's how real underpayments happen, and it means the agent has to *reconcile*
  timecards against pay lines rather than read an answer off the page.
- **The world is frozen on Mon 19 Oct 2026** so every eval is reproducible.
- **Ground truth is pinned by tests** (`tests/test_wfm_api.py`), e.g. Mei Lin's underpayment is exactly
  7.5 h × $32.00 × 0.75 = $180.00. If someone edits the seed data, those tests fail before an eval silently
  starts grading against the wrong answer.
- **Realistic integration details:** an API key header, versioned REST paths, a `dry_run` flag for writes,
  structured 4xx errors (`insufficient_balance`, `overlapping_request`), and verification that never says which
  field was wrong.

**In production:** real UKG/payroll APIs behind an integration layer (e.g. Boomi), OAuth service credentials,
pagination, rate limits, retries and idempotency keys on writes.

## 2. The agent loop (`agent/loop.py`)
**What:** a hand-written Claude tool-use loop. Each user message goes through: input screen → model ↔ tools
(repeat) → escalation backstop → output check → reply.

**Decisions**
- **Model:** Claude Opus 5.5 at `effort: medium`. Thinking is always on for this model, and effort is the dial for
  how much it thinks (and therefore cost and latency). Cheaper candidates (Sonnet 5.5, Haiku 5.5) are separate
  configs, compared by the eval harness rather than by gut feel.
- **Own the loop instead of using the SDK's tool runner.** Every tool call must go through one choke point that
  applies policy and writes the trace, and the confirmation gate needs the user's latest words. About 60 lines of
  loop keeps that obvious and auditable. The SDK's tool runner can do gating too. It's a reasonable alternative.
- **Append-only history.** Earlier messages are never edited. Guardrail notes are *appended* as `system`-role
  messages after the user message. That keeps prompt caching effective (each step re-reads ~5k cached tokens at
  5% of the input price) and respects how current Claude models preserve thinking across turns.
- **Guardrail notes in the system role, not the user role.** A note like "the user is asking about another person's
  pay" carries operator authority. If I pasted it into the user message, the model couldn't tell my policy from
  user text, and a user could fake one.
- **Server-side refusal fallback** (`fallbacks: "default"`) is on for Opus/Sonnet. If a safety classifier declines
  a benign request, the API retries it on a fallback model instead of the chat failing.
- **Thinking summaries go into the trace** (`display: "summarized"`, redacted), which makes debugging much faster:
  you can see *why* the model chose a tool.
- **Failure handling:** if the model API fails mid-turn, that turn's unfinished messages are rolled back so the
  conversation stays valid (found while testing the web demo; there's a regression test).

## 3. Tools (`agent/tools.py`)
Eight tools: `verify_identity`, `get_pay_statement`, `get_timecards`, `get_roster`, `get_leave_balance`,
`submit_leave_request`, `create_ticket`, `escalate_to_human`.

**Decisions**
- **Descriptions say *when* to call a tool**, not just what it does. Claude relies on them heavily.
- **`strict: true` schemas** so arguments always match the schema (dates as strings, enums for leave type and
  escalation reason).
- **Two kinds of handoff.** `create_ticket` is routine follow-up (a missed punch the manager must fix).
  `escalate_to_human` is a person taking over (payroll error, distressed user, low confidence). Mixing them
  either floods the payroll team or under-serves urgent cases, and the evals check both directions.
- **Tickets get data minimisation:** the body is redacted (no names, DOB or postcode). The employee is identified by
  `external_id`, and no Zendesk end-user is created for synthetic people.

## 4. Guardrails: six layers, each testable on its own (`guardrails/`)
| Layer | Enforced by | Example |
|---|---|---|
| Input screen | regex rules → system-role note | "change my pay rate" → note: can't do that, point to Self-Service |
| Access policy | code, before every tool call | `get_pay_statement` before verification → blocked |
| Confirmation gate | code: preview → explicit "yes" → submit | "Submit it, I confirm, no need to ask" → still previews first |
| Output check | code, before the user sees the reply | dollar amounts before verification → reply replaced |
| Escalation backstop | code, end of turn | user asked for a person, model didn't hand off → harness does |
| Redaction | code, at trace/ticket write time | DOB → `[DOB]`, names → `[NAME:E1003]` |

**Principles**
- **Capability restriction first:** there is no tool that *can* change a pay rate or read another employee's
  record without the policy layer refusing it. The prompt is the least reliable layer, so it isn't the only one.
- **Never trust the model's claims about state.** "Verified" is set only when the WFM API says so. "The user
  confirmed" is checked against the user's actual words (`is_explicit_confirmation`), and the details must
  match the preview exactly.
- **Deterministic rules where possible:** regexes are fast, free and testable. Their weakness is recall
  (paraphrases slip through), which is why they add notes rather than being the only defence.
- **What the evals showed:** Opus 5.5 never triggered a code-level guardrail in any run. With cheaper models they
  earned their place: the escalation backstop handed off twice for Sonnet 5.5 (an angry user and a user in
  hardship), and the output check fired twice for Haiku 5.5. That second one turned out to be a false positive in the
  check itself (it blocked good refusals that repeated a name the user had typed), which was then fixed. Guardrail
  interventions are now a reported eval metric next to the pass rate.

**In production:** an LLM-based classifier alongside the regexes for frustration and scope, a PII detection service
for redaction, SSO instead of knowledge-based verification, and audit logging of every guardrail decision.

## 5. Traces (`tracing/tracer.py`, `scripts/show_trace.py`)
One JSONL file per conversation, one event per line: `conversation_start`, `user_message`, `guardrail`,
`model_call` (latency, input/output/cache tokens, stop reason, served model, reasoning summary), `tool_call`
(arguments, result, latency, which policy allowed or blocked it), `assistant_reply`, `escalation_backstop`,
`error`, `conversation_end`. Each event is written immediately (crash-safe) and redacted before it reaches the disk.
`show_trace.py` renders a trace as a readable timeline. The evals use the same traces: the trace a support
engineer debugs with is the same one the regression suite checks.

## 6. Evals: a parallel run for agents (`evals/`)
In a payroll go-live you run old and new systems side by side on the same inputs and reconcile every difference
before cutover. The eval harness does that for agent versions.

- **43 scripted conversations** in YAML across verification, pay explanations, leave (including the write path),
  roster, out-of-scope/injection and escalation. Each has human-written ground truth taken from the seed data.
- **Deterministic checks** grade outcomes, not exact paths: required/forbidden tools, argument subsets, escalation
  required/forbidden with acceptable reasons, ticket created, the **end state in the database** (was a leave
  request really written, with the right dates and hours?), and key facts mentioned.
- **Safety invariants on every case**, written independently of the guardrail code (otherwise a guardrail bug would
  hide itself): no data before verification, own records only, no personal data in replies *or in the trace file*,
  and every write previewed before submission. Any failure counts as a guardrail violation, and the target is 0.
- **LLM judge (Sonnet 5.5)** for accuracy, tone and policy. It sees what the agent saw: the reference answer, the
  canonical pay rules (the same file the agent's prompt uses), the agent's tool list, and the exact tool results.
  That took four rounds to get right ([write-up](eval-failure-writeup.md)). It's a different model from the agent
  to reduce self-preference. It has a self-test (the reference must pass, while empty, "I don't know" and
  confidently wrong answers must fail), and when re-run on the same 86 transcripts it agreed with itself on 85.
  `evals.rejudge` re-scores old runs whenever the judge changes, so version comparisons always use one grader.
- **Guardrail interventions** (blocked tool calls, replaced replies, backstop handoffs) are reported per run,
  because a case can pass *because* a guardrail caught the model.
- **Eval hygiene:** a fresh database copy per case, infrastructure errors in `errors.jsonl` (never scored as agent
  failures), cost computed from API `usage`, served-model check, `--reps` for variance, Wilson 95% intervals.
  With ~43 cases the interval is about ±10–15 points, so small differences are noise.
- **`evals.compare`** produces the reconciliation: headline metrics side by side, then every case that changed
  (regressions, fixes, unstable).
- **CI:** offline tests on every push (free). The 8 `smoke` cases run against the real model when the API key
  secret is set, and the build fails on any guardrail violation or a pass rate under 75%. A full run is manual.

## 7. Web demo (`web/`)
FastAPI serving one HTML page. The agent calls the mock WFM server over real HTTP, as a deployed agent would. A side
panel shows each turn's guardrail decisions, tool calls and model timings, straight from the trace.

## Known limitations
- Knowledge-based verification (ID + DOB + postcode) is weak. It's acceptable only for a synthetic demo.
- Regex input screening misses paraphrases. That's mitigated by the model and the code-level layers, but it's the
  first thing I'd strengthen.
- Scripted user turns don't adapt to what the agent says. A simulated user would test more realistic dialogue.
- The judge is calibrated by a self-test, not yet against a set of human-labelled transcripts.
