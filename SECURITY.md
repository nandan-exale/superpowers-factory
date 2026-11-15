# Security

## Reporting a problem

Please report security problems privately, not in a public issue: on the
repository's **Security** tab, choose **Report a vulnerability**
(<https://github.com/nandan-exale/superpowers-factory/security/advisories/new>).

Say what you found, how to reproduce it, and which version of the plugin
(`version` in `.claude-plugin/plugin.json`) you used. You should get a reply
within a week.

## What counts

Anything that lets a factory job do more than the README's "What the plugin
runs, writes and sends" section says: reading a credential, escaping the job's
worktree, weakening `factory/checks.sh` or `factory/runner-settings.json`, or
merging without the checks and reviews.

Only the latest release is supported.
