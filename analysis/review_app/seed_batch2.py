"""Seed Part B's second review batch: 30 traces stratified evenly across
`intent` (chosen by the student before looking at outcomes, per the
handout). Excludes every trace already in batch 1. Draws only from the
corrected pool (HW3 final-run traces, pilot-run excluded).

Appends to (does not replace):
  analysis/state/samples.json          (regeneratable, not committed)
  analysis/state/sample_manifest.json  (committed provenance record)

Usage:
    uv run python -m analysis.review_app.seed_batch2
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from pathlib import Path

from analysis.helpers import _state
from analysis.review_app import trace_pool

STATE_DIR = Path(__file__).resolve().parents[1] / "state"
SEED = 23
TOTAL = 30
INTENTS_4 = ["order_status", "product_search", "return_or_refund_eligibility",
             "issue_refund", "policy_question", "cancel_order"]
INTENTS_3 = ["escalation_or_dispute", "out_of_scope_refusal"]


def main() -> None:
    pool = trace_pool.load_pool()
    traces = pool["traces"]
    print(f"pool: {len(traces)} traces (offline_reason={pool['offline_reason']!r})")

    existing_samples = _state.read_json(STATE_DIR / "samples.json", [])
    existing_ids = {s["trace_id"] for s in existing_samples}
    print(f"excluding {len(existing_ids)} traces already in earlier batches")

    by_intent: dict[str, list[dict]] = defaultdict(list)
    for t in traces:
        if t["id"] in existing_ids:
            continue
        by_intent[t["meta"].get("intent")].append(t)

    rng = random.Random(SEED)
    quota = {**{i: 4 for i in INTENTS_4}, **{i: 3 for i in INTENTS_3}}
    assert sum(quota.values()) == TOTAL

    picked: list[dict] = []
    for intent, n in quota.items():
        pool_i = by_intent.get(intent, [])
        if len(pool_i) < n:
            raise RuntimeError(f"only {len(pool_i)} available traces for intent={intent}, need {n}")
        picked.extend(rng.sample(pool_i, n))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_samples = []
    new_manifest = []
    for t in picked:
        reason = f"batch2_intent:{t['meta'].get('intent')}"
        new_manifest.append({"trace_id": t["id"], "reason": reason, "batch": "batch2_intent", "picked_at": now})
        new_samples.append({
            "trace_id": t["id"],
            "reason": reason,
            "batch": "batch2_intent",
            "trace": t.get("trace", []),
            "meta": t.get("meta", {}),
            "scenario": t.get("scenario", {}),
            "permalink": t.get("permalink"),
            "text": t.get("text", ""),
            "flags": [],
        })

    all_samples = existing_samples + new_samples
    all_manifest = _state.read_json(STATE_DIR / "sample_manifest.json", []) + new_manifest
    _state.write_json(STATE_DIR / "samples.json", all_samples)
    _state.write_json(STATE_DIR / "sample_manifest.json", all_manifest)

    print(f"added {len(new_samples)} batch-2 samples (total now {len(all_samples)})")
    from collections import Counter
    print("batch 2 intent counts:", dict(Counter(s["meta"].get("intent") for s in new_samples)))


if __name__ == "__main__":
    main()
