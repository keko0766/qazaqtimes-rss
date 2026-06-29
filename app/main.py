from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.collectors.gdelt_collector import collect_gdelt
from app.collectors.gdelt_collector import (
    DEFAULT_DELAY_SECONDS,
    DEFAULT_MAX_RECORDS,
    DEFAULT_RETRY_DELAY_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from app.collectors.rss_collector import collect_rss_sources
from app.db import fetch_recent_news, get_connection, get_existing_titles, init_db, insert_news
from app.services.classifier import classify_items
from app.services.deduplicate import deduplicate_items
from app.services.relevance import filter_relevant_items
from app.services.report_generator import generate_report
from app.utils.datetime import get_app_timezone, now_local


RUN_MODES = {
    "fast": {"gdelt_enabled": False, "maxrecords": 0, "delay_seconds": 0},
    "normal": {"gdelt_enabled": True, "maxrecords": 20, "delay_seconds": 15},
}


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Collect geopolitical news and generate a Markdown digest.")
    parser.add_argument("command", choices=["collect", "report", "all"], help="What to run")
    parser.add_argument(
        "--mode",
        choices=RUN_MODES.keys(),
        default="fast",
        help="Run mode: fast = RSS only, normal = RSS + GDELT",
    )
    args = parser.parse_args()

    settings = load_settings()
    settings["mode"] = args.mode
    log_timezone()
    print(f"[main] run mode: {args.mode}")

    if args.command in {"collect", "all"}:
        collect(settings)
    if args.command in {"report", "all"}:
        report(settings)
    return 0


def log_timezone() -> None:
    timezone = get_app_timezone()
    timezone_name = getattr(timezone, "key", str(timezone))
    print(f"[main] timezone: {timezone_name}; local time: {now_local().isoformat(timespec='seconds')}")


def load_settings() -> dict:
    return {
        "db_path": os.getenv("DATABASE_PATH", "data/news.sqlite3"),
        "sources_path": os.getenv("SOURCES_PATH", "sources.json"),
        "output_dir": os.getenv("OUTPUT_DIR", "output"),
        "timeout": int(os.getenv("REQUEST_TIMEOUT", "20")),
        "max_rss_items": int(os.getenv("MAX_RSS_ITEMS_PER_SOURCE", "30")),
    }


def load_sources(path: str | Path) -> dict:
    source_path = Path(path)
    if not source_path.exists():
        print(f"[sources] missing {source_path}; using empty source list")
        return {"rss_sources": [], "gdelt": {"enabled": False, "queries": []}}

    try:
        return json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[sources] cannot parse {source_path}: {exc}")
        return {"rss_sources": [], "gdelt": {"enabled": False, "queries": []}}


def collect(settings: dict) -> None:
    print("[main] preparing database")
    init_db(settings["db_path"])
    sources = load_sources(settings["sources_path"])

    rss_sources = sources.get("rss_sources", [])
    gdelt_config = sources.get("gdelt", {})
    gdelt_config = apply_run_mode(gdelt_config, settings["mode"])

    print("[main] collecting RSS")
    rss_items = collect_rss_sources(
        rss_sources,
        timeout=settings["timeout"],
        max_items=settings["max_rss_items"],
    )

    gdelt_items = []
    if gdelt_config.get("enabled", True):
        print(
            "[main] collecting GDELT "
            f"(maxrecords={gdelt_config['maxrecords']}, delay={gdelt_config['delay_seconds']}s)"
        )
        gdelt_items = collect_gdelt(
            gdelt_config.get("queries", []),
            timeout=int(gdelt_config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
            max_records=int(gdelt_config.get("maxrecords", DEFAULT_MAX_RECORDS)),
            delay_seconds=float(gdelt_config.get("delay_seconds", DEFAULT_DELAY_SECONDS)),
            retry_delay_seconds=float(
                gdelt_config.get("retry_delay_seconds", DEFAULT_RETRY_DELAY_SECONDS)
            ),
        )
    else:
        print("[main] skipping GDELT for this run mode")

    raw_items = rss_items + gdelt_items
    print(f"[main] collected raw items: {len(raw_items)}")

    with get_connection(settings["db_path"]) as conn:
        existing_titles = get_existing_titles(conn)
        unique_items = deduplicate_items(raw_items, existing_titles=existing_titles)
        classified_items = classify_items(unique_items)
        relevant_items = filter_relevant_items(classified_items)
        inserted = insert_news(conn, relevant_items)

    print(f"[main] unique candidates: {len(unique_items)}")
    print(f"[main] relevant candidates: {len(relevant_items)}")
    print(f"[main] inserted new records: {inserted}")


def apply_run_mode(gdelt_config: dict, mode: str) -> dict:
    config = dict(gdelt_config)
    mode_config = RUN_MODES[mode]
    config["enabled"] = bool(config.get("enabled", True)) and mode_config["gdelt_enabled"]
    config["maxrecords"] = mode_config["maxrecords"] or DEFAULT_MAX_RECORDS
    config["delay_seconds"] = mode_config["delay_seconds"]
    config.setdefault("retry_delay_seconds", DEFAULT_RETRY_DELAY_SECONDS)
    config.setdefault("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    return config


def report(settings: dict) -> None:
    print("[main] generating report")
    init_db(settings["db_path"])
    with get_connection(settings["db_path"]) as conn:
        items = fetch_recent_news(conn)
    classified_items = classify_items(items)
    relevant_items = filter_relevant_items(classified_items)
    generate_report(relevant_items, settings["output_dir"])


if __name__ == "__main__":
    raise SystemExit(main())
