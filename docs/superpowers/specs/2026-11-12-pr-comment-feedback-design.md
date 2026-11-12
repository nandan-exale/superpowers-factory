# PR comment follow-ups — Design

Date: 2026-11-12
Status: approved design. The idea is borrowed from deepseek-ai/dsh-superagent-prototype, where later
comments on a Thread reach the Ticket's Executor without a new mention.

## Goal

Trusted comments on a factory job's PR reach that job's builder without
`/factory <feedback>`, and the factory never merges past a trusted comment it
hasn't handled.

## Decisions

| Question | Decision |
|---|---|
| Which jobs | Escalated (`needs-human`) and in-flight jobs with a PR. |
| Whose comments | The operator (the `gh` account running the factory) plus `config.json` `pr_feedback.allowed` logins; defaults to the operator only. |

## What counts

On the job's PR: conversation comments, inline review comments (with `file:line`), and reviews with a body. Skipped:

- comments that start with the factory's marker;
- bots (`user.type == "Bot"`);
- authors not trusted;
- empty bodies, which covers plain approve-reviews, since merging on GitHub stays the approval;
- `PENDING` (unsubmitted) reviews;
- comments already handled, tracked by id in `job.json` `pr_feedback_seen` as `comment-<id>`, `inline-<id>` and `review-<id>`.

Reads use `gh api repos/{owner}/{repo}/…?per_page=100`, which reads the newest 100 of each kind.

## `job pr-feedback <job>`

1. If the job has no PR, or is in `intake`, `needs-info`, `spec`, `merged` or `rejected`, it prints `PR-FEEDBACK: none`.
2. New trusted comments go to `feedback-<k>.md` as quoted data (author, kind, `file:line`, link), their ids go into `pr_feedback_seen`, and `feedback_pending` is set to true. One factory-marked comment on the PR acknowledges them.
3. If the job is `needs-human` and `feedback_pending` is true, it advances to `build`, with a fresh round budget as `job feedback` gives.
4. It prints `PR-FEEDBACK: feedback-<k>.md (<n> comments)` for new comments, `PR-FEEDBACK: pending feedback-<k>.md` when an earlier file waits for a round, or `PR-FEEDBACK: none`.

`feedback_pending` is cleared when the next build round starts (`next_round`).

## Pipeline changes

- `review → approve` refuses while `feedback_pending`. `review → build` is allowed when a review wants CHANGES or `feedback_pending` is set, within the round limit.
- `needs-human → build` accepts `feedback_pending` as well as a newer `feedback-*.md`.
- `job merge` refuses before touching git when `feedback_pending` is set or new trusted comments exist. It escalates to `needs-human` and says so.
- `job queue` shows a `needs-human` job with pending feedback or new trusted comments as `resume … PR feedback`.
- Orchestrator: `/factory run` runs `pr-feedback` for each such `resume` row, and before every gate-fail rebuild and every end of review. It names the feedback file in the builder's message, and goes to `build` instead of `approve` when feedback is pending.
- Builder: reads PR-comment feedback files as it reads escalation feedback.

## Config

```json
"pr_feedback": { "allowed": [] }
```

`allowed` must be a list of logins. Anything else is refused.

## Testing

Stdlib `unittest`, faking `gh_json`:

- each trust and skip rule;
- the allow-list from config;
- no comment handled twice;
- the quoted file format and the acknowledgement comment;
- `needs-human → build`;
- `review` refusing `approve` and allowing `build` while feedback is pending;
- `merge` blocked by pending feedback and by new comments;
- the queue's `resume` row;
- a bad `allowed` value.
