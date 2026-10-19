"""Pretty-print a conversation trace for debugging.

    python scripts/show_trace.py traces/conv-abc123.jsonl
    python scripts/show_trace.py evals/results/<run>/traces/pay-sunday-penalty-r1.jsonl --full

Shows, turn by turn: the user message, guardrail decisions, each model call (latency, tokens, stop reason,
a short reasoning summary), each tool call (arguments, result, which policy allowed or blocked it) and the
reply. Ends with totals. Use --full to print complete tool results and reasoning.
"""

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

ACTION_STYLE = {"allow": "green", "flag": "yellow", "hold": "yellow", "block": "red", "replace": "red",
                "escalate": "magenta"}


def short(value, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--full", action="store_true", help="don't truncate tool results and reasoning")
    args = parser.parse_args()

    events = [json.loads(line) for line in args.trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    console = Console()
    limit = 100_000 if args.full else 220
    totals = {"model_calls": 0, "latency_ms": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
              "tool_calls": 0, "blocked": 0}

    for e in events:
        kind = e["type"]
        if kind == "conversation_start":
            console.print(Panel(f"{e['conversation_id']}  ·  agent {e['agent_version']} ({e['model']}, effort "
                                f"{e['effort']})  ·  prompt {e['system_prompt_file']}  ·  ticketing "
                                f"{e['ticketing_backend']}", title="conversation", style="bold"))
        elif kind == "user_message":
            console.rule(f"turn {e['turn']}")
            console.print(f"[bold cyan]USER[/bold cyan] {e['text']}")
        elif kind == "guardrail":
            style = ACTION_STYLE.get(e["action"], "white")
            detail = f" – {e['detail']}" if e.get("detail") else ""
            console.print(f"  [{style}]guardrail {e['layer']}.{e['rule']} → {e['action']}[/{style}]{detail}")
        elif kind == "model_call":
            u = e["usage"]
            totals["model_calls"] += 1
            totals["latency_ms"] += e["latency_ms"]
            totals["input"] += u["input_tokens"]
            totals["output"] += u["output_tokens"]
            totals["cache_read"] += u["cache_read_input_tokens"]
            totals["cache_write"] += u["cache_creation_input_tokens"]
            served = "" if e["model_served"] == e["model_requested"] else f" [red]served by {e['model_served']}[/red]"
            console.print(f"  [dim]model step {e['step']}: {e['latency_ms']} ms, in {u['input_tokens']} + cache "
                          f"{u['cache_read_input_tokens']} read / {u['cache_creation_input_tokens']} write, out "
                          f"{u['output_tokens']}, stop={e['stop_reason']}{served}[/dim]")
            for thought in e.get("thinking") or []:
                console.print(f"    [italic dim]reasoning: {short(thought, limit)}[/italic dim]")
        elif kind == "tool_call":
            totals["tool_calls"] += 1
            if not e["executed"]:
                totals["blocked"] += 1
            status = "[green]ok[/green]" if not e["is_error"] else "[red]error[/red]"
            console.print(f"  [bold]tool[/bold] {e['name']}({short(e['input'], 160)}) → {status} "
                          f"[dim]{e['latency_ms']} ms[/dim]")
            for d in e.get("decisions", []):
                style = ACTION_STYLE.get(d["action"], "white")
                console.print(f"    [{style}]{d['layer']}.{d['rule']} → {d['action']}[/{style}]")
            console.print(f"    [dim]{short(e['result'], limit)}[/dim]")
        elif kind == "escalation_backstop":
            console.print(f"  [magenta]backstop escalation: {e['reason']} → ticket #{e['ticket_id']}[/magenta]")
        elif kind == "assistant_reply":
            flag = " [red](replaced by output check)[/red]" if e.get("replaced_by_output_check") else ""
            console.print(f"[bold green]AGENT[/bold green]{flag} {e['text']}")
        elif kind == "error":
            console.print(f"  [red]error: {e}[/red]")
        elif kind == "conversation_end":
            console.rule("end")
            console.print(f"verified={e['verified']}  escalation={e['escalation_reason']} "
                          f"(ticket {e['escalation_ticket_id']})  tickets={e['ticket_ids']}  "
                          f"leave submitted={e['leave_requests_submitted']}")

    table = Table(title="totals", show_header=False)
    for key, value in totals.items():
        table.add_row(key, str(value))
    console.print(table)


if __name__ == "__main__":
    sys.exit(main())
