# Interface comparison (HW4 Part A)

## Standard Langfuse annotation view: friction observed

I could not get the Chrome extension connected to browse Langfuse's standard
annotation view live during this session, so this comparison is grounded in
the raw trace/observation structure returned by
`analysis/helpers/langfuse_io.fetch_traces` and `normalize_trace` (the same
data Langfuse's UI itself renders from), plus the documented layout of that
view, rather than a live click-through. Two structural facts drove the
design below:

- **A Cartwheel trace is one turn, not one conversation.** A shopper's
  three-message exchange is three separate Langfuse trace records that
  happen to share `cartwheel.scenario_id`. The standard view has no notion
  of that relationship, so a followup turn's tool calls appear with no
  visible connection to the first turn's context.
- **Tool calls and the final reply are siblings in one flat `observations`
  list**, ordered by start time, with no visual grouping between a tool
  call, its result, and the reply text that depends on it. A reviewer has
  to hold that connection in their head while scrolling.

## One design retained from the reference (`analysis/ui/index.html`)

The reference's **margin-note annotation mechanic** was kept essentially
unchanged: wrap the selected text in a `pending-highlight` span *before*
focusing the note input (so the browser's native selection-clearing on
focus doesn't lose the reviewer's context), position notes in a right
margin column computed from `getBoundingClientRect` deltas (not
`scrollTop`, which double-counts), and link hover states between a
highlight and its note. This already matched the error-discovery skill's
own design guidance exactly, and reimplementing it would only have
introduced new bugs into logic that was already correct.

## One design changed after inspecting real traces

The reference's trace header rendered three placeholder "extra metadata"
fields (`exp.order`, `exp.store_override`, `exp.data_error`) that don't
exist in our actual scenario data. Real Cartwheel scenarios carry a
richer, differently-shaped `expected` object from
`scenarios/support_scenarios.jsonl` (`evaluation`, `outcome`/`criterion`,
`reason`, `source: {type, reference}`) — a real database value, an
eligibility-function result, or a specification citation, never a model's
own claim about itself. I rewrote the header to render this real shape,
and added `scenario_group`, `intent`, `difficulty`,
`data_quality_case_id`, and a direct permalink to the trace in Langfuse
(joined in by `analysis/review_app/trace_pool.py` from the committed
scenario file, since none of this lives on the trace's own span
attributes). I also added a fourth "Labeling" view for Part D/E's
present/absent grid, which the reference doesn't need because it only
covers open coding (phases 1-5 of the skill), not structured labeling.

I did **not** cut the 2D cluster map view, despite it costing more to
build than the handout strictly requires: once traces are already
clustered for "cluster representative" sampling (Part B), wiring that same
clustering into the existing map-view code was nearly free, and it gives a
visual gut-check on cluster coverage during Part B / Part D's stability
check that a text-only progress view wouldn't provide as immediately.

## One limitation remaining

**Samples are snapshotted, not live-joined.** When a trace is added to
`analysis/state/samples.json` (via seeding or a depth-search push), its
full conversation content, scenario metadata, and permalink are copied in
at that moment. If the underlying Langfuse trace or the scenario file
changed afterward, the sample would go stale until re-seeded. For a fixed
250-scenario, already-completed HW3 run this isn't a practical problem,
but it's a real design tradeoff (simplicity and offline resilience,
against staleness) worth naming rather than leaving implicit.
