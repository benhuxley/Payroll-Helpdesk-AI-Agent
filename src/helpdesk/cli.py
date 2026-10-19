"""Chat with the agent in the terminal.

    python -m helpdesk.cli                 # in-process mock WFM, fresh synthetic data each run
    python -m helpdesk.cli --remote        # talk to a running mock WFM server (WFM_BASE_URL)
    python -m helpdesk.cli --config configs/candidate_sonnet.yaml

Type /quit to exit. The trace path is printed at the start, so you can inspect it with scripts/show_trace.py.
"""

import argparse

from rich.console import Console

from helpdesk import config, runtime
from helpdesk.agent.loop import HelpdeskAgent
from helpdesk.agent.settings import load_settings
from helpdesk.wfm_api.db import build_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Payroll helpdesk agent (CLI)")
    parser.add_argument("--config", default=config.AGENT_CONFIG, help="agent version YAML")
    parser.add_argument("--remote", action="store_true", help="use the WFM server at WFM_BASE_URL")
    args = parser.parse_args()

    settings = load_settings(args.config)
    if args.remote:
        wfm, tickets = runtime.remote()
    else:
        wfm, tickets = runtime.in_process(build_database(config.WFM_DB_PATH), config.TICKETING_BACKEND)

    agent = HelpdeskAgent(settings, wfm, tickets)
    console = Console()
    console.print(f"[bold]Kestrel Bay Health payroll helpdesk[/bold] ({settings.name}, synthetic data)")
    console.print(f"[dim]trace: {agent.tracer.path} | ticketing: {tickets.backend} | /quit to exit[/dim]\n")
    try:
        while True:
            text = console.input("[bold cyan]you>[/bold cyan] ").strip()
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                break
            with console.status("thinking..."):
                reply = agent.send(text)
            console.print(f"[bold green]agent>[/bold green] {reply}\n")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        agent.close()
        console.print(f"[dim]trace saved: {agent.tracer.path}[/dim]")


if __name__ == "__main__":
    main()
