# superpowers-factory

![superpowers-factory: design with Superpowers, then the factory builds, gates, reviews and ships each plan as one PR](plugin/assets/banner.svg)

**You design the feature with Claude. The factory builds it.** A Claude Code
plugin: you brainstorm and plan with the Superpowers skills, the plan becomes
one GitHub issue, and an unattended factory of agents builds, checks, reviews
and ships it as one pull request. Specs and plans from any other planning tool
work too, and so does any plain issue labeled `factory`.

```text
/plugin marketplace add nandan-exale/superpowers-factory
/plugin install superpowers-factory@superpowers-factory
```

**The full guide is [`plugin/README.md`](plugin/README.md)**: how it works,
setup, configuration, what it runs and sends, and troubleshooting.

- Changes: [`CHANGELOG.md`](CHANGELOG.md)
- Security: [`SECURITY.md`](SECURITY.md)
- License: GPL-3.0-only ([`LICENSE`](LICENSE)), because
  `plugin/vendor/factory/` is a modified copy of GPLv3-licensed code.

## Contributing

Working on the plugin itself? Read [`AGENTS.md`](AGENTS.md) and run
`scripts/check` before calling a change done; CI runs the same script.

- `plugin/`: everything users install, and the folder submitted to
  Anthropic's directory. Keep development files out of it.
- `plugin/skills/`: the plugin's skills (`factory-install`, `factory-update`,
  `factory-handoff`, `factory-uninstall`, and the bundled
  `agents-best-practices`, MIT-licensed, vendored with the modifications
  listed in its `SOURCE`).
- `plugin/tools/`, `plugin/hooks/`: the plugin's session hook and update scripts.
- `plugin/vendor/factory/`: the factory copied into projects. Commit 3a0b6bd is
  the unmodified import; every later commit is a modification (see
  `plugin/vendor/factory/NOTICE`).
- `tests/`, `scripts/`, `docs/`: tests, maintainer tools, specs and plans.

### Proving changes with real agents

Two maintainer tools spend real money, so they never run in CI. Run them by hand
before a release that changes agent prompts or the job state machine.

**Prompt evals** run each agent prompt against small fixtures in `tests/evals/`
and compare pass rates with `tests/evals/baseline.json`:

```bash
scripts/eval --samples 3 --max-usd 5
```

Add `--agent reviewer-code` to run one agent. A case fails when its pass rate
falls more than one sample below its baseline. After a prompt change you mean,
run with `--update-baseline` and review the diff before committing it.

**End-to-end scenarios** run the whole factory on a disposable GitHub repo.
Make the sandbox once: a new private repo whose name contains `e2e` or
`sandbox` (for example `factory-e2e`), holding a tiny Python CLI (`app.py`
with an argparse entry point, a `VERSION` file and one unittest), with the
factory installed (`/factory-install`) and committed. Then, from this repo:

```bash
scripts/e2e --sandbox ~/src/factory-e2e --max-usd 10
```

`--only <scenario>` runs one, and `--keep` leaves its issue, PR and branch open
for a look. Results are in `e2e-results/<timestamp>/`. The tool refuses
any repo that isn't on github.com, is this plugin's repo, or lacks `e2e` or
`sandbox` in its name. It also refuses a clone whose pushes or `gh` would reach
another repo, and pins every `gh` call it and the factory make to the sandbox
(`GH_REPO`). The `runner-tick` scenario needs the runner's Keychain token and is
skipped without it.
