# PR comment follow-ups — Design

Date: 2026-11-12
Status: approved design. The idea: later comments on a work
item reach the agent working on it without a new mention.

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

On the job's PR: conversation comments, inline review comments (with `file:line`, or just the file for a file-level comment), and `COMMENTED` or `CHANGES_REQUESTED` reviews with a body. Skipped:

- comments that start with the factory's marker;
- bots (`user.type == "Bot"`);
- authors not trusted;
- empty bodies;
- `APPROVED` reviews, since merging on GitHub stays the approval, and `DISMISSED` and `PENDING` (unsubmitted) reviews;
- edited comments whose last editor isn't trusted, looked up with one GraphQL call per edited comment. This also stops a collaborator from removing the marker from a factory comment;
- comments already handled, tracked in `job.json` `pr_feedback_seen` as `comment-<id>@<time>`, `inline-<id>@<time>` and `review-<id>@<time>`, where the time is `updated_at`, else `submitted_at`, else `created_at`. A trusted edit after pickup is new again.

Reads use `gh api --paginate --jq '.[]' repos/{owner}/{repo}/…?per_page=100`, which reads every page of each kind.

## `job pr-feedback <job>`

1. If the job has no PR, or is in `intake`, `needs-info`, `spec`, `merged` or `rejected`, it prints `PR-FEEDBACK: none`.
2. New trusted comments go to `feedback-<k>.md` as quoted data (author, kind, `file:line`, link), their keys go into `pr_feedback_seen`, and the file name is appended to `feedback_pending`. The job is saved before any further `gh` call, so a failure there can't write the same comments twice. One factory-marked comment on the PR acknowledges them.
3. If the job is `needs-human` and `feedback_pending` is not empty, it advances to `build`, with a fresh round budget as `job feedback` gives.
4. It prints `PR-FEEDBACK: <file> <file> … (<n> new comments)`, naming every file the coming round must read (`<n>` may be 0 when only earlier files are pending), or `PR-FEEDBACK: none`.

`feedback_pending` is the list of feedback files no build round has had yet. It is emptied when the next build round starts (`next_round`). `job feedback` prints those files after its own, so they reach the builder too.

## Pipeline changes

- `review → approve` refuses while `feedback_pending`. `review → build` is allowed when a review wants CHANGES or `feedback_pending` is set, within the round limit.
- `needs-human → build` accepts `feedback_pending` as well as a newer `feedback-*.md`.
- `job merge` refuses before touching git when `feedback_pending` is set or new trusted comments exist, and checks for new comments again just before `gh pr merge`. Either way it escalates to `needs-human` and says so.
- `job queue` shows a `needs-human` job with pending feedback or new trusted comments as `resume … PR feedback`. A failing `gh` call stops it.
- Orchestrator: `/factory run` runs `pr-feedback` for each such `resume` row, and before every gate-fail rebuild and every end of review. It names every file `pr-feedback` printed in the builder's message, and goes to `build` instead of `approve` when feedback is pending.
- Builder: reads PR-comment feedback files as it reads escalation feedback.

## Config

```json
"pr_feedback": { "allowed": [] }
```

`allowed` must be a list of logins. Anything else is refused.

## Testing

Stdlib `unittest`, faking `gh_api_list` and `gh_json` (GraphQL editor lookups):

- each trust and skip rule, including review states, untrusted edits and file-level inline comments;
- reading past the first page;
- a trusted edit picked up again;
- several pending files named, and the list cleared by the next round;
- no duplicate file when the acknowledgement fails;
- `merge` checking again just before merging;
- the allow-list from config;
- no comment handled twice;
- the quoted file format and the acknowledgement comment;
- `needs-human → build`;
- `review` refusing `approve` and allowing `build` while feedback is pending;
- `merge` blocked by pending feedback and by new comments;
- the queue's `resume` row;
- a bad `allowed` value.
