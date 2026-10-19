"""Re-score an existing eval run with the current judge, without re-running the agent.

    python -m evals.rejudge evals/results/baseline-v1 --run-id baseline-v1-rejudged

Two uses:
  - Fair comparisons. Scores from before and after a judge change aren't comparable, so when the judge changes,
    re-judge the older run before comparing it with a newer one.
  - Judge consistency. Re-judge the same run twice and see how often the verdicts agree. Disagreements are
    the judge's own noise, on top of the agent's.
The judge reads the saved (redacted) traces: the same user turns, tool results and replies the agent produced.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from rich.console import Console

from evals import judge
from evals.cases import load_cases
from evals.report import summarise, to_markdown
from evals.run import RESULTS_DIR

console = Console()


def turns_from_trace(path: Path) -> list[dict]:
    turns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["type"] == "user_message":
            turns.append({"user": event["text"], "assistant": "", "tools": []})
        elif event["type"] == "tool_call":
            turns[-1]["tools"].append({"name": event["name"], "input": event["input"], "result": event["result"]})
        elif event["type"] == "assistant_reply":
            turns[-1]["assistant"] = event["text"]
    return turns


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-judge an eval run from its traces")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--judge-model", default=judge.DEFAULT_JUDGE_MODEL)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    run = json.loads((args.run_dir / "results.json").read_text(encoding="utf-8"))
    cases = {c.id: c for c in load_cases()}
    client = anthropic.Anthropic(max_retries=5, timeout=180)

    def rescore(result: dict) -> dict:
        case = cases.get(result["case_id"])
        if result["status"] != "ok" or case is None or not case.reference:
            return result
        turns = turns_from_trace(args.run_dir / result["trace_file"])
        scores = judge.judge(client, args.judge_model, case.title, case.reference, turns)
        previous = result.get("judge") or {}
        return {**result, "judge": scores, "previous_judge_passed": previous.get("passed"),
                "pass": result["deterministic_pass"] and scores["passed"],
                "trace_file": str(Path("..") / args.run_dir.name / result["trace_file"])}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(rescore, run["results"]))

    compared = [r for r in results if r.get("previous_judge_passed") is not None]
    agree = sum(r["judge"]["passed"] == r["previous_judge_passed"] for r in compared)
    new_run = {**run, "run_id": args.run_id, "judge_model": args.judge_model, "results": results,
               "rejudged_from": run["run_id"], "summary": summarise(results),
               "judge_agreement_with_previous": {"agree": agree, "n": len(compared)}}
    out = RESULTS_DIR / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(new_run, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(to_markdown(new_run), encoding="utf-8")

    console.print(f"judge verdicts agree with the previous judging on {agree}/{len(compared)} conversations")
    for r in compared:
        if r["judge"]["passed"] != r["previous_judge_passed"]:
            console.print(f"  changed: {r['case_id']} r{r['rep']}: {r['previous_judge_passed']} -> "
                          f"{r['judge']['passed']} (acc {r['judge']['accuracy']}, tone {r['judge']['tone']}, "
                          f"policy {r['judge']['policy_ok']})")
    console.print(f"pass rate {new_run['summary']['pass_rate']:.0%} | results: {out}")


if __name__ == "__main__":
    main()
