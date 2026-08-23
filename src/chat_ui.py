#!/usr/bin/env python3

"""Small browser chat UI for the QBot RAG assistant."""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


REPO_DIR = Path(__file__).resolve().parents[1]
from chat_history import ExcelChatLogger  # noqa: E402
import rag_chat_adapter as rag_service  # noqa: E402


MAX_REQUEST_BYTES = 64 * 1024
MAX_NAME_LENGTH = 120
MAX_QUESTION_LENGTH = 8000


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QBot Log Assistant</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #18323c;
      --muted: #657980;
      --panel: #ffffff;
      --line: #d8e2e5;
      --accent: #16758a;
      --accent-dark: #0d5364;
      --user: #e4f4f7;
      --bot: #f5f3ec;
      --danger: #a63b32;
      --shadow: 0 20px 55px rgba(30, 62, 71, .13);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 10% 0%, #d9eef0 0, transparent 32rem),
        linear-gradient(150deg, #eef4f2, #e7edef 65%, #dfeaec);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    .shell {
      width: min(1080px, calc(100% - 28px));
      height: min(860px, calc(100vh - 28px));
      min-height: 620px;
      margin: 14px auto;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr) auto;
      overflow: hidden;
      background: rgba(255, 255, 255, .94);
      border: 1px solid rgba(255, 255, 255, .8);
      border-radius: 24px;
      box-shadow: var(--shadow);
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      padding: 22px 26px 16px;
      border-bottom: 1px solid var(--line);
    }

    .brand { display: flex; align-items: center; gap: 14px; }

    .mark {
      display: grid;
      width: 46px;
      height: 46px;
      place-items: center;
      border-radius: 15px;
      background: var(--ink);
      color: white;
      font-weight: 800;
      letter-spacing: -.04em;
    }

    h1 { margin: 0; font-size: 1.22rem; letter-spacing: -.02em; }
    .subtitle { margin-top: 3px; color: var(--muted); font-size: .86rem; }

    .status {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: .82rem;
      white-space: nowrap;
    }

    .dot {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #d3983c;
      box-shadow: 0 0 0 4px rgba(211, 152, 60, .15);
    }

    .dot.ready { background: #3a9b70; box-shadow: 0 0 0 4px rgba(58, 155, 112, .14); }
    .dot.error { background: var(--danger); box-shadow: 0 0 0 4px rgba(166, 59, 50, .14); }

    .controls {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr);
      gap: 12px;
      padding: 14px 26px;
      background: #f8faf9;
      border-bottom: 1px solid var(--line);
    }

    label { display: grid; gap: 5px; color: var(--muted); font-size: .72rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }

    input, textarea, button {
      font: inherit;
    }

    input, textarea {
      width: 100%;
      color: var(--ink);
      background: white;
      border: 1px solid #c9d6da;
      border-radius: 11px;
      outline: none;
      transition: border-color .15s, box-shadow .15s;
    }

    input { height: 40px; padding: 0 11px; }
    textarea { min-height: 54px; max-height: 160px; resize: vertical; padding: 14px 15px; line-height: 1.45; }
    input:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(22, 117, 138, .11); }

    .messages {
      min-height: 0;
      overflow-y: auto;
      padding: 24px 26px 16px;
      scroll-behavior: smooth;
    }

    .message { display: flex; margin-bottom: 18px; }
    .message.user { justify-content: flex-end; }

    .bubble {
      max-width: min(760px, 86%);
      padding: 13px 16px;
      border: 1px solid var(--line);
      border-radius: 16px 16px 16px 5px;
      background: var(--bot);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.5;
      font-size: .94rem;
    }

    .user .bubble { background: var(--user); border-color: #bfdee5; border-radius: 16px 16px 5px 16px; }
    .error-message .bubble { color: var(--danger); background: #fff1ef; border-color: #efcbc6; }

    .thinking .bubble::after {
      content: "";
      display: inline-block;
      width: 16px;
      height: 4px;
      margin-left: 8px;
      border-radius: 4px;
      background: var(--accent);
      animation: pulse 1s infinite alternate ease-in-out;
      vertical-align: middle;
    }

    @keyframes pulse { to { opacity: .25; transform: translateX(7px); } }

    .composer {
      padding: 15px 18px 18px;
      border-top: 1px solid var(--line);
      background: white;
    }

    .compose-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 11px; align-items: end; }

    button {
      min-width: 108px;
      height: 54px;
      border: 0;
      border-radius: 13px;
      color: white;
      background: var(--accent);
      font-weight: 800;
      cursor: pointer;
      transition: background .15s, transform .15s;
    }

    button:hover { background: var(--accent-dark); transform: translateY(-1px); }
    button:disabled { cursor: wait; opacity: .55; transform: none; }
    .hint { margin: 7px 3px 0; color: var(--muted); font-size: .72rem; }

    @media (max-width: 740px) {
      .shell { width: 100%; height: 100vh; min-height: 560px; margin: 0; border-radius: 0; }
      header { padding: 16px; }
      .controls { grid-template-columns: 1fr 1fr; padding: 12px 16px; }
      .messages { padding: 18px 16px 10px; }
      .status span:last-child { display: none; }
      button { min-width: 84px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header>
      <div class="brand">
        <div class="mark">QB</div>
        <div>
          <h1>QBot Log Assistant</h1>
          <div class="subtitle">Answers grounded in recorded robot evidence</div>
        </div>
      </div>
      <div class="status"><span id="statusDot" class="dot"></span><span id="statusText">Checking pipeline…</span></div>
    </header>

    <section class="controls" aria-label="Chat settings">
      <label>Your name
        <input id="userName" maxlength="120" autocomplete="name" placeholder="Enter your name" required>
      </label>
      <label>Map (optional)
        <input id="mapName" list="mapOptions" placeholder="All indexed maps">
        <datalist id="mapOptions"></datalist>
      </label>
    </section>

    <section id="messages" class="messages" aria-live="polite">
      <div class="message"><div class="bubble">Hello. Ask me about a recorded QBot task, movement, failure, or destination.</div></div>
    </section>

    <form id="chatForm" class="composer">
      <div class="compose-row">
        <textarea id="question" maxlength="8000" placeholder="Ask what happened and why…" required></textarea>
        <button id="sendButton" type="submit">Send</button>
      </div>
      <div class="hint">Enter to send · Shift+Enter for a new line · each exchange is written to Excel</div>
    </form>
  </main>

  <script>
    const form = document.getElementById('chatForm');
    const messages = document.getElementById('messages');
    const question = document.getElementById('question');
    const userName = document.getElementById('userName');
    const sendButton = document.getElementById('sendButton');
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');

    const savedName = localStorage.getItem('qbot-user-name');
    if (savedName) userName.value = savedName;

    function addMessage(text, role, extraClass = '') {
      const row = document.createElement('div');
      row.className = `message ${role} ${extraClass}`.trim();
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = text;
      row.appendChild(bubble);
      messages.appendChild(row);
      messages.scrollTop = messages.scrollHeight;
      return row;
    }

    async function loadStatus() {
      try {
        const response = await fetch('/api/status');
        const data = await response.json();
        const configured = data.api_key_configured;
        const indexed = data.retrieval_indexes_ready;
        statusDot.className = `dot ${configured && indexed ? 'ready' : 'error'}`;
        statusText.textContent = configured && indexed
          ? `${data.model} · ready`
          : (!configured ? 'NVIDIA_API_KEY is not set' : 'RAG indexes are not built');

        const options = document.getElementById('mapOptions');
        data.maps.forEach(name => {
          const option = document.createElement('option');
          option.value = name;
          options.appendChild(option);
        });
      } catch (error) {
        statusDot.className = 'dot error';
        statusText.textContent = 'UI status unavailable';
      }
    }

    question.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const name = userName.value.trim();
      const text = question.value.trim();

      if (!name) {
        userName.focus();
        userName.setCustomValidity('Please enter your name.');
        userName.reportValidity();
        return;
      }
      userName.setCustomValidity('');
      if (!text) return;

      localStorage.setItem('qbot-user-name', name);
      addMessage(text, 'user');
      question.value = '';
      sendButton.disabled = true;
      const thinking = addMessage('Searching the robot logs and preparing an answer', 'assistant', 'thinking');

      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            user_name: name,
            question: text,
            map: document.getElementById('mapName').value.trim()
          })
        });
        const data = await response.json();
        thinking.remove();
        addMessage(data.answer || data.error || 'No response was returned.', 'assistant', response.ok ? '' : 'error-message');
        if (data.log_warning) addMessage(data.log_warning, 'assistant', 'error-message');
      } catch (error) {
        thinking.remove();
        addMessage(`Could not reach the QBot chat service: ${error.message}`, 'assistant', 'error-message');
      } finally {
        sendButton.disabled = false;
        question.focus();
      }
    });

    loadStatus();
    question.focus();
  </script>
