# Parallel run: agent version comparison

- **A (current):** v1-opus-5.5 (claude-opus-5-5, effort medium, system_v1.md) · run `v1-final` · 2 rep(s)
- **B (candidate):** v2-opus-5.5 (claude-opus-5-5, effort medium, system_v2.md) · run `v2-final` · 2 rep(s)
- Same cases, same synthetic data, same deterministic checks and judge.

## Headline metrics

| Metric | A | B |
|---|---|---|
| Cases run (errors) | 86 (0) | 86 (0) |
| Overall pass rate (95% CI) | 95% (89%–98%) | 100% (96%–100%) |
| Deterministic checks pass rate | 99% | 100% |
| Judge pass rate | 95% | 100% |
| Resolution rate | 96% (44/46) | 100% (46/46) |
| Correct-escalation rate | 100% (14/14) | 100% (14/14) |
| False-escalation rate | 0% (0/52) | 0% (0/52) |
| Guardrail violations | 0 | 0 |
| Guardrail interventions: blocked calls / replaced replies / backstop handoffs | 0 / 0 / 0 | 0 / 0 / 0 |
| Mean accuracy (1–5) | 4.57 | 4.67 |
| Mean tone (1–5) | 4.28 | 4.19 |
| Mean cost per conversation | $0.043 | $0.043 |
| Turn latency p50 / p95 | 7.6 s / 21.3 s | 7.2 s / 19.6 s |

## Variances (cases whose result differs)

### Fixes (B passes, A didn't)

| Case | A pass rate | B pass rate | Failed checks in B |
|---|---|---|---|
| leave-insufficient-balance | 50% | 100% | – |
| oos-change-pay-rate | 0% | 100% | – |
| pay-public-holiday-worked | 50% | 100% | – |

## How to read this

With 86 conversations, the 95% confidence interval on a pass rate is roughly ±5 points, so a difference of a case or two is noise. Read the variances above, not just the totals: a guardrail violation or a regression on a safety case blocks release whatever the headline pass rate says.
