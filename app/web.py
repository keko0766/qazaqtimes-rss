from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output"
COMMANDS = {"collect", "report", "article", "all"}
MODES = {"fast", "normal"}


class JobState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.command = ""
        self.mode = ""
        self.started_at = ""
        self.finished_at = ""
        self.returncode: int | None = None
        self.output: list[str] = []
        self.process: subprocess.Popen[str] | None = None
        self.stop_requested = False

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "command": self.command,
                "mode": self.mode,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "returncode": self.returncode,
                "stopped": self.stop_requested and self.returncode not in (None, 0),
                "output": self.output[-200:],
                "latest_digest": str(latest_digest_path().name) if latest_digest_path() else "",
                "latest_article": latest_article_label(),
            }

    def start(self, command: str, mode: str, use_ollama: bool) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.command = command
            self.mode = mode
            self.started_at = now_iso()
            self.finished_at = ""
            self.returncode = None
            self.output = []
            self.process = None
            self.stop_requested = False
        thread = threading.Thread(
            target=self._run,
            args=(command, mode, use_ollama),
            daemon=True,
        )
        thread.start()
        return True

    def _run(self, command: str, mode: str, use_ollama: bool) -> None:
        cmd = [sys.executable, "app/main.py", command, "--mode", mode]
        env = None
        if use_ollama:
            env = {"USE_OLLAMA": "true"}
        try:
            process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                env=None if env is None else {**dict_env(), **env},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            with self.lock:
                self.process = process
            assert process.stdout is not None
            for line in process.stdout:
                self.append(line.rstrip())
            returncode = process.wait()
        except Exception as exc:  # noqa: BLE001 - GUI must never crash the app process.
            self.append(f"[gui] команданы іске қосу сәтсіз: {exc}")
            returncode = 1

        with self.lock:
            self.running = False
            self.returncode = returncode
            self.finished_at = now_iso()
            self.process = None

    def stop(self) -> bool:
        with self.lock:
            if not self.running or self.process is None:
                return False
            process = self.process
            self.stop_requested = True
            self.output.append("[gui] тоқтату сұралды")

        process.terminate()
        threading.Timer(5, self._kill_if_running, args=(process,)).start()
        return True

    def _kill_if_running(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            self.append("[gui] процесс уақытында тоқтамады; мәжбүрлеп тоқтатылады")
            process.kill()

    def append(self, line: str) -> None:
        with self.lock:
            self.output.append(line)


JOB = JobState()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_html(INDEX_HTML)
            return
        if path == "/api/status":
            self.send_json(JOB.snapshot())
            return
        if path == "/api/digest":
            digest = latest_digest_path()
            self.send_json(
                {
                    "name": digest.name if digest else "",
                    "content": digest.read_text(encoding="utf-8") if digest else "",
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/stop":
            if not JOB.stop():
                self.send_json({"ok": False, "error": "Іске қосылған тапсырма жоқ"}, status=409)
                return
            self.send_json({"ok": True})
            return

        if path != "/api/run":
            self.send_error(404)
            return

        payload = self.read_json()
        command = str(payload.get("command", "all"))
        mode = str(payload.get("mode", "fast"))
        use_ollama = bool(payload.get("use_ollama", False))
        if command not in COMMANDS or mode not in MODES:
            self.send_json({"ok": False, "error": "Команда немесе режим қате"}, status=400)
            return
        if not JOB.start(command, mode, use_ollama):
            self.send_json({"ok": False, "error": "Тапсырма қазір орындалып жатыр"}, status=409)
            return
        self.send_json({"ok": True})

    def read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"[gui] {self.address_string()} {format % args}")


def dict_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def latest_digest_path() -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    digests = sorted(OUTPUT_DIR.glob("digest_*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return digests[0] if digests else None


def latest_article_path() -> Path | None:
    article_dir = OUTPUT_DIR / "articles"
    if not article_dir.exists():
        return None
    articles = sorted(article_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return articles[0] if articles else None


def latest_article_label() -> str:
    article = latest_article_path()
    if not article:
        return ""
    return str(article.relative_to(PROJECT_ROOT))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


INDEX_HTML = r"""<!doctype html>
<html lang="kk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>geo-news-bot</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #126b5f;
      --accent-2: #284b8f;
      --danger: #a43f3f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 18px; letter-spacing: 0; }
    main {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      min-height: calc(100vh - 58px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 16px;
    }
    section { padding: 16px; min-width: 0; }
    .field { margin-bottom: 14px; }
    label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    select, button {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }
    button {
      cursor: pointer;
      font-weight: 650;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.secondary { background: var(--accent-2); border-color: var(--accent-2); }
    button.danger { background: var(--danger); border-color: var(--danger); }
    button.ghost { background: #fff; color: var(--ink); border-color: var(--line); }
    button:disabled { opacity: .55; cursor: wait; }
    .row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    .article-button { margin-top: 8px; background: var(--accent-2); border-color: var(--accent-2); }
    .toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      color: var(--ink);
    }
    .toggle input { width: 16px; height: 16px; }
    .status {
      margin-top: 16px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
    }
    .status strong { display: block; margin-bottom: 4px; }
    .muted { color: var(--muted); }
    .tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
    }
    .tabs button {
      width: auto;
      min-width: 92px;
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
    }
    .tabs button.active { border-color: var(--accent); color: var(--accent); }
    pre {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      min-height: 520px;
      max-height: calc(100vh - 130px);
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .error { color: var(--danger); }
    @media (max-width: 820px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      pre { min-height: 360px; max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <h1>geo-news-bot</h1>
    <span id="latest" class="muted">дайджест: -</span>
  </header>
  <main>
    <aside>
      <div class="field">
        <label for="command">Команда</label>
        <select id="command">
          <option value="all">бәрі</option>
          <option value="collect">жинау</option>
          <option value="report">есеп</option>
        </select>
      </div>
      <div class="field">
        <label for="mode">Режим</label>
        <select id="mode">
          <option value="fast">жылдам</option>
          <option value="normal">қалыпты</option>
        </select>
      </div>
      <label class="toggle">
        <input id="ollama" type="checkbox">
        Ollama қолдану
      </label>
      <div class="row">
        <button id="run">Іске қосу</button>
        <button id="stop" class="danger" disabled>Тоқтату</button>
        <button id="refresh" class="ghost">Жаңарту</button>
      </div>
      <button id="article" class="article-button">Қазақша мақала жазу</button>
      <div class="status">
        <strong id="state">Дайын</strong>
        <div id="meta" class="muted">Тапсырма орындалып жатқан жоқ</div>
        <div id="articlePath" class="muted">мақала: -</div>
      </div>
    </aside>
    <section>
      <div class="tabs">
        <button id="tabDigest" class="active">Дайджест</button>
        <button id="tabLog">Журнал</button>
      </div>
      <pre id="viewer">Жүктеліп жатыр...</pre>
    </section>
  </main>
  <script>
    const viewer = document.querySelector("#viewer");
    const latest = document.querySelector("#latest");
    const state = document.querySelector("#state");
    const meta = document.querySelector("#meta");
    const run = document.querySelector("#run");
    const stop = document.querySelector("#stop");
    const refresh = document.querySelector("#refresh");
    const article = document.querySelector("#article");
    const articlePath = document.querySelector("#articlePath");
    const tabDigest = document.querySelector("#tabDigest");
    const tabLog = document.querySelector("#tabLog");
    let activeTab = "digest";

    const commandLabels = {all: "бәрі", collect: "жинау", report: "есеп", article: "мақала"};
    const modeLabels = {fast: "жылдам", normal: "қалыпты"};

    async function getJSON(url, options) {
      const response = await fetch(url, options);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Сұрау сәтсіз аяқталды");
      return data;
    }

    async function refreshStatus() {
      const status = await getJSON("/api/status");
      run.disabled = status.running;
      article.disabled = status.running;
      stop.disabled = !status.running;
      state.textContent = status.running
        ? "Орындалып жатыр"
        : status.returncode === 0 ? "Аяқталды" : status.stopped ? "Тоқтатылды" : status.finished_at ? "Қате" : "Дайын";
      meta.textContent = status.running
        ? `${commandLabels[status.command] || status.command}, режим: ${modeLabels[status.mode] || status.mode}; басталды: ${status.started_at}`
        : status.finished_at ? `аяқталды: ${status.finished_at}, шығу коды ${status.returncode}` : "Тапсырма орындалып жатқан жоқ";
      latest.textContent = `дайджест: ${status.latest_digest || "-"}`;
      articlePath.textContent = `мақала: ${status.latest_article || "-"}`;
      if (activeTab === "log") {
        viewer.textContent = status.output.join("\n") || "Журнал әзірге жоқ.";
      }
      return status;
    }

    async function refreshDigest() {
      const digest = await getJSON("/api/digest");
      latest.textContent = `дайджест: ${digest.name || "-"}`;
      viewer.textContent = digest.content || "Дайджест әзірге жоқ.";
    }

    async function refreshAll() {
      try {
        const status = await refreshStatus();
        if (activeTab === "digest" && !status.running) await refreshDigest();
      } catch (error) {
        viewer.innerHTML = `<span class="error">${error.message}</span>`;
      }
    }

    run.addEventListener("click", async () => {
      try {
        await getJSON("/api/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            command: document.querySelector("#command").value,
            mode: document.querySelector("#mode").value,
            use_ollama: document.querySelector("#ollama").checked
          })
        });
        activeTab = "log";
        tabLog.classList.add("active");
        tabDigest.classList.remove("active");
        await refreshAll();
      } catch (error) {
        viewer.textContent = error.message;
      }
    });
    article.addEventListener("click", async () => {
      try {
        await getJSON("/api/run", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            command: "article",
            mode: document.querySelector("#mode").value,
            use_ollama: document.querySelector("#ollama").checked
          })
        });
        activeTab = "log";
        tabLog.classList.add("active");
        tabDigest.classList.remove("active");
        await refreshAll();
      } catch (error) {
        viewer.textContent = error.message;
      }
    });
    stop.addEventListener("click", async () => {
      try {
        await getJSON("/api/stop", {method: "POST"});
        activeTab = "log";
        tabLog.classList.add("active");
        tabDigest.classList.remove("active");
        await refreshAll();
      } catch (error) {
        viewer.textContent = error.message;
      }
    });
    refresh.addEventListener("click", refreshAll);
    tabDigest.addEventListener("click", async () => {
      activeTab = "digest";
      tabDigest.classList.add("active");
      tabLog.classList.remove("active");
      await refreshDigest();
    });
    tabLog.addEventListener("click", async () => {
      activeTab = "log";
      tabLog.classList.add("active");
      tabDigest.classList.remove("active");
      await refreshStatus();
    });
    setInterval(refreshAll, 2500);
    refreshAll();
  </script>
</body>
</html>
"""


def main() -> int:
    host = "0.0.0.0"
    port = 8000
    print(f"[gui] listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
