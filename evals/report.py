"""Turn per-case results into headline metrics (the PRD's success metrics) and a markdown summary."""

import math
import statistics


def wilson_interval(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a pass rate. With ~40 cases the interval is wide: about +/- 12-15 points."""
    if n == 0:
        return 0.0, 0.0
    p = passes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _rate(items, predicate) -> dict:
    items = list(items)
    hits = sum(1 for r in items if predicate(r))
    return {"rate": hits / len(items) if items else None, "hits": hits, "n": len(items)}


def _percentile(values, pct):
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(pct / 100 * (len(values) - 1))))
    return values[k]


def summarise(results: list[dict]) -> dict:
    ok = [r for r in results if r["status"] == "ok"]
    passes = sum(r["pass"] for r in ok)
    judged = [r for r in ok if r.get("judge")]
    turn_latencies = [ms for r in ok for ms in r["metrics"]["turn_latency_ms"]]
    lo, hi = wilson_interval(passes, len(ok))
    return {
        "cases": len(results),
        "errors": len(results) - len(ok),
        "pass_rate": passes / len(ok) if ok else None,
        "pass_rate_ci95": [lo, hi],
        "deterministic_pass_rate": _rate(ok, lambda r: r["deterministic_pass"])["rate"],
        "judge_pass_rate": _rate(judged, lambda r: r["judge"]["passed"])["rate"] if judged else None,
        "resolution_rate": _rate([r for r in ok if r["outcome"] == "resolved"],
                                 lambda r: r["pass"] and not r["escalated"]),
        "correct_escalation_rate": _rate([r for r in ok if r["expect_escalation"] == "required"],
                                         lambda r: _check_passed(r, "escalation:required")),
        "false_escalation_rate": _rate([r for r in ok if r["expect_escalation"] == "forbidden"],
                                       lambda r: r["escalated"]),
        "guardrail_violations": sum(1 for r in ok for c in r["checks"] if c["kind"] == "safety" and not c["passed"]),
        "mean_accuracy": statistics.mean(r["judge"]["accuracy"] for r in judged) if judged else None,
        "mean_tone": statistics.mean(r["judge"]["tone"] for r in judged) if judged else None,
        "mean_cost_per_conversation_usd": statistics.mean(r["metrics"]["cost_usd"] for r in ok) if ok else None,
        "total_agent_cost_usd": sum(r["metrics"]["cost_usd"] for r in ok),
        "total_judge_cost_usd": sum(r["judge"]["judge_cost_usd"] for r in judged),
        "turn_latency_p50_ms": _percentile(turn_latencies, 50),
        "turn_latency_p95_ms": _percentile(turn_latencies, 95),
        "served_model_mismatches": sum(r["metrics"]["served_model_mismatches"] for r in ok),
    }


def _check_passed(result: dict, name: str) -> bool:
    return any(c["name"] == name and c["passed"] for c in result["checks"])


def failed_checks(result: dict) -> list[str]:
    names = [c["name"] for c in result["checks"] if not c["passed"]]
    if result.get("judge") and not result["judge"]["passed"]:
        names.append(f"judge(acc={result['judge']['accuracy']},tone={result['judge']['tone']},"
                     f"policy={result['judge']['policy_ok']})")
    return names


def fmt_rate(value) -> str:
    if isinstance(value, dict):
        if value["rate"] is None:
            return "n/a"
        return f"{value['rate']:.0%} ({value['hits']}/{value['n']})"
    return "n/a" if value is None else f"{value:.0%}"


def metric_rows(s: dict) -> list[tuple[str, str]]:
    def money(v):
        return "n/a" if v is None else f"${v:.3f}"

    def secs(v):
        return "n/a" if v is None else f"{v / 1000:.1f} s"

    def score(v):
        return "n/a" if v is None else f"{v:.2f}"

    return [
        ("Cases run (errors)", f"{s['cases']} ({s['errors']})"),
        ("Overall pass rate (95% CI)", f"{fmt_rate(s['pass_rate'])} ({s['pass_rate_ci95'][0]:.0%}–"
                                       f"{s['pass_rate_ci95'][1]:.0%})"),
        ("Deterministic checks pass rate", fmt_rate(s["deterministic_pass_rate"])),
        ("Judge pass rate", fmt_rate(s["judge_pass_rate"])),
        ("Resolution rate", fmt_rate(s["resolution_rate"])),
        ("Correct-escalation rate", fmt_rate(s["correct_escalation_rate"])),
        ("False-escalation rate", fmt_rate(s["false_escalation_rate"])),
        ("Guardrail violations", str(s["guardrail_violations"])),
        ("Mean accuracy (1–5)", score(s["mean_accuracy"])),
        ("Mean tone (1–5)", score(s["mean_tone"])),
        ("Mean cost per conversation", money(s["mean_cost_per_conversation_usd"])),
        ("Turn latency p50 / p95", f"{secs(s['turn_latency_p50_ms'])} / {secs(s['turn_latency_p95_ms'])}"),
    ]


def to_markdown(run: dict) -> str:
    s = run["summary"]
    lines = [f"# Eval run `{run['run_id']}`", "",
             f"Agent **{run['agent']['name']}** (`{run['agent']['model']}`, effort `{run['agent']['effort']}`, "
             f"prompt `{run['agent']['system_prompt_file']}`) · judge `{run['judge_model'] or 'off'}` · "
             f"git `{run['git_sha']}` · {run['started_at']}", "",
             "| Metric | Value |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in metric_rows(s)]
    lines += ["", f"Agent cost ${s['total_agent_cost_usd']:.2f}, judge cost ${s['total_judge_cost_usd']:.2f}.", "",
              "| Case | Result | Failed checks | Acc | Tone | Cost |", "|---|---|---|---|---|---|"]
    for r in run["results"]:
        if r["status"] != "ok":
            lines.append(f"| {r['case_id']} | ERROR | {r['error']} | | | |")
            continue
        j = r.get("judge") or {}
        lines.append(f"| {r['case_id']} | {'pass' if r['pass'] else '**FAIL**'} | "
                     f"{', '.join(failed_checks(r)) or '–'} | {j.get('accuracy', '')} | {j.get('tone', '')} | "
                     f"${r['metrics']['cost_usd']:.3f} |")
    return "\n".join(lines) + "\n"
