"""HW5: build and evaluate an LLM judge for the ``uninformative_response``
failure mode, per ``homework/module-2/hw5.md``.

Run functions from the repository root, e.g.:

    uv run python -c "from analysis.run_judges import prepare_inputs; prepare_inputs()"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODE = "uninformative_response"
TRACE_INPUTS_PATH = Path("analysis/state/hw5_trace_inputs.json")
JUDGE_MODEL = "gpt-4o-mini"


def prepare_inputs() -> list[dict[str, Any]]:
    """Export one judge-input record per labeled trace to
    ``analysis/state/hw5_trace_inputs.json``.

    Each record is ``{"trace_id": ..., "trace": [...messages...]}`` --
    ``normalize_trace``'s own message list, which already carries earlier
    turns, ``tool_call``/``tool_result`` messages (including policy lookups),
    and the final reply. Human labels and annotations are deliberately left
    out so the judge never sees the answer.
    """
    from analysis.helpers.langfuse_io import fetch_traces
    from analysis.helpers.normalization import normalize_trace
    from analysis.helpers.tools import _load_labels

    trace_ids = sorted({row["trace_id"] for row in _load_labels(MODE)})

    traces_by_id = {t["id"]: t for t in fetch_traces(limit=1000)}
    missing = [tid for tid in trace_ids if tid not in traces_by_id]
    if missing:
        raise ValueError(f"labeled trace ids missing from Langfuse: {missing[:5]}")

    records = []
    seen_text: dict[str, str] = {}
    for tid in trace_ids:
        normalized = normalize_trace(traces_by_id[tid])
        record = {"trace_id": normalized["trace_id"], "trace": normalized["trace"]}
        text_key = normalized.get("text", "")
        dup_of = seen_text.get(text_key)
        if dup_of:
            print(f"note: {tid} has identical text to {dup_of} (possible duplicate run)")
        else:
            seen_text[text_key] = tid
        records.append(record)

    TRACE_INPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACE_INPUTS_PATH.write_text(json.dumps(records, indent=2))
    print(f"wrote {len(records)} records to {TRACE_INPUTS_PATH}")
    return records


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """Split human labels into train(20%)/dev(40%)/test(40%), restricted to
    trace ids that have a prepared judge-input record."""
    from analysis.helpers import split_labels

    records = json.loads(TRACE_INPUTS_PATH.read_text())
    splits = split_labels(
        mode,
        fractions=(0.20, 0.40, 0.40),
        seed=7,
        min_per_class=10,
        eligible_trace_ids=[record["trace_id"] for record in records],
    )
    for name in ("train", "dev", "test"):
        print(f"{name}: {len(splits[name])} traces")
    return splits


def run_development(mode: str, prompt_path: str) -> dict[str, Any]:
    """Register a judge prompt version and score it on the dev split."""
    from analysis.helpers import judge_alignment, register_judge, run_judge

    record = register_judge(
        mode=mode,
        prompt_text=Path(prompt_path).read_text(),
        judge_model=JUDGE_MODEL,
    )
    judge_id = record["judge_id"]
    run_judge(judge_id, split="dev", batch_size=10)
    development = judge_alignment(judge_id, split="dev")

    report_path = Path(f"analysis/report/dev-{judge_id}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(development, indent=2))
    print(f"judge_id={judge_id}  dev TPR={development['tpr']}  TNR={development['tnr']}")
    return development


def run_test(judge_id: str) -> dict[str, Any]:
    """Freeze the judge's current prompt version and score it once on test."""
    from analysis.helpers import freeze_judge, judge_alignment, run_judge

    freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=10)
    test = judge_alignment(judge_id, split="test")

    report_path = Path(f"analysis/report/test-{judge_id}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(test, indent=2))
    print(f"judge_id={judge_id}  test TPR={test['tpr']}  TNR={test['tnr']}")
    return test
