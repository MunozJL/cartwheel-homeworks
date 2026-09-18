"""Load, normalize, and enrich the Cartwheel trace pool for HW4 review.

Langfuse is canonical (per hw4.md's "Prepare Langfuse" section). This module
tries a live fetch first and falls back to the committed Module 1 export
(``traces/support_traces.json``) only when Langfuse is unreachable, recording
the reason so the interface comparison can note it honestly.

On top of the shared ``analysis/helpers`` normalization, this module adds two
things HW4 specifically needs that HW1-3 traces do not carry as span
attributes:

  - scenario metadata (``scenario_group``, ``intent``, ``difficulty``,
    ``data_quality_case_id``, ...) joined in from the committed
    ``scenarios/support_scenarios.jsonl`` by ``cartwheel.scenario_id``, since
    the scenario file -- not the trace -- is the source of truth for it;
  - a 2D projection (PCA over the same standardized feature vector
    ``analysis/helpers/selection.py`` clusters on) for the review app's map
    view, plus the cluster assignment from that same module so "cluster
    representative" sampling and the map view agree with each other.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "traces.json"
SUPPORT_SCENARIOS_PATH = REPO_ROOT / "scenarios" / "support_scenarios.jsonl"
OFFLINE_EXPORT_PATH = REPO_ROOT / "traces" / "support_traces.json"

SCENARIO_FIELDS = (
    "scenario_group",
    "data_quality_case_id",
)
TUPLE_FIELDS = ("intent", "difficulty", "record_state", "applicable_policy", "tools_needed")


def _load_scenario_index() -> dict[str, dict[str, Any]]:
    """id -> the fields worth showing a reviewer, from the committed scenario file."""
    if not SUPPORT_SCENARIOS_PATH.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for line in SUPPORT_SCENARIOS_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        tup = row.get("tuple", {})
        index[row["id"]] = {
            **{k: row.get(k) for k in SCENARIO_FIELDS},
            **{k: tup.get(k) for k in TUPLE_FIELDS},
            "expected": row.get("expected"),
            "opening_message": row.get("opening_message"),
        }
    return index


def _permalink(host: str, project_id: str | None, trace_id: str) -> str | None:
    if not project_id:
        return None
    return f"{host}/project/{project_id}/traces/{trace_id}"


def _fetch_live(limit: int) -> tuple[list[dict[str, Any]], str | None]:
    """Return (raw_traces, offline_reason). offline_reason is None on success."""
    from observability.instrument import load_env

    load_env()
    from analysis.helpers import langfuse_io

    if not langfuse_io.is_configured():
        return [], "LANGFUSE_* env not set"
    try:
        from langfuse import Langfuse

        lf = Langfuse()
        project_id = lf.api.projects.get().data[0].id
        host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
        raw = langfuse_io.fetch_traces(limit=limit)
        for t in raw:
            if not t.get("permalink"):
                t["permalink"] = _permalink(host, project_id, t.get("id") or t.get("trace_id"))
        return raw, None
    except Exception as exc:  # noqa: BLE001 - any network/config failure -> offline fallback
        return [], f"live Langfuse fetch failed: {exc}"


def _fetch_offline() -> list[dict[str, Any]]:
    if not OFFLINE_EXPORT_PATH.exists():
        return []
    data = json.loads(OFFLINE_EXPORT_PATH.read_text())
    return data.get("traces", data if isinstance(data, list) else [])


def _project_2d(vectors: list[list[float]]) -> list[tuple[float, float]]:
    """PCA to 2 components. Falls back to zeros for <2 traces or degenerate input."""
    if len(vectors) < 2:
        return [(0.0, 0.0) for _ in vectors]
    import numpy as np
    from sklearn.decomposition import PCA

    arr = np.array(vectors, dtype=float)
    if arr.shape[1] < 2:
        arr = np.pad(arr, ((0, 0), (0, 2 - arr.shape[1])))
    n_components = min(2, arr.shape[0], arr.shape[1])
    coords = PCA(n_components=n_components, random_state=7).fit_transform(arr)
    if n_components == 1:
        coords = np.pad(coords, ((0, 0), (0, 1)))
    return [(float(x), float(y)) for x, y in coords]


def build_pool(limit: int = 1000, force_offline: bool = False) -> dict[str, Any]:
    """Fetch, normalize, join, and cluster the trace pool. Returns the cache document."""
    from analysis.helpers.normalization import normalize_traces
    from analysis.helpers.selection import _feature_vector, _kmeans, _standardize

    offline_reason = None
    if force_offline:
        raw = _fetch_offline()
        offline_reason = "forced offline (force_offline=True)"
    else:
        raw, offline_reason = _fetch_live(limit)
        if not raw:
            raw = _fetch_offline()
            offline_reason = offline_reason or "live fetch returned no traces"

    traces = normalize_traces(raw)
    scenario_index = _load_scenario_index()
    # Restrict to the 250-scenario FINAL run (ids "support-*"). HW3's pilot
    # traces ("pilot-*") share the same Langfuse project but aren't joinable
    # against scenarios/support_scenarios.jsonl, so they'd show no expected-
    # outcome/ground-truth in the review header -- a real degradation, not
    # just a scope-purity concern. Traces with no scenario_id at all (there
    # are none in this project as of this build, but defensively) are kept,
    # since dropping unscoped review targets isn't the goal here.
    traces = [
        t for t in traces
        if not (t.get("meta", {}).get("scenario_id") or "").startswith("pilot-")
    ]
    for t in traces:
        sid = t.get("meta", {}).get("scenario_id")
        extra = scenario_index.get(sid, {})
        t["scenario"] = extra
        t["meta"] = {**t.get("meta", {}), **{k: v for k, v in extra.items() if k in SCENARIO_FIELDS + TUPLE_FIELDS}}

    vectors = _standardize([_feature_vector(t) for t in traces])
    k = max(1, min(8, len(traces) // 8 or 1))
    clusters = _kmeans(vectors, k=k, seed=7) if traces else []
    coords = _project_2d(vectors) if traces else []
    graph_nodes = [
        {
            "trace_id": t["id"],
            "cluster": clusters[i] if i < len(clusters) else 0,
            "x": coords[i][0] if i < len(coords) else 0.0,
            "y": coords[i][1] if i < len(coords) else 0.0,
        }
        for i, t in enumerate(traces)
    ]

    return {
        "traces": traces,
        "graph": {"nodes": graph_nodes, "clusters": sorted(set(clusters))},
        "offline_reason": offline_reason,
        "count": len(traces),
    }


def load_pool(refresh: bool = False, limit: int = 1000) -> dict[str, Any]:
    """Return the cached pool, building (and caching) it if absent or refresh=True."""
    if not refresh and CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    pool = build_pool(limit=limit)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(pool, indent=2, default=str))
    return pool


if __name__ == "__main__":
    pool = load_pool(refresh=True)
    print(f"pool: {pool['count']} traces, offline_reason={pool['offline_reason']!r}")
