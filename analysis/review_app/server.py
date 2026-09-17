"""Review server for Homework 4 (adapted from analysis/server.py).

Kept: the file-backed JSON API pattern (GET reads a state file, POST
overwrites it, every write is atomic) and the annotation -> Langfuse score
sync, both of which are correct for HW4 unchanged.

Added, because the reference server only serves a pre-built local sample
file and has no notion of a failure-mode label separate from a free-text
annotation:

  GET  /api/traces        the full normalized+enriched trace pool (see
                           trace_pool.py) -- backs sampling scripts and the
                           labeling view's trace picker
  POST /api/refresh       rebuild the trace pool from live Langfuse (falls
                           back to the Module 1 export; see trace_pool.py)
  GET  /api/labels        {mode: [{trace_id, label, note, ts}, ...]} for
                           every mode with a label file under
                           analysis/state/labels/, using the append-only,
                           superseded_by-flip convention analysis/helpers
                           already uses for HW5 (kept consistent on purpose:
                           the same files feed both homeworks)
  POST /api/labels        body: {mode, trace_id, label, note}. Appends one
                           row (marking any prior row for the same
                           trace_id+mode superseded), writes the Langfuse
                           score, and updates analysis/state/labels/<mode>.jsonl

/api/graph now returns the live pool's projection instead of a static file.

Run it:
    uv run python -m analysis.review_app.server            # serve on :8030
    uv run python -m analysis.review_app.server --port 8031
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
STATE_DIR = REPO_ROOT / "analysis" / "state"
LABELS_DIR = STATE_DIR / "labels"
UI_DIR = HERE / "ui"

sys.path.insert(0, str(REPO_ROOT))

from analysis.helpers import _state  # noqa: E402
from analysis.review_app import trace_pool  # noqa: E402

API_FILES: dict[str, Path] = {
    "/api/samples": STATE_DIR / "samples.json",
    "/api/annotations": STATE_DIR / "annotations.json",
    "/api/patterns": STATE_DIR / "patterns.json",
    "/api/suggestions": STATE_DIR / "suggestions.json",
}
API_DEFAULTS: dict[str, Any] = {
    "/api/samples": [],
    "/api/annotations": [],
    "/api/patterns": {},
    "/api/suggestions": [],
}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _count(data: Any) -> int:
    if isinstance(data, (list, dict)):
        return len(data)
    return 0


def _annotation_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("annotations", [])
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def _sync_annotation_scores(data: Any) -> int:
    """Same contract as the reference server: score only mode+0/1-label rows."""
    try:
        from analysis.helpers import langfuse_io
    except Exception:
        return 0
    if not langfuse_io.is_configured():
        return 0
    written = 0
    client = langfuse_io._client()
    for ann in _annotation_list(data):
        trace_id, mode, label = ann.get("trace_id"), ann.get("mode"), ann.get("label")
        if not trace_id or not mode or label not in (0, 1, "0", "1"):
            continue
        langfuse_io.write_label_score(
            trace_id=str(trace_id), mode=str(mode), label=int(label),
            comment=ann.get("note"), client=client,
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# Structured labels: one append-only JSONL file per mode under state/labels/.
# ---------------------------------------------------------------------------


def _mode_label_path(mode: str) -> Path:
    safe = "".join(c for c in mode if c.isalnum() or c in "_-") or "unnamed"
    return LABELS_DIR / f"{safe}.jsonl"


def _live_labels_for_mode(mode: str) -> list[dict[str, Any]]:
    """Latest (non-superseded) row per trace_id.

    A row that itself carries a ``superseded_by`` pointer is the OLD side of
    a flip and must be skipped; the replacement row (named by that pointer)
    has no ``superseded_by`` of its own and is what should show as current.
    """
    rows = _state.read_jsonl(_mode_label_path(mode))
    live: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("superseded_by"):
            continue
        live[row["trace_id"]] = row
    return list(live.values())


def _all_labels() -> dict[str, list[dict[str, Any]]]:
    if not LABELS_DIR.exists():
        return {}
    return {p.stem: _live_labels_for_mode(p.stem) for p in LABELS_DIR.glob("*.jsonl")}


def _write_label(mode: str, trace_id: str, label: int, note: str | None) -> dict[str, Any]:
    path = _mode_label_path(mode)
    existing = _state.read_jsonl(path)
    prior = next(
        (r for r in reversed(existing) if r.get("trace_id") == trace_id and not r.get("superseded_by")),
        None,
    )
    new_id = f"lbl_{trace_id}_{mode}_{int(time.time() * 1000)}"
    record = {
        "id": new_id, "trace_id": trace_id, "mode": mode,
        "label": int(label), "note": note or "",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if prior is not None:
        # Append-only flip: mark the prior row dead, never rewrite it in place.
        rows = existing[:]
        for i, r in enumerate(rows):
            if r is prior:
                rows[i] = {**r, "superseded_by": new_id}
        _state.write_jsonl(path, rows + [record])
    else:
        _state.append_jsonl(path, record)

    try:
        from analysis.helpers import langfuse_io

        if langfuse_io.is_configured():
            langfuse_io.write_label_score(
                trace_id=trace_id, mode=mode, label=int(label), comment=note
            )
    except Exception as exc:  # noqa: BLE001
        record["langfuse_error"] = str(exc)
    return record


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": f"not found: {path.name}"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({}, status=204)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/ui/"):
            asset = UI_DIR / path[len("/ui/"):]
            if asset.is_file() and UI_DIR in asset.resolve().parents:
                self._send_file(asset, _guess_type(asset))
                return

        if path == "/api/traces":
            pool = trace_pool.load_pool()
            self._send_json(pool["traces"])
            return
        if path == "/api/graph":
            pool = trace_pool.load_pool()
            self._send_json(pool["graph"])
            return
        if path == "/api/labels":
            self._send_json(_all_labels())
            return
        if path in API_FILES:
            self._send_json(_read_json(API_FILES[path], API_DEFAULTS[path]))
            return

        self._send_json({"error": f"unknown path: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/api/refresh":
            pool = trace_pool.load_pool(refresh=True)
            self._send_json({"ok": True, "count": pool["count"], "offline_reason": pool["offline_reason"]})
            return

        if path == "/api/labels":
            body = self._read_body()
            if not isinstance(body, dict) or "mode" not in body or "trace_id" not in body:
                self._send_json({"error": "expected {mode, trace_id, label, note}"}, status=400)
                return
            record = _write_label(
                mode=str(body["mode"]), trace_id=str(body["trace_id"]),
                label=int(body.get("label", 0)), note=body.get("note"),
            )
            self._send_json({"ok": True, "record": record})
            return

        if path not in API_FILES:
            self._send_json({"error": f"cannot POST to {path}"}, status=404)
            return
        data = self._read_body()
        if data is None:
            self._send_json({"error": "expected a JSON body"}, status=400)
            return
        synced = 0
        if path == "/api/annotations":
            try:
                synced = _sync_annotation_scores(data)
            except Exception as exc:  # noqa: BLE001
                _write_json(API_FILES[path], data)
                self._send_json(
                    {"error": f"Langfuse score write failed: {exc}", "cached_locally": True},
                    status=502,
                )
                return
        _write_json(API_FILES[path], data)
        result = {"ok": True, "count": _count(data)}
        if synced:
            result["langfuse_scores_written"] = synced
        self._send_json(result)


def _guess_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
        ".json": "application/json", ".svg": "image/svg+xml",
    }.get(path.suffix, "application/octet-stream")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), ReviewHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"HW4 review interface on {url}")
    print(f"serving state from {STATE_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
