from __future__ import annotations

import json
import logging
import signal
import threading
import time
import webbrowser
from datetime import datetime, timezone

from dotenv import load_dotenv

from app import web
from app.services.ollama_manager import ensure_ollama_ready, stop_managed_ollama
from app.utils.paths import (
    configure_environment_defaults,
    configure_logging,
    ensure_app_paths,
    ollama_status_path,
)


LOGGER = logging.getLogger(__name__)


def main() -> int:
    load_dotenv()
    ensure_app_paths()
    configure_environment_defaults()
    configure_logging()

    stop_event = threading.Event()
    server, port = web.create_server("127.0.0.1", 8000)
    url = f"http://127.0.0.1:{port}"

    server_thread = threading.Thread(target=server.serve_forever, name="GeoNewsBotGUI", daemon=True)
    server_thread.start()
    LOGGER.info("GeoNewsBot GUI started at %s", url)
    webbrowser.open(url, new=1)

    ollama_thread = threading.Thread(
        target=run_ollama_setup,
        name="GeoNewsBotOllamaSetup",
        daemon=True,
    )
    ollama_thread.start()

    def shutdown(_signum: int | None = None, _frame: object | None = None) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while not stop_event.wait(0.5):
            if not server_thread.is_alive():
                LOGGER.error("GUI server stopped unexpectedly")
                return 1
    finally:
        LOGGER.info("GeoNewsBot shutting down")
        server.shutdown()
        server.server_close()
        stop_managed_ollama()
    return 0


def run_ollama_setup() -> None:
    try:
        ensure_ollama_ready(write_ollama_status)
    except Exception:  # noqa: BLE001 - desktop startup must keep the GUI alive.
        LOGGER.exception("Ollama setup failed")
        write_ollama_status(
            {
                "state": "error",
                "percent": 0,
                "text": "Ollama дайындалмады",
                "model": "",
                "error": "ollama_setup_failed",
            }
        )


def write_ollama_status(payload: dict) -> None:
    status_path = ollama_status_path()
    status_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "state": payload.get("state", ""),
        "percent": int(payload.get("percent") or 0),
        "text": payload.get("text") or payload.get("message") or "",
        "message": payload.get("message") or payload.get("text") or "",
        "model": payload.get("model") or "",
        "error": payload.get("error") or "",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_at_epoch": time.time(),
    }
    status_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
