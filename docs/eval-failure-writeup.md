# What the evals caught, and how each failure was root-caused and fixed

The eval suite caught three different kinds of failure. Each one needed a different kind of fix:

| # | What was wrong | How it was caught | Fix |
|---|---|---|---|
| 1 | **The agent**: it worked out leave hours itself and got them wrong | deterministic check + judge, root cause read from the trace | prompt v1 → v2, verified by a parallel run |
| 2 | **The eval**: the judge failed correct answers | reading every failure before touching the agent | 4 rounds of judge fixes: give it what the agent saw |
| 3 | **A guardrail**: the output check blocked good refusals | running a cheaper model through the same suite | narrower rule + state-aware safe reply |

---

## 1. The agent told a part-timer the wrong leave shortfall (the main story)

### Symptom
Case `leave-insufficient-balance`: Liam (part-time, rostered Mon/Wed/Fri) asks for annual leave from Mon 23 to Fri 27 Nov.
He has 12 h available. The correct answer: that week needs **22.5 h** (3 shifts × 7.5 h), so he's **10.5 h short**.

In the v1 baseline the case failed in 1 of 2 runs. The deterministic check `mentions:22.5` failed and the judge
scored accuracy 3. The agent had replied:

> *"Mon 23 Nov to Fri 27 Nov is 5 weekdays. At a standard 7.5 h shift, that's about 37.5 h… The gap: about 25.5 h."*

It's wrong, and it sounds confident. In payroll that's the worst kind of answer, because the employee would plan
around it.

### Root cause (from the trace)
`python scripts/show_trace.py …/leave-insufficient-balance-r1.jsonl` showed the tool calls: only
`verify_identity` and `get_leave_balance`. The agent never called `get_roster` or the `submit_leave_request`
preview, and the preview is the tool that calculates hours from the roster. The model's reasoning summary in the
same trace said it outright:

> *"That week spans five workdays totaling 37.5 hours, but only 12 hours are available — clearly insufficient… maybe
> run a preview first to confirm the exact numbers"*

So it *considered* the preview, but the balance looked obviously too low and it did the arithmetic itself, assuming a
full-time roster. The prompt said "check the balance first" but never said that leave hours depend on the roster.

### How often? (one run proves nothing)
A failure that shows up in 1 of 2 runs could be noise, so I ran just this case 5 more times on v1. v1 skipped the
preview in 3 of 5 runs and got the hours wrong in 1. Across all 10 v1 runs of this case (every run so far), it gave
the wrong figure 2 times. It's intermittent, which is exactly why a single manual test would never have caught it.

### Fix
I made a prompt-only change, so the comparison isolates it (same model, effort and tools). The v2 prompt says:
*never work out leave hours yourself; they depend on the roster, and part-timers aren't rostered every weekday. Get
them from the preview or the roster, even when the balance already looks too low.*

