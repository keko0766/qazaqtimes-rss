from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


APP_NAME = "GeoNewsBot"


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    if is_packaged():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return project_root()


def app_support_root() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def data_dir() -> Path:
    if is_packaged():
        return app_support_root() / "data"
    return project_root() / "data"


def output_dir() -> Path:
    if is_packaged():
        return app_support_root() / "output"
    return project_root() / "output"


def runtime_dir() -> Path:
    if is_packaged():
        return app_support_root() / "runtime"
    return project_root() / "data"


def database_path() -> Path:
    return data_dir() / "news.sqlite3"


def sources_path() -> Path:
    env_path = os.getenv("SOURCES_PATH")
    if env_path:
        return Path(env_path)
    return resource_root() / "sources.json"


def ollama_status_path() -> Path:
    return runtime_dir() / "ollama_status.json"


def ai_status_path() -> Path:
    return data_dir() / "ai_status.json"


def log_path() -> Path:
    return runtime_dir() / "app.log"


def ensure_app_paths() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    output_dir().mkdir(parents=True, exist_ok=True)
    runtime_dir().mkdir(parents=True, exist_ok=True)


def configure_environment_defaults() -> None:
    ensure_app_paths()
    os.environ.setdefault("DATABASE_PATH", str(database_path()))
    os.environ.setdefault("DATA_DIR", str(data_dir()))
    os.environ.setdefault("SOURCES_PATH", str(sources_path()))
    os.environ.setdefault("OUTPUT_DIR", str(output_dir()))
    os.environ.setdefault("AI_PROVIDER", "ollama")
    os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("OLLAMA_MODEL", "gpt-oss:20b")
    os.environ.setdefault("APP_TIMEZONE", "Asia/Almaty")
    if os.environ.get("OLLAMA_URL", "").rstrip("/") == "http://ollama:11434":
        os.environ["OLLAMA_URL"] = "http://127.0.0.1:11434"


def configure_logging() -> None:
    ensure_app_paths()
    logging.basicConfig(
        filename=str(log_path()),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
