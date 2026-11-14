Recorded with `opencode v2.3.0` on 2026-11-14, model `google/gemini-3.5-flash-lite`, by Task 1 of
docs/superpowers/plans/2026-11-14-phase6b-other-runtimes.md.
Exit codes: result 0; resumed 0; error 1.
OUTPUT: json lines (`--format json`): step_start, text, step_finish per step; `{"type":"error",...}` on failure
SESSION: sessionID on every event. NOTE: `--session <id>` creates a session that doesn't exist, so a lost
  session is not an error: the agent silently starts without its earlier conversation.
COST: part.cost on step_finish (dollars)
TOKENS: part.tokens on step_finish: input, output, reasoning, cache.read, cache.write
FLAG: effort is a model variant (`-m provider/model#variant`); no separate effort flag.
error.out is a run with model `google/no-such-model-xyz` (exit 1, one error event), recorded separately
because an unknown --session id isn't an error.
