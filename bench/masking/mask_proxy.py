#!/usr/bin/env python3
"""Tail-only observation-masking proxy for Claude Code (or any Anthropic API
client that honors ANTHROPIC_BASE_URL).

Claude Code sends its full conversation to POST /v1/messages every turn. Point
it at this proxy (ANTHROPIC_BASE_URL=http://<proxy>:<port>) and, for requests
matching the target model, we rewrite the OUTBOUND request body: replace the
content of all but the most-recent N `tool_result` blocks with a short
placeholder, leaving system/tools (the cacheable prefix) and the recent tail
untouched. The response stream is passed through byte-for-byte.

This applies tail-only observation masking to the REAL Claude Code scaffold
without hooks or a fork — only what the model *sees* changes; Claude Code's own
bookkeeping is intact. Set MASK_ENABLED=0 for a pass-through control that is
otherwise byte-identical.

Security: the client's auth header is forwarded upstream verbatim and is NEVER
logged. Only masking COUNTS (never message content or headers) are recorded.

Env config:
  MASK_PORT           listen port (default 8788)
  MASK_HOST           bind host (default 0.0.0.0 so a Docker sandbox can reach it)
  MASK_ENABLED        1 to mask, 0 for pass-through control (default 1)
  MASK_KEEP_N         most-recent tool_result blocks kept at full fidelity (default 3)
  MASK_TARGET_MODEL   only mask requests whose "model" contains this (default claude-opus-4)
  MASK_STATS          optional path to append per-request JSONL masking stats
  ANTHROPIC_UPSTREAM  upstream host (default api.anthropic.com)
"""

import http.client
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PORT = int(os.environ.get("MASK_PORT", "8788"))
HOST = os.environ.get("MASK_HOST", "0.0.0.0")
ENABLED = os.environ.get("MASK_ENABLED", "1") == "1"
KEEP_N = int(os.environ.get("MASK_KEEP_N", "3"))
TARGET = os.environ.get("MASK_TARGET_MODEL", "claude-opus-4")
STATS_PATH = os.environ.get("MASK_STATS", "")
UPSTREAM = os.environ.get("ANTHROPIC_UPSTREAM", "api.anthropic.com")

PLACEHOLDER = "[observation masked to save context; re-run the tool if you need this output again]"
_req_counter = 0


def log(msg: str) -> None:
    sys.stderr.write(f"[mask_proxy] {msg}\n")
    sys.stderr.flush()


def record_stats(entry: dict) -> None:
    if not STATS_PATH:
        return
    try:
        with open(STATS_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def mask_request(body: bytes) -> tuple[bytes, dict]:
    """Return (possibly-rewritten body, stats). Never raises: on any parse
    problem the original body is forwarded unchanged."""
    stats = {"masked": 0, "total_tool_results": 0, "model": None, "applied": False}
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body, stats
    model = obj.get("model", "") if isinstance(obj, dict) else ""
    stats["model"] = model
    if not ENABLED or TARGET not in model:
        return body, stats
    messages = obj.get("messages")
    if not isinstance(messages, list):
        return body, stats
    # Locate every tool_result block, in conversation order.
    positions = []
    for mi, m in enumerate(messages):
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, list):
            for bi, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    positions.append((mi, bi))
    stats["total_tool_results"] = len(positions)
    if len(positions) <= KEEP_N:
        return body, stats
    masked = 0
    for mi, bi in positions[: len(positions) - KEEP_N]:
        block = messages[mi]["content"][bi]
        if block.get("content") == PLACEHOLDER:
            continue
        # Preserve tool_use_id + any cache_control; only shrink the payload.
        block["content"] = PLACEHOLDER
        block.pop("is_error", None)
        masked += 1
    stats["masked"] = masked
    stats["applied"] = masked > 0
    if masked == 0:
        return body, stats
    return json.dumps(obj).encode(), stats


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence default noisy logging
        return

    def _proxy(self, method: str):
        global _req_counter
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""

        stats = {"masked": 0, "total_tool_results": 0, "model": None, "applied": False}
        # Claude Code posts to /v1/messages?beta=true (query string) and also
        # /v1/messages/count_tokens; strip the query and match the messages
        # endpoints so masking is applied consistently to both the billed model
        # call and Claude Code's own token-budget estimate.
        path_only = urlsplit(self.path).path
        if method == "POST" and "/v1/messages" in path_only:
            body, stats = mask_request(body)
            _req_counter += 1
            entry = {"req": _req_counter, "path": self.path, **stats}
            record_stats(entry)
            if stats["total_tool_results"]:
                log(
                    f"req#{_req_counter} model={stats['model']} "
                    f"tool_results={stats['total_tool_results']} masked={stats['masked']}"
                )

        # Forward upstream over TLS, streaming the response straight back.
        conn = http.client.HTTPSConnection(UPSTREAM, timeout=600)
        fwd_headers = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in ("host", "content-length", "accept-encoding", "connection"):
                continue
            fwd_headers[k] = v
        fwd_headers["Host"] = UPSTREAM
        fwd_headers["Content-Length"] = str(len(body))
        fwd_headers["Accept-Encoding"] = "identity"  # keep the stream un-gzipped for passthrough
        try:
            conn.request(method, self.path, body=body, headers=fwd_headers)
            resp = conn.getresponse()
        except Exception as e:  # upstream failure -> 502
            log(f"upstream error: {type(e).__name__}: {e}")
            self.send_response(502)
            self.end_headers()
            return

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in ("content-length", "transfer-encoding", "connection"):
                continue
            self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            try:
                self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
        conn.close()

    def do_POST(self):
        self._proxy("POST")

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self._proxy("GET")


def main():
    mode = "MASK" if ENABLED else "PASSTHROUGH(control)"
    log(f"listening on {HOST}:{PORT} mode={mode} keep_n={KEEP_N} target={TARGET!r} upstream={UPSTREAM}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
