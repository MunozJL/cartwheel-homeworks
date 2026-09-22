"""One-time import: load the 117 traces bundled in homework/module-2/
hw3-reference.patch (extracted separately, since applying that patch
whole would conflict with our own real HW3 files) into this Langfuse
project via the raw ingestion API, preserving their original ids.

Needed because analysis/state/labels/uninformative_response.jsonl (from
the applied hw4-reference.patch) references 100 trace ids that only exist
in that reference bundle, not in our own Cartwheel Langfuse project. HW5's
judge tooling needs real trace content for those ids to write examples
and run evaluations against.

Usage:
    uv run python -m analysis.review_app.import_reference_traces <path-to-extracted-traces.json>
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from observability.instrument import load_env

load_env()

import os  # noqa: E402

HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
PUBLIC_KEY = os.environ["LANGFUSE_PUBLIC_KEY"]
SECRET_KEY = os.environ["LANGFUSE_SECRET_KEY"]

BATCH_SIZE = 50


def _post_batch(events: list[dict[str, Any]]) -> dict[str, Any]:
    import base64

    body = json.dumps({"batch": events}).encode()
    req = urllib.request.Request(
        f"{HOST}/api/public/ingestion", data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Basic " + base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode(),
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _trace_event(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"import-trace-{t['id']}",
        "type": "trace-create",
        "timestamp": t.get("timestamp") or t.get("createdAt"),
        "body": {
            "id": t["id"],
            "name": t.get("name"),
            "timestamp": t.get("timestamp") or t.get("createdAt"),
            "input": t.get("input"),
            "output": t.get("output"),
            "metadata": t.get("metadata"),
            "tags": t.get("tags") or [],
            "public": bool(t.get("public")),
        },
    }


_OBS_EVENT_TYPE = {"SPAN": "span-create", "GENERATION": "generation-create", "EVENT": "event-create"}


def _observation_event(o: dict[str, Any], trace_id: str) -> dict[str, Any] | None:
    ev_type = _OBS_EVENT_TYPE.get(o.get("type"))
    if not ev_type:
        return None
    body = {
        "id": o["id"],
        "traceId": trace_id,
        "parentObservationId": o.get("parentObservationId"),
        "name": o.get("name"),
        "startTime": o.get("startTime"),
        "metadata": o.get("metadata"),
        "input": o.get("input"),
        "output": o.get("output"),
    }
    if ev_type != "event-create":
        body["endTime"] = o.get("endTime")
    if ev_type == "generation-create":
        body["model"] = o.get("model")
        body["modelParameters"] = o.get("modelParameters")
        body["usage"] = o.get("usage")
    return {
        "id": f"import-obs-{o['id']}",
        "type": ev_type,
        "timestamp": o.get("startTime"),
        "body": body,
    }


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "traces_export.json")
    data = json.loads(path.read_text())
    traces = data.get("traces", data if isinstance(data, list) else [])
    print(f"loaded {len(traces)} traces from {path}")

    events: list[dict[str, Any]] = []
    for t in traces:
        events.append(_trace_event(t))
        for o in t.get("observations") or []:
            ev = _observation_event(o, t["id"])
            if ev:
                events.append(ev)

    print(f"built {len(events)} ingestion events ({len(traces)} traces + observations)")

    sent = 0
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i : i + BATCH_SIZE]
        result = _post_batch(batch)
        errors = result.get("errors") or []
        if errors:
            print(f"  batch {i // BATCH_SIZE}: {len(errors)} errors, e.g. {errors[0]}")
        sent += len(batch)
        print(f"  sent {sent}/{len(events)}")
        time.sleep(0.2)

    print("done. Give the worker a few seconds to process, then verify via /api/traces.")


if __name__ == "__main__":
    main()