</body>
</html>
"""


class ChatRequestHandler(BaseHTTPRequestHandler):
    server_version = "QBotChat/1.0"

    def _send_bytes(
        self,
        status,
        content_type,
        content,
        disposition=None,
    ):
        self.send_response(status)
        self.send_header(
            "Content-Type",
            content_type,
        )
        self.send_header(
            "Content-Length",
            str(len(content)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )

        if disposition:
            self.send_header(
                "Content-Disposition",
                disposition,
            )

        self.end_headers()
        self.wfile.write(content)

    def _send_json(
        self,
        status,
        payload,
    ):
        content = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")
        self._send_bytes(
            status,
            "application/json; charset=utf-8",
            content,
        )

    def do_GET(self):
        path = urlsplit(
            self.path
        ).path

        if path == "/":
            self._send_bytes(
                200,
                "text/html; charset=utf-8",
                PAGE.encode("utf-8"),
            )
            return

        if path == "/api/status":
            maps = sorted({
                item.parent.name
                for item in (
                    rag_service
                    .map_embedding_files()
                )
            })

            indexes_ready = any([
                rag_service
                .GLOBAL_EMBEDDINGS
                .exists(),
                rag_service
                .INTENT_EMBEDDINGS
                .exists(),
                bool(maps),
            ])

            self._send_json(
                200,
                {
                    "model":
                        rag_service.NVIDIA_MODEL,
                    "api_key_configured":
                        bool(os.environ.get(
                            "NVIDIA_API_KEY"
                        )),
                    "retrieval_indexes_ready":
                        indexes_ready,
                    "maps": maps,
                },
            )
            return

        self._send_json(
            404,
            {"error": "Not found."},
        )

    def do_POST(self):
        path = urlsplit(
            self.path
        ).path

        if path != "/api/chat":
            self._send_json(
                404,
                {"error": "Not found."},
            )
            return

        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )
        except ValueError:
            length = 0

        if (
            length <= 0
            or length > MAX_REQUEST_BYTES
        ):
            self._send_json(
                400,
                {
                    "error": (
                        "Request body is empty or too large."
                    )
                },
            )
            return

        try:
            payload = json.loads(
                self.rfile
                .read(length)
                .decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            self._send_json(
                400,
                {"error": "Invalid JSON request."},
            )
            return

        if not isinstance(payload, dict):
            self._send_json(
                400,
                {"error": "JSON body must be an object."},
            )
            return

        user_name = payload.get(
            "user_name",
            "",
        )
        question = payload.get(
            "question",
            "",
        )
        requested_map = payload.get(
            "map",
            "",
        )

        if not isinstance(user_name, str):
            user_name = ""
        if not isinstance(question, str):
            question = ""
        if not isinstance(requested_map, str):
            requested_map = ""

        user_name = user_name.strip()
        question = question.strip()
        requested_map = (
            requested_map.strip()
            or None
        )

        validation_error = None

        if not user_name:
            validation_error = (
                "User name is required."
            )
        elif len(user_name) > MAX_NAME_LENGTH:
            validation_error = (
                "User name is too long."
            )
        elif not question:
            validation_error = (
                "Question is required."
            )
        elif len(question) > MAX_QUESTION_LENGTH:
            validation_error = (
                "Question is too long."
            )
        elif (
            requested_map
            and (
                len(requested_map) > 200
                or "/" in requested_map
                or "\\" in requested_map
                or requested_map in {".", ".."}
            )
        ):
            validation_error = (
                "Invalid map name."
            )
        if validation_error:
            self._send_json(
                400,
                {"error": validation_error},
            )
            return

        started = time.monotonic()
        answer = ""
        error = ""
        model = rag_service.NVIDIA_MODEL
        packet_count = 0
        used_llm = False
        record_status = "error"
        http_status = 200

        try:
            result = rag_service.answer_question(
                question,
                requested_map=requested_map,
                audience="user",
            )
            answer = result["answer"]
            model = result["model"]
            packet_count = result[
                "packet_count"
            ]
            used_llm = result[
                "used_llm"
            ]
            record_status = (
                "ok"
                if used_llm
                else "no_evidence"
            )
        except Exception as exc:
            error = str(exc)
            answer = (
                "I could not complete the RAG request. "
                + error
            )
            http_status = 502

        elapsed_ms = round(
            (
                time.monotonic()
                - started
            )
            * 1000
        )

        log_warning = ""

        try:
            self.server.logger.append(
                {
                    "user_name": user_name,
                    "question": question,
                    "llm_response": answer,
                    "model": model,
                    "audience": "user",
                    "map": requested_map or "",
                    "status": record_status,
                    "used_llm": used_llm,
                    "packet_count": packet_count,
                    "response_time_ms": elapsed_ms,
                    "error": error,
                }
            )
        except Exception as exc:
            log_warning = (
                "The answer was returned, but the Excel "
                "log could not be updated: "
                + str(exc)
            )
            http_status = 500

        self._send_json(
            http_status,
            {
                "answer": answer,
                "model": model,
                "status": record_status,
                "used_llm": used_llm,
                "packet_count": packet_count,
                "response_time_ms": elapsed_ms,
                "error": error,
                "log_warning": log_warning,
            },
        )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Serve the QBot RAG chat UI."
        )
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
    )
    parser.add_argument(
        "--port",
        default=8766,
        type=int,
    )
    parser.add_argument(
        "--log-file",
        default=str(
            REPO_DIR
            / "runtime_logs"
            / "private_chat"
            / "qbot_chat_history.xlsx"
        ),
        help="Path to the generated Excel workbook.",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        (
            args.host,
            args.port,
        ),
        ChatRequestHandler,
    )
    server.daemon_threads = True
    server.logger = ExcelChatLogger(
        args.log_file
    )

    print(
        "QBot chat UI is running."
    )
    print(
        "Open: http://ROBOT_IP:{}".format(
            args.port
        )
    )
    print(
        "Excel log: {}".format(
            server.logger.xlsx_path
        )
    )

    if not os.environ.get(
        "NVIDIA_API_KEY"
    ):
        print(
            "WARNING: NVIDIA_API_KEY is not set."
        )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping QBot chat UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
