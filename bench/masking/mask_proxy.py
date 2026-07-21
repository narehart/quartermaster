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
  MASK_ENABLED        1 to transform, 0 for pass-through control (default 1)
  MASK_MODE           "window" (sliding-window masking; PROVEN CACHE-HOSTILE,
                      kept for the F2 record) or "cap" (deterministic
                      whale-capping; cache-safe by construction) (default cap)
  MASK_KEEP_N         window mode: most-recent tool_result blocks kept (default 3)
  MASK_CAP_CHARS      cap mode: threshold above which a text part is capped
                      (default 16000 chars ~= 4k tokens)
  MASK_HEAD_CHARS     cap mode: chars kept from the head (default 8000)
  MASK_TAIL_CHARS     cap mode: chars kept from the tail (default 4000)
  MASK_OVERFLOW_DIR   cap mode: host dir where full outputs are written for
                      re-fetch; the note references its in-sandbox mount
  MASK_OVERFLOW_MOUNT cap mode: the path where MASK_OVERFLOW_DIR is visible
                      INSIDE the sandbox (default /meta/obs)
  MASK_TARGET_MODEL   only transform requests whose "model" contains this
                      (default claude-opus-4)
  MASK_STATS          optional path to append per-request JSONL stats
  ANTHROPIC_UPSTREAM  upstream host (default api.anthropic.com)

Cache-safety invariant for cap mode: the transform is a PURE FUNCTION of the
text content (hash-keyed, no age/position/counter dependence), so a given
tool_result serializes to identical bytes in every request that carries it —
the cached prefix stays byte-stable. This is the structural fix for the F2
sliding-window pathology (bench/docs/SWEBENCH_LIVE_ANALYSIS.md).
"""

import hashlib
import http.client
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PORT = int(os.environ.get("MASK_PORT", "8788"))
HOST = os.environ.get("MASK_HOST", "0.0.0.0")
ENABLED = os.environ.get("MASK_ENABLED", "1") == "1"
MODE = os.environ.get("MASK_MODE", "cap")
KEEP_N = int(os.environ.get("MASK_KEEP_N", "3"))
CAP_CHARS = int(os.environ.get("MASK_CAP_CHARS", "16000"))
HEAD_CHARS = int(os.environ.get("MASK_HEAD_CHARS", "8000"))
TAIL_CHARS = int(os.environ.get("MASK_TAIL_CHARS", "4000"))
OVERFLOW_DIR = os.environ.get("MASK_OVERFLOW_DIR", "")
OVERFLOW_MOUNT = os.environ.get("MASK_OVERFLOW_MOUNT", "/meta/obs")
TARGET = os.environ.get("MASK_TARGET_MODEL", "claude-opus-4")
STATS_PATH = os.environ.get("MASK_STATS", "")
UPSTREAM = os.environ.get("ANTHROPIC_UPSTREAM", "api.anthropic.com")

PLACEHOLDER = "[observation masked to save context; re-run the tool if you need this output again]"
CAP_MARKER = "[[QM-CAPPED "  # idempotency sentinel: never re-cap our own output
EPOCH_TRIGGER_TOKENS = int(os.environ.get("MASK_EPOCH_TRIGGER_TOKENS", "50000"))
EPOCH_KEEP_RECENT = int(os.environ.get("MASK_EPOCH_KEEP_RECENT", "5"))
EPOCH_CLEAR_AT_LEAST = int(os.environ.get("MASK_EPOCH_CLEAR_AT_LEAST_CHARS", "60000"))
_req_counter = 0

# Epoch-clearing state (one proxy process serves one agent run; requests are
# sequential). Once a tool_use_id enters _cleared_ids its tool_result renders
# as the SAME placeholder in every subsequent request -- byte-stable between
# epochs. New ids are added ONLY at threshold firings (batched, per the
# break-even rule in bench/docs/ORIGINAL_IDEAS.md), so the cached prefix is
# invalidated once per epoch, not per turn (the F2 fix, applied to clearing).
_cleared_ids: set[str] = set()
_epochs_fired = 0


def _content_text_and_hash(content: object) -> tuple[str, str]:
    text = content if isinstance(content, str) else json.dumps(content)
    return text, hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def epoch_placeholder(content: object) -> str:
    """Deterministic replacement for a cleared tool_result: pure function of
    the ORIGINAL content (which the client resends in full every request), so
    a cleared block serializes identically in every later request."""
    text, digest = _content_text_and_hash(content)
    if OVERFLOW_DIR:
        p = Path(OVERFLOW_DIR)
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"{digest}.txt"
        if not f.exists():
            f.write_text(text, errors="replace")
    return (
        f"[[QM-CLEARED {digest}]] old observation cleared at a context checkpoint "
        f"({len(text)} chars). Full output saved at {OVERFLOW_MOUNT}/{digest}.txt — "
        f"Read it with offset/limit if needed."
    )


def epoch_transform(obj: dict, positions: list, stats: dict) -> bool:
    """Apply epoch clearing to a parsed request. Returns True if modified.
    Positions: [(mi, bi)] of tool_result blocks in conversation order."""
    global _epochs_fired
    messages = obj["messages"]
    changed = False
    # 1. Re-apply existing clears (byte-stable between epochs).
    for mi, bi in positions:
        block = messages[mi]["content"][bi]
        tid = block.get("tool_use_id")
        if tid in _cleared_ids:
            ph = epoch_placeholder(block.get("content"))
            if block.get("content") != ph:
                block["content"] = ph
                block.pop("is_error", None)
                changed = True
    # 2. Fire a new epoch if the (post-clear) request is over the trigger.
    est_tokens = len(json.dumps(obj)) // 4
    stats["est_tokens"] = est_tokens
    if est_tokens > EPOCH_TRIGGER_TOKENS:
        candidates = [
            (mi, bi)
            for mi, bi in positions[: max(0, len(positions) - EPOCH_KEEP_RECENT)]
            if messages[mi]["content"][bi].get("tool_use_id") not in _cleared_ids
        ]
        clearable = sum(
            len(_content_text_and_hash(messages[mi]["content"][bi].get("content"))[0])
            for mi, bi in candidates
        )
        # Batch rule: only fire if the epoch reclaims enough to amortize the
        # one-time cache re-write (break-even; see ORIGINAL_IDEAS.md).
        if candidates and clearable >= EPOCH_CLEAR_AT_LEAST:
            _epochs_fired += 1
            for mi, bi in candidates:
                block = messages[mi]["content"][bi]
                _cleared_ids.add(block.get("tool_use_id"))
                block["content"] = epoch_placeholder(block.get("content"))
                block.pop("is_error", None)
            stats["epoch_fired"] = True
            stats["epoch_cleared_chars"] = clearable
            changed = True
    stats["epochs_fired_total"] = _epochs_fired
    stats["cleared_ids_total"] = len(_cleared_ids)
    return changed


def cap_text(text: str) -> str:
    """Deterministic whale-cap: pure function of `text` (hash-keyed, no
    age/position dependence), so the same content always serializes to the
    same bytes -> cache-stable. Writes the full text to the overflow dir
    (idempotent, hash-named) so the agent can re-fetch; the note points at
    the IN-SANDBOX mount and instructs chunked Reads (offset/limit) so a
    re-fetched whale isn't just capped again."""
    if len(text) <= CAP_CHARS or CAP_MARKER in text:
        return text
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
    if OVERFLOW_DIR:
        p = Path(OVERFLOW_DIR)
        p.mkdir(parents=True, exist_ok=True)
        f = p / f"{digest}.txt"
        if not f.exists():
            f.write_text(text, errors="replace")
    note = (
        f"\n\n{CAP_MARKER}{digest}]] output capped to save context: showing first "
        f"{HEAD_CHARS} and last {TAIL_CHARS} of {len(text)} chars. Full output saved at "
        f"{OVERFLOW_MOUNT}/{digest}.txt — Read it with offset/limit to view specific "
        f"sections (do NOT read it whole).\n\n"
    )
    return text[:HEAD_CHARS] + note + text[-TAIL_CHARS:]


