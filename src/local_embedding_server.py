#!/usr/bin/env python3

"""Serve SentenceTransformers embeddings through Ollama's /api/embed shape."""

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_MODEL = "BAAI/bge-m3"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_INPUTS = 32


class EmbeddingRequestHandler(BaseHTTPRequestHandler):
    server_version = "QBotEmbedding/1.0"

    def _send_json(self, status, payload):
        content = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(content)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send_json(
                200,
                {
                    "models": [
                        {
                            "name": "bge-m3",
                            "model": (
                                self.server.model_name
                            ),
                        }
                    ]
                },
            )
            return

        if self.path == "/api/version":
            self._send_json(
                200,
                {"version": "qbot-embedding-1.0"},
            )
            return

        self._send_json(
            404,
            {"error": "Not found."},
        )

    def do_POST(self):
        if self.path != "/api/embed":
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
                {"error": "Invalid request size."},
            )
            return

        try:
            payload = json.loads(
                self.rfile.read(length)
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

        inputs = payload.get("input")

        if isinstance(inputs, str):
            inputs = [inputs]

        if (
            not isinstance(inputs, list)
            or not inputs
            or len(inputs) > MAX_INPUTS
            or not all(
                isinstance(item, str)
                and item.strip()
                for item in inputs
            )
        ):
            self._send_json(
                400,
                {
                    "error": (
                        "input must be a non-empty string "
                        "or a list of non-empty strings."
                    )
                },
            )
            return

        started = time.monotonic()

        try:
            embeddings = self.server.model.encode(
                inputs,
                batch_size=1,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ).tolist()
        except Exception as exc:
            self._send_json(
                500,
                {"error": str(exc)},
            )
            return

        self._send_json(
            200,
            {
                "model": "bge-m3",
                "embeddings": embeddings,
                "total_duration": int(
                    (
                        time.monotonic()
                        - started
                    )
                    * 1_000_000_000
                ),
            },
        )


def load_model(model_name, device=None):
    try:
        from sentence_transformers import (
            SentenceTransformer,
        )
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "See QBOT_CHAT_UI.md."
        ) from exc

    print(
        "Loading embedding model: {}".format(
            model_name
        ),
        flush=True,
    )

    model = SentenceTransformer(
        model_name,
        device=device,
    )

    print(
        "Embedding model ready (device: {}).".format(
            model.device
        ),
        flush=True,
    )

    return model


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Serve BGE-M3 using Ollama-compatible endpoints."
        )
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        default=11434,
        type=int,
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "QBOT_EMBED_MODEL",
            DEFAULT_MODEL,
        ),
    )
    parser.add_argument(
        "--device",
        default=(
            os.environ.get(
                "QBOT_EMBED_DEVICE"
            )
            or None
        ),
        help="Optional SentenceTransformers device, such as cpu or cuda.",
    )
    args = parser.parse_args()

    model = load_model(
        args.model,
        args.device,
    )

    server = ThreadingHTTPServer(
        (args.host, args.port),
        EmbeddingRequestHandler,
    )
    server.daemon_threads = True
    server.model = model
    server.model_name = args.model

    print(
        "Embedding API: http://{}:{}".format(
            args.host,
            args.port,
        ),
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(
            "\nStopping embedding service.",
            flush=True,
        )
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
