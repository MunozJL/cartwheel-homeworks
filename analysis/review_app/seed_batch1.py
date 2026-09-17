"""Seed Part B's first review batch: 15 uniform + 15 cluster-representative
samples, using the course's own analysis/helpers/selection.py so the same
sampling machinery backs both the manifest and later depth-search batches.

Writes:
  analysis/state/samples.json          full enriched sample records (the UI
                                        reads this directly; regeneratable,
                                        not a "Files to commit" item)
  analysis/state/sample_manifest.json  {trace_id, reason, batch, picked_at}
                                        per pick -- the committed provenance
                                        record HW4 asks for

Usage:
    uv run python -m analysis.review_app.seed_batch1
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from analysis.helpers import _state
from analysis.helpers.selection import select
from analysis.review_app import trace_pool

STATE_DIR = Path(__file__).resolve().parents[1] / "state"


def main() -> None:
    pool = trace_pool.load_pool()
    traces = pool["traces"]
    by_id = {t["id"]: t for t in traces}
    print(f"pool: {len(traces)} traces (offline_reason={pool['offline_reason']!r})")

    uniform = select(traces, 15, "random", exclude_ids=set(), seed=7)
    picked_ids = {p["trace_id"] for p in uniform}
    # "diversity" is ~60-70% nearest-to-cluster-centroid + the rest random,
    # per selection.py's own _diversity_picks -- the closest thing this
    # module offers to pure "cluster representatives" without reimplementing
    # centroid-nearest selection from scratch. Exclude the uniform batch's
    # ids so all 30 of batch 1 are distinct.
    cluster = select(traces, 15, "diversity", exclude_ids=picked_ids, seed=11)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = []
    samples = []
    for batch_name, picks in (("batch1_uniform", uniform), ("batch1_cluster", cluster)):
        for p in picks:
            tid = p["trace_id"]
            manifest.append({
                "trace_id": tid, "reason": p["reason"], "batch": batch_name, "picked_at": now,
            })
            t = by_id.get(tid, {})
            samples.append({
                "trace_id": tid,
                "reason": p["reason"],
                "batch": batch_name,
                "trace": t.get("trace", []),
                "meta": t.get("meta", {}),
                "scenario": t.get("scenario", {}),
                "permalink": t.get("permalink"),
                "text": t.get("text", ""),
                "flags": [],
            })

    _state.write_json(STATE_DIR / "samples.json", samples)
    _state.write_json(STATE_DIR / "sample_manifest.json", manifest)
    print(f"wrote {len(samples)} samples to state/samples.json")
    print(f"wrote {len(manifest)} manifest rows to state/sample_manifest.json")
    print("batches:", {b: sum(1 for m in manifest if m["batch"] == b) for b in ("batch1_uniform", "batch1_cluster")})


if __name__ == "__main__":
    main()
