# Demo video script (about 3 minutes)

**Setup before recording:** run `helpdesk-demo`, open http://127.0.0.1:8000 and, in a second window, a terminal in
the repo. Widen the browser so the "Under the hood" panel is visible. Expand "Synthetic test identities" once, then
collapse it. Have `docs/comparison.md` (or the latest `summary.md`) open in a tab. Record at 1080p. Zoom the browser
to about 125%.

---

### 0:00–0:20 · Hook
**On screen:** the chat page.
**Say:** "I've spent five years delivering payroll and workforce-management integrations, where a wrong number means
someone can't pay their rent. This is a customer-support AI agent for a payroll helpdesk, built the way I'd deploy it
for a customer: grounded in the customer's systems, with layered guardrails, traces, and an eval suite that works
like a payroll parallel run. All the data is synthetic."

### 0:20–1:05 · The hard case: reconciling pay
**Do:** click "Sunday shift looks underpaid". When asked, type `E1003, born 25 June 1998, postcode 4006`.
**Say while it runs:** "It won't touch personal data until identity is verified. That's enforced in code, not just
in the prompt. Now it's pulling the payslip and the timecards for the same period and reconciling them day by day."
**When the answer lands, point at:** the $180.00, the arithmetic, Sun 4 Oct, the manual-entry note, the ticket number.
**Say:** "It found the Sunday shift was keyed in manually with the ordinary pay code, so it was paid at 100% instead
of 175%. That's $180 short. It's a payroll error, so it hands off to a person with the evidence attached."
**Point at the side panel:** "Every tool call, guardrail decision and model step is here, and in a JSONL trace with
personal data redacted."

### 1:05–1:45 · Guardrails
**Do:** click "New chat", then "Ask about someone else's pay" ("What's Sofia Rossi's hourly rate?").
**Say:** "Other people's data is off limits. The input screen flags it and the model declines."
**Do:** "New chat", then "Prompt injection".
**Say:** "Same for prompt injection. And if the model ever did try, the access policy blocks any tool call for an
employee other than the verified one."
**Optional, if time:** "Book annual leave", then type the verification. **Say:** "Writes are two-phase: it shows a
preview and only submits after an explicit yes, which is checked against what the user actually typed, not what the
model claims."

### 1:45–2:40 · Evals: the parallel run
**Do:** switch to the terminal and run `python -m evals.run --tags smoke` (or show a finished run's output and
`summary.md`).
**Say:** "Here's the part I care about most. In payroll you never go live without a parallel run: old and new
systems on the same inputs, every difference reconciled. This harness does that for agents. There are 43 scripted
conversations with human-written ground truth. Deterministic checks cover the right tools, the right arguments,
whether it escalated when it should and didn't when it shouldn't, and the end state in the database. Safety
invariants run on every case: no data before verification, no personal data in replies or traces. Then an LLM judge
scores accuracy and tone against the reference *and* the actual tool data."
**Show:** the comparison report. **Say:** "Comparing two versions gives a reconciliation: which cases regressed,
which got fixed, and the cost and latency of each. It runs in GitHub Actions: a cheap smoke subset on every push,
and the build fails on any guardrail violation."
**Say (the story):** "The first runs reported 11 failures, and every one was a bug in my eval, not the agent. The
judge couldn't see the data the agent had used. I've written up how I root-caused it, because that's what makes
the numbers trustworthy."

### 2:40–3:00 · Close
**On screen:** the README architecture diagram.
**Say:** "So: a mock WFM and payroll API, a Claude agent with tool use, six guardrail layers you can test one at a
time, traces, and evals in CI. It's the job I'd be doing as an Agent Deployment Engineer, built with payroll-grade
rigour. The repo, PRD and write-up are linked below."

---
**Tips:** don't read it word for word. Rehearse the two live chats once, because response times are 10–25 s. If a
response is slow, talk over it about what the agent is doing (the side panel helps). Cut dead air in editing.
