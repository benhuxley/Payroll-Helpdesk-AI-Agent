"""One command to run the whole demo locally:

    helpdesk-demo            (or: python -m helpdesk.web.demo)

1. Rebuilds the synthetic database (a fresh world every time).
2. Starts the mock WFM + Zendesk API on http://127.0.0.1:8001 in a background thread.
3. Starts the chat UI on http://127.0.0.1:8000.
"""

import threading
import time

import uvicorn

from helpdesk import config
from helpdesk.web.app import create_web_app
from helpdesk.wfm_api.app import create_app
from helpdesk.wfm_api.db import build_database

WFM_PORT = 8001
WEB_PORT = 8000


def main() -> None:
    build_database(config.WFM_DB_PATH)
    wfm_server = uvicorn.Server(uvicorn.Config(create_app(config.WFM_DB_PATH), host="127.0.0.1", port=WFM_PORT,
                                               log_level="warning"))
    threading.Thread(target=wfm_server.run, daemon=True).start()
    while not wfm_server.started:
        time.sleep(0.05)
    print(f"Mock WFM + Zendesk API: http://127.0.0.1:{WFM_PORT}/docs")
    print(f"Chat UI:                http://127.0.0.1:{WEB_PORT}")
    print(f"Ticketing backend:      {config.TICKETING_BACKEND}")
    uvicorn.run(create_web_app(), host="127.0.0.1", port=WEB_PORT, log_level="warning")


if __name__ == "__main__":
    main()
