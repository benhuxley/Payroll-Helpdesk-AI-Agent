# Parallel run: agent version comparison

- **A (current):** v2-opus-5.5 (claude-opus-5-5, effort medium, system_v2.md) · run `v2-final` · 2 rep(s)
- **B (candidate):** cand-sonnet-5.5 (claude-sonnet-5-5, effort medium, system_v2.md) · run `cand-sonnet` · 1 rep(s)
- Same cases, same synthetic data, same deterministic checks and judge.

## Headline metrics

| Metric | A | B |
|---|---|---|
| Cases run (errors) | 86 (0) | 43 (0) |
| Overall pass rate (95% CI) | 100% (96%–100%) | 100% (92%–100%) |
| Deterministic checks pass rate | 100% | 100% |
| Judge pass rate | 100% | 100% |
| Resolution rate | 100% (46/46) | 100% (23/23) |
| Correct-escalation rate | 100% (14/14) | 100% (7/7) |
| False-escalation rate | 0% (0/52) | 0% (0/26) |
| Guardrail violations | 0 | 0 |
| Guardrail interventions: blocked calls / replaced replies / backstop handoffs | 0 / 0 / 0 | 0 / 0 / 2 |
| Mean accuracy (1–5) | 4.67 | 4.79 |
| Mean tone (1–5) | 4.19 | 4.40 |
| Mean cost per conversation | $0.043 | $0.023 |
| Turn latency p50 / p95 | 7.2 s / 19.6 s | 6.4 s / 18.5 s |

## Variances (cases whose result differs)

None: both versions produced the same result on every case.
## How to read this

With 86 conversations, the 95% confidence interval on a pass rate is roughly ±2 points, so a difference of a case or two is noise. Read the variances above, not just the totals: a guardrail violation or a regression on a safety case blocks release whatever the headline pass rate says.
