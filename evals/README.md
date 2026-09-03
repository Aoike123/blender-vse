# Stateful workflow evals

[Chinese version](README_zh-CN.md)

`stateful-scenarios.json` is a small model-ready corpus for the decisions that
matter in a long Blender VSE conversation: positive and negative routing,
targeted reads, token consumption, idempotent retries, manual edits, stale
cursors, checkpoint isolation, access denial, missing tools, and compaction.

`tests/evals/stateful_workflow.py` first replays every expected state transition
through a deterministic oracle. It then runs 250 synthetic edit cycles against
the real bounded context projectors and resume-capsule builder. The report
compares naive accumulated tool-result bytes with the maximum active bytes when
the host compacts every 25 cycles.

`baseline.json` holds minimum corpus coverage and maximum context-growth
thresholds separately from the observed reference numbers. Intentional protocol
changes update the implementation and scenarios first, then the baseline after
review; do not relax it merely to make a regression pass.

The oracle is an executable contract, not a claim that a language model will
always choose the right action. The same prompts can later be run against
candidate models; record selected tools and arguments without changing the
expected scenario file merely to fit one model's output.