def cap_block_content(content: object) -> tuple[object, int]:
    """Apply cap_text to a tool_result's content (string or list of text
    parts). Returns (new_content, n_capped_parts)."""
    if isinstance(content, str):
        new = cap_text(content)
        return new, (1 if new is not content and new != content else 0)
    if isinstance(content, list):
        n = 0
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                new_text = cap_text(part["text"])
                if new_text != part["text"]:
                    part = {**part, "text": new_text}
                    n += 1
            out.append(part)
        return (out, n) if n else (content, 0)
    return content, 0


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
    problem the original body is forwarded unchanged. Dispatches on MASK_MODE:
    "cap" (deterministic whale-capping, cache-safe) or "window" (sliding-window
    masking, cache-hostile, kept for the F2 record)."""
    stats = {"masked": 0, "total_tool_results": 0, "model": None, "applied": False, "mode": MODE}
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

    if MODE == "cap":
        capped = 0
        for mi, bi in positions:
            block = messages[mi]["content"][bi]
            new_content, n = cap_block_content(block.get("content"))
            if n:
                block["content"] = new_content
                capped += n
        stats["masked"] = capped
        stats["applied"] = capped > 0
        if capped == 0:
            return body, stats
        return json.dumps(obj).encode(), stats

    if MODE == "epoch":
        changed = epoch_transform(obj, positions, stats)
        stats["masked"] = stats.get("cleared_ids_total", 0)
        stats["applied"] = changed
        if not changed:
            return body, stats
        return json.dumps(obj).encode(), stats

    # window mode (legacy, cache-hostile)
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
    mode = f"{MODE.upper()}" if ENABLED else "PASSTHROUGH(control)"
    log(
        f"listening on {HOST}:{PORT} mode={mode} keep_n={KEEP_N} cap_chars={CAP_CHARS} "
        f"target={TARGET!r} upstream={UPSTREAM}"
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
