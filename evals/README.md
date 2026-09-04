# Stateful workflow evals

[Chinese version](README_zh-CN.md)

`stateful-scenarios.json` is a small, model-ready corpus covering the decisions
that matter in a long Blender VSE conversation: positive and negative routing,
targeted reads, token consumption, idempotent retries, manual edits, stale
cursors, checkpoint isolation, access denial, missing tools, and compaction.

`tests/evals/stateful_workflow.py` first replays every expected state transition
through a deterministic oracle. It then runs 250 synthetic edit cycles against
the real bounded-context projectors and resume-capsule builder. The report
compares the bytes consumed by naively accumulated tool results with the maximum
active bytes when the host compacts context every 25 cycles.

`baseline.json` stores the minimum corpus coverage and maximum context-growth
thresholds separately from the observed reference values. For an intentional
protocol change, update the implementation and scenarios first, then update the
baseline after review. Do not relax the baseline merely to make a regression
pass.

The oracle is an executable contract, not a claim that a language model will
always choose the right action. The same prompts can later be run against
candidate models; record selected tools and arguments without changing the
expected scenario file merely to fit one model's output.
