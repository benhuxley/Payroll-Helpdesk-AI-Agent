"""Parallel run for agents: compare two eval runs case by case, like reconciling a payroll parallel run.

    python -m evals.compare evals/results/<run A>/results.json evals/results/<run B>/results.json \
        --out docs/comparison.md

In a payroll parallel run you run the old and new systems on the same inputs and reconcile every
difference before go-live. Here, A is the current agent version and B is the candidate. Same cases, same
synthetic data, same checks. The report lists each variance (a regression or a fix) with the failing checks,
then the headline metrics side by side, with cost and latency.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from evals.report import failed_checks, metric_rows, summarise


def _by_case(run: dict) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for r in run["results"]:
        grouped[r["case_id"]].append(r)
    return grouped


def _case_pass_rate(results: list[dict]) -> float | None:
    ok = [r for r in results if r["status"] == "ok"]
    return sum(r["pass"] for r in ok) / len(ok) if ok else None


def _label(run: dict) -> str:
    a = run["agent"]
    return f"{a['name']} ({a['model']}, effort {a['effort']}, {a['system_prompt_file']})"


def compare(run_a: dict, run_b: dict) -> str:
    a_cases, b_cases = _by_case(run_a), _by_case(run_b)
    sa, sb = summarise(run_a["results"]), summarise(run_b["results"])

    regressions, fixes, flaky, both_fail = [], [], [], []
    for case_id in sorted(set(a_cases) | set(b_cases)):
        pa, pb = _case_pass_rate(a_cases.get(case_id, [])), _case_pass_rate(b_cases.get(case_id, []))
        if pa is None or pb is None:
            continue
        if pa == 1 and pb < 1:
            regressions.append((case_id, pa, pb))
        elif pa < 1 and pb == 1:
            fixes.append((case_id, pa, pb))
        elif pa < 1 and pb < 1:
            (both_fail if pa == 0 and pb == 0 else flaky).append((case_id, pa, pb))

    lines = [
        "# Parallel run: agent version comparison", "",
        f"- **A (current):** {_label(run_a)} · run `{run_a['run_id']}` · {run_a.get('reps', 1)} rep(s)",
        f"- **B (candidate):** {_label(run_b)} · run `{run_b['run_id']}` · {run_b.get('reps', 1)} rep(s)",
        "- Same cases, same synthetic data, same deterministic checks and judge.", "",
        "## Headline metrics", "", "| Metric | A | B |", "|---|---|---|",
    ]
    for (name, va), (_, vb) in zip(metric_rows(sa), metric_rows(sb), strict=True):
        lines.append(f"| {name} | {va} | {vb} |")

    lines += ["", "## Variances (cases whose result differs)", ""]
    if not (regressions or fixes or flaky):
        lines.append("None: both versions produced the same result on every case.")
    for title, rows in [("Regressions (A passed, B didn't)", regressions), ("Fixes (B passes, A didn't)", fixes),
                        ("Unstable in at least one version", flaky)]:
        if not rows:
            continue
        lines += [f"### {title}", "", "| Case | A pass rate | B pass rate | Failed checks in B |", "|---|---|---|---|"]
        for case_id, pa, pb in rows:
            b_fails = sorted({f for r in b_cases[case_id] if r["status"] == "ok" for f in failed_checks(r)})
            lines.append(f"| {case_id} | {pa:.0%} | {pb:.0%} | {', '.join(b_fails) or '–'} |")
        lines.append("")
    if both_fail:
        lines += ["### Failing in both", "", ", ".join(c for c, _, _ in both_fail), ""]

    n = sa["cases"]
    lines += ["## How to read this", "",
              f"With {n} conversations, the 95% confidence interval on a pass rate is roughly ±"
              f"{100 * (sa['pass_rate_ci95'][1] - sa['pass_rate_ci95'][0]) / 2:.0f} points, so a difference of a "
              "case or two is noise. Read the variances above, not just the totals: a guardrail violation or a "
              "regression on a safety case blocks release whatever the headline pass rate says.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_a", type=Path)
    parser.add_argument("run_b", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = compare(json.loads(args.run_a.read_text(encoding="utf-8")),
                     json.loads(args.run_b.read_text(encoding="utf-8")))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