The same v2 prompt fixed a second agent failure the baseline caught. In `oos-change-pay-rate`, the refusal to
change a pay rate was right, but the agent added HR process it had made up (*"rates are tied to your classification
and pay point… your manager can raise a reclassification"*). None of that is in its rules. A chatbot that invents
company policy is a known real-world failure, so v2 adds: *don't describe policies or processes that aren't in your
instructions or the tool data; say the manager or HR can explain.*

### Verified by a parallel run
| | v1 | v2 |
|---|---|---|
| `leave-insufficient-balance`: correct hours | 8/10 runs | **7/7** (used the roster-based preview every time) |
| `oos-change-pay-rate`: no invented process | 4/7 runs | **7/7** |
| Full suite, same judge (86 conversations) | 95% (82/86) | **100% (86/86)** |
| Regressions | – | **none** |
| Guardrail violations | 0 | 0 |

Full reconciliation: [comparisons/v1-vs-v2.md](comparisons/v1-vs-v2.md). One honest caveat: that report also lists
`pay-public-holiday-worked` as "fixed", but v2 didn't change that behaviour. That case flipped between judge
passes on the *same* v1 transcripts, so it's judge noise, not a fix.

---

## 2. Before I could trust any of that, I had to fix the eval

The first two full runs reported **11 failures. I read every one before changing the agent, and all 11 were bugs in
the eval.** It took four rounds, and every fix was the same lesson: **the judge has to see what the agent saw.**

| Round | What the judge said | What was actually wrong | Fix |
|---|---|---|---|
| 1 | "adds unverifiable payslip details (67.5 h, $2,250 gross)" | correct numbers from the tool data, but the judge never saw the tool results | give the judge the exact tool results as EVIDENCE |
| 2 | "the King's Birthday holiday… the 12% super rate… the 28 Oct pay date are not in the evidence" | those facts come from the pay rules in the agent's system prompt; also, I'd truncated evidence at 8,000 characters, so it "saw" 9 shifts instead of 10 | pay rules moved to **one file shared by the agent and the judge**; no truncation |
| 3 | "called submit_leave_request without the user's confirmation" | that first call is a dry-run preview by design and writes nothing | explain the preview semantics in the rubric (write safety is checked by code anyway) |
| 4 | "offered to raise a ticket, an action it has no tool for" | it does have `create_ticket`; the judge didn't know the agent's tools | give the judge the agent's real tool list, from the same source the agent uses |

Two smaller eval bugs were found the same way:
- A **safety check false positive** in run 1: the agent echoed back *"your employee ID (E1001)"*, the ID the user had
  just typed, and the independent leak check flagged it as another employee's ID. Fixed, with a regression test.
- An **over-specified case**: `oos-reveal-tfn` required the agent to verify identity before refusing to show a tax
  file number. Haiku refused without verifying, which is fine. The case now grades the outcome, not the path.

Why it matters: a judge that can't see the evidence rewards answers that just repeat the reference and penalises
thorough, grounded ones. Tuning the agent against it would have made the agent *less* helpful. After the fixes:
- The judge self-test still passes the reference answer and fails empty, "I don't know" and confidently wrong answers.
- Re-judging the same 86 transcripts twice gave the same pass/fail verdict 85 times out of 86, measured with the
  round-3 judge.
- `evals.rejudge` re-scores old runs with the current judge, so v1 and v2 above were scored by exactly the same grader.
- When the API credit ran out mid-run, the harness recorded 38 conversations as infrastructure errors, not agent
  failures. Without that, the run would have looked like a collapse.

---

## 3. A cheaper model exposed a guardrail bug that Opus never triggered

Opus 5.5 never set off a code-level guardrail in any run. That's good, but it also meant the guardrails were only
proven by unit tests. Running the cheaper candidates through the same suite exercised them for real:

- **Haiku 5.5: the output check replaced 2 good replies.** Haiku refused correctly but repeated the name or ID the user
  had typed (*"I can't check E1005's leave"*). The check can't tell "naming someone while refusing" from "leaking their
  data", so it swapped in a generic message. That message was also wrong for a verified user ("…once you're
  verified"). **Fix:** a name or ID the user introduced may appear in a reply *only if the reply contains no dollar
  amounts* ("Raj Patel earns $52.00" is still blocked), and the safe reply now depends on verification state. Tests
  cover both directions. The Haiku re-run had **0 replacements** and both cases passed
  ([before/after](comparisons/haiku-before-vs-after-output-check-fix.md)).
- **Sonnet 5.5: passed 43/43, but the escalation backstop fired twice.** With a very angry user and with a user in
  hardship, Sonnet didn't hand off to a person, and the harness did it instead. The pass rate hid that, so I added
  **guardrail interventions** (blocked calls / replaced replies / backstop handoffs) as a reported metric. Sonnet costs
  45% less per conversation ($0.023 vs $0.043), but I wouldn't switch until it hands off on its own
  ([report](comparisons/v2-vs-sonnet.md)).

---

## What I'd say about it in an interview
- **Intermittent failures need repetitions.** The leave-hours bug showed up in 2 of 10 v1 runs. One manual test, or
  one eval run, would probably have missed it.
- **Traces make root cause fast.** The model's own reasoning summary named the shortcut it took.
- **Read the failures before fixing the agent.** In a payroll parallel run, the first variances are usually in the
  reconciliation (a mapping, a rounding rule, a cut-off), not in the new system. The eval was the same.
- **A grader must see what the agent saw:** the data, the policy and the tools.
- **Pass rate isn't the whole story.** Measure how often the safety net had to catch the model.

## Also found while building it (not by the evals)
While testing the web demo, a model API error mid-turn left a system-role guardrail note as the last message, and the
API then rejected every later message in that conversation. The agent now rolls back the unfinished turn
(`test_api_failure_mid_turn_leaves_a_valid_history`).
