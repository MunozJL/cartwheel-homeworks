# Homework 4 reference review summary

This reference bundle provides the Homework 4 evidence needed to begin Homework 5. It uses the 100 traces from `homework/module-2/hw3-reference.patch`.

## Reviewed sample

The sample contains 100 traces. The review covered order lookup, refunds, cancellations, policy questions, product search, and out of scope requests. The saved label file contains one decision for every trace for the final mode below.

## Final mode

`uninformative_response` asks whether the final reply gives the information the user needs for the next decision without burying it in unnecessary detail. The mode maps to RESP-3 and requires an LLM judge because the correct amount of detail depends on the request.

The boundary changed during review. The first draft treated every short reply as uninformative. Trace `13bc170360f221fe75c16853971b4c0f` is a close negative because the user explicitly asked for yes or no. The final definition judges the reply against the requested level of detail.

The review found 31 traces with the failure and 69 without it. The label file uses the Homework 4 convention: 1 means the failure is present and 0 means it is absent. Homework 5 converts these to Pass and Fail labels before splitting the data.

No new consequential mode appeared in the final 15 traces. This compact reference bundle keeps one mode because Homework 5 requires one judge.
