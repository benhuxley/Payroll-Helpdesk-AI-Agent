"""Run the eval suite against one agent version.

    python -m evals.run --config configs/agent_v1.yaml                # all cases, with the LLM judge
    python -m evals.run --tags smoke --fail-on-safety --min-pass-rate 0.75   # the CI subset
    python -m evals.run --cases pay-sunday-penalty,pay-missed-punch --no-judge

Each case runs in a clean, isolated world: its own copy of the synthetic database, its own agent.
Output in evals/results/<run_id>/: results.json, summary.md, errors.jsonl, traces/*.jsonl
Infrastructure errors (API outages, timeouts) go to errors.jsonl and are NOT scored as agent failures.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic
from rich.console import Console

from evals import checks, judge
from evals.cases import load_cases
from evals.pricing import cost_usd
from evals.report import failed_checks, summarise, to_markdown
from helpdesk import runtime
from helpdesk.agent.loop import HelpdeskAgent
from helpdesk.agent.settings import load_settings
from helpdesk.wfm_api import seed_data
from helpdesk.wfm_api.db import build_database

RESULTS_DIR = Path(__file__).parent / "results"
console = Console()

DIRECTORY = [{"employee_id": e["employee_id"], "first_name": e["first_name"], "last_name": e["last_name"],
              "manager_id": e["manager_id"]} for e in seed_data.EMPLOYEES]
DOBS = {e["employee_id"]: e["date_of_birth"] for e in seed_data.EMPLOYEES}
POSTCODES = {e["employee_id"]: e["postcode"] for e in seed_data.EMPLOYEES}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_case(case, rep, settings, pristine_db: Path, run_dir: Path, llm, judge_client, judge_model) -> dict:
    conversation_id = f"{case.id}-r{rep}"
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "wfm.db"
        shutil.copy(pristine_db, db_path)  # clean state for every case
        wfm, tickets = runtime.in_process(db_path)
        agent = HelpdeskAgent(settings, wfm, tickets, llm=llm, traces_dir=run_dir / "traces",
                              conversation_id=conversation_id)
        turn_latency = []
        try:
            for user_text in case.turns:
                started = time.perf_counter()
                agent.send(user_text)
                turn_latency.append(int((time.perf_counter() - started) * 1000))
        except (anthropic.APIError, anthropic.APIConnectionError) as exc:
            return {"case_id": case.id, "rep": rep, "status": "error", "error_class": "api",
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        finally:
            agent.close()

        results = checks.behaviour_checks(case, agent, db_path)
        results += checks.safety_checks(case, agent, DIRECTORY, DOBS, POSTCODES)

    model_calls = [e for e in agent.tracer.events if e["type"] == "model_call"]
    usage_totals = {k: sum(e["usage"][k] for e in model_calls) for k in
                    ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    replies = [e["text"] for e in agent.tracer.events if e["type"] == "assistant_reply"]  # redacted copies
    transcript = [{"user": agent.redactor.text(t.user_text), "assistant": reply,
                   "tools": [c.name for c in t.tool_calls]} for t, reply in zip(agent.turns, replies, strict=True)]

    behaviour_pass = all(c.passed for c in results if c.kind == "behaviour")
    safety_pass = all(c.passed for c in results if c.kind == "safety")
    judge_scores = None
    if judge_client is not None and case.reference:
        try:
            raw_turns = [{"user": t.user_text, "assistant": t.reply, "tools": [c.name for c in t.tool_calls]}
                         for t in agent.turns]
            judge_scores = judge.judge(judge_client, judge_model, case.title, case.reference, raw_turns)
        except (anthropic.APIError, RuntimeError) as exc:
            return {"case_id": case.id, "rep": rep, "status": "error", "error_class": "judge",
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    deterministic_pass = behaviour_pass and safety_pass
    return {
        "case_id": case.id, "rep": rep, "title": case.title, "tags": case.tags, "outcome": case.outcome,
        "status": "ok", "expect_escalation": case.expect.get("escalation", "optional"),
        "checks": [c.to_dict() for c in results],
        "behaviour_pass": behaviour_pass, "safety_pass": safety_pass, "deterministic_pass": deterministic_pass,
        "judge": judge_scores,
        "pass": deterministic_pass and (judge_scores is None or judge_scores["passed"]),
        "escalated": agent.state.escalation_ticket_id is not None,
        "escalation_reason": agent.state.escalation_reason,
        "ticket_ids": agent.state.ticket_ids,
        "metrics": {
            "model_calls": len(model_calls),
            "tool_calls": sum(len(t.tool_calls) for t in agent.turns),
            **usage_totals,
            "cost_usd": round(sum(cost_usd(e["model_served"], e["usage"]) for e in model_calls), 5),
            "turn_latency_ms": turn_latency,
            "served_models": sorted({e["model_served"] for e in model_calls}),
            "served_model_mismatches": sum(1 for e in model_calls if e["model_served"] != e["model_requested"]),
        },
        "transcript": transcript,
        "trace_file": f"traces/{conversation_id}.jsonl",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the helpdesk agent eval suite")
    parser.add_argument("--config", default="configs/agent_v1.yaml")
    parser.add_argument("--tags", help="comma-separated tags, e.g. smoke")
    parser.add_argument("--cases", help="comma-separated case ids")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--judge-model", default=judge.DEFAULT_JUDGE_MODEL)
    parser.add_argument("--run-id")
    parser.add_argument("--fail-on-safety", action="store_true", help="exit 1 on any guardrail violation")
    parser.add_argument("--min-pass-rate", type=float, help="exit 1 if the overall pass rate is below this")
    args = parser.parse_args()

    settings = load_settings(args.config)
    cases = load_cases(tags=args.tags.split(",") if args.tags else None,
                       ids=args.cases.split(",") if args.cases else None)
    if not cases:
        console.print("[red]No cases matched.[/red]")
        return 1

    run_id = args.run_id or f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{settings.name}"
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pristine_db = build_database(run_dir / "pristine.db")

    llm = anthropic.Anthropic(max_retries=5, timeout=180)
    judge_client = None if args.no_judge else llm
    judge_model = None if args.no_judge else args.judge_model
    console.print(f"Running {len(cases)} cases x {args.reps} rep(s) with [bold]{settings.name}[/bold] "
                  f"({settings.model}, effort {settings.effort}); judge: {judge_model or 'off'}")

    started_at = datetime.now().isoformat(timespec="seconds")
    results = []
    jobs = [(case, rep) for case in cases for rep in range(1, args.reps + 1)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_case, case, rep, settings, pristine_db, run_dir, llm, judge_client,
                               judge_model): (case, rep) for case, rep in jobs}
        for future in as_completed(futures):
            case, rep = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # a harness bug: record it, don't score it
                result = {"case_id": case.id, "rep": rep, "status": "error", "error_class": "harness",
                          "error": f"{type(exc).__name__}: {exc}"}
            results.append(result)
            if result["status"] != "ok":
                console.print(f"  [yellow]ERROR[/yellow] {case.id}: {result['error']}")
            else:
                mark = "[green]pass[/green]" if result["pass"] else "[red]FAIL[/red]"
                fails = ", ".join(failed_checks(result))
                console.print(f"  {mark} {case.id}  {fails}")

    order = {(c.id, rep): i for i, (c, rep) in enumerate(jobs)}
    results.sort(key=lambda r: order[(r["case_id"], r["rep"])])
    errors = [r for r in results if r["status"] != "ok"]
    with (run_dir / "errors.jsonl").open("w", encoding="utf-8") as f:
        for r in errors:
            f.write(json.dumps(r) + "\n")

    run = {"run_id": run_id, "started_at": started_at, "git_sha": git_sha(), "agent": vars(settings),
           "judge_model": judge_model, "reps": args.reps, "results": results, "summary": summarise(results)}
    (run_dir / "results.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(to_markdown(run), encoding="utf-8")
    (run_dir / "pristine.db").unlink(missing_ok=True)

    s = run["summary"]
    console.print(f"\n[bold]pass rate {s['pass_rate']:.0%}[/bold] | guardrail violations "
                  f"{s['guardrail_violations']} | cost ${s['total_agent_cost_usd']:.2f} agent + "
                  f"${s['total_judge_cost_usd']:.2f} judge | results: {run_dir}")

    if args.fail_on_safety and s["guardrail_violations"] > 0:
        return 1
    if args.min_pass_rate is not None and (s["pass_rate"] or 0) < args.min_pass_rate:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
