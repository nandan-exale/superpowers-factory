# Plugin subfolder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the plugin's files into `plugin/` so Anthropic's directory submits and users install only what the plugin runs, with development files left at the repo root.

**Architecture:** A `git mv` of the plugin's folders into `plugin/`, then path prefixes in the repo-side scripts and tests. Runtime code finds its files relative to itself and doesn't change. `scripts/known-hashes` learns to follow the rename so the hash history survives. A new `plugin-folder` check in `scripts/check` keeps dev files and directory-blocking files out of `plugin/`.

**Tech Stack:** Python 3.10+ standard library, git, `unittest`, `claude plugin validate`.

**Spec:** `docs/superpowers/specs/2026-11-15-plugin-subfolder-design.md`

---

## Before you start

- Work interactively, not as a factory job: the installed factory's files
  (`factory/`, `.claude/`) are protected and this change leaves some of them
  stale (Task 6 is the human follow-up).
- The working tree must be clean. The publishing fixes (`SECURITY.md`,
  `.claude-plugin/icon.png`, the `plugin.json` links, README sections) must be
  committed first; this plan moves those files.
- Branch: `git switch -c refactor/plugin-subfolder` from the branch that holds
  those fixes.
- Record the current vendor hash; Task 1 compares against it:

```bash
python3 -c "import sys; sys.path.insert(0, 'bin'); import factory_files as f; print(f.vendor_hash())" > /tmp/vendor-hash-before
cat /tmp/vendor-hash-before
```

## File map

| Path | Change |
|---|---|
| `.claude-plugin/plugin.json`, `.claude-plugin/icon.png` | move to `plugin/.claude-plugin/` |
| `skills/`, `hooks/`, `bin/`, `vendor/` | move to `plugin/` |
| `assets/` | move to `plugin/assets/` (Task 4, with the README) |
| `LICENSE` | stays; copied to `plugin/LICENSE` |
| `.claude-plugin/marketplace.json` | stays; `source` becomes `./plugin` |
| `scripts/check` | `plugin/` paths (Task 1); new `plugin-folder` check (Task 3) |
| `scripts/known-hashes` | `plugin/` paths and `git log --follow` (Task 1) |
| `scripts/release`, `scripts/e2e`, `scripts/eval` | `plugin/` paths (Task 1) |
| `tests/*.py` | `plugin/` paths (Task 1); new tests (Tasks 1, 3) |
| `plugin/skills/factory-{install,update,uninstall}/SKILL.md` | clone fallback (Task 2) |
| `plugin/vendor/factory/NOTICE` | name the import commit (Task 2) |
| `README.md` → `plugin/README.md`; new short `README.md` | Task 4 |
| `AGENTS.md` | `plugin/` paths (Task 4) |

---

### Task 1: Move the files and fix every path

**Files:**
- Move: `.claude-plugin/plugin.json`, `.claude-plugin/icon.png`, `skills/`, `hooks/`, `bin/`, `vendor/` → `plugin/`
- Create: `plugin/LICENSE` (copy)
- Modify: `.claude-plugin/marketplace.json`, `scripts/check`, `scripts/known-hashes`, `scripts/release`, `scripts/e2e`, `scripts/eval`, `tests/*.py`
- Test: `tests/test_known_hashes.py`

- [ ] **Step 1: Write the failing test for history across the move**

Add to `KnownHashesFileTest` in `tests/test_known_hashes.py`:

```python
    @unittest.skipIf(shallow(), "needs full git history")
    def test_generated_list_matches_the_committed_one(self):
        """Regenerating from git history gives the committed list: no version is lost to a rename."""
        res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(REPO), "--stdout"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout), json.loads(KNOWN.read_text()))
```

and, below `SCRIPT = ...`, the constant it uses (Step 6 points it at `plugin/`):

```python
KNOWN = REPO / "vendor/known-hashes.json"
```

In `scripts/known-hashes`, give `main` a `--stdout` flag that prints the
generated list instead of writing it. Replace `main` with:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--stdout", action="store_true", help="print the list instead of writing it")
    opts = parser.parse_args(argv)
    root = opts.root.resolve()
    if opts.check:
        problems = missing(root)
        for problem in problems:
            print(problem)
        return 1 if problems else 0
    text = json.dumps(generate(root), indent=2, sort_keys=True) + "\n"
    if opts.stdout:
        sys.stdout.write(text)
        return 0
    (root / OUT).write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0
```

- [ ] **Step 2: Run it before the move; it passes**

Run: `python3 -m unittest tests.test_known_hashes -v`
Expected: PASS (nothing has moved yet). Commit nothing yet. This test is the
guard for the move: after Step 3, with the old `git log` (no `--follow`), it
fails because every version committed before the move drops out of the list.
Step 6 makes it pass again.

- [ ] **Step 3: Move the files**

```bash
mkdir -p plugin/.claude-plugin
git mv .claude-plugin/plugin.json plugin/.claude-plugin/plugin.json
git mv .claude-plugin/icon.png plugin/.claude-plugin/icon.png
git mv skills hooks bin vendor plugin/
cp LICENSE plugin/LICENSE
git add plugin/LICENSE
```

In `.claude-plugin/marketplace.json`, change `"source": "./"` to
`"source": "./plugin"`.

- [ ] **Step 4: Rewrite the test and script paths**

Save this one-off script outside the repo (it is not committed) and run it
from the repo root:

```python
# /tmp/prefix_paths.py
import re
from pathlib import Path

ANCHORED = [
    # REPO / "vendor" ...  ->  REPO / "plugin" / "vendor" ...
    (re.compile(r'\b(PLUGIN|REPO|ROOT) / "(vendor|skills|bin|hooks)"'), r'\1 / "plugin" / "\2"'),
    # REPO / "vendor/..."  ->  REPO / "plugin/vendor/..."
    (re.compile(r'\b(PLUGIN|REPO|ROOT) / "(vendor|skills|bin|hooks)/'), r'\1 / "plugin/\2/'),
    # parents[1] / "vendor/..."  ->  parents[1] / "plugin/vendor/..."
    (re.compile(r'parents\[1\] / "(vendor|skills)'), r'parents[1] / "plugin/\1'),
]
files = sorted(Path("tests").glob("*.py")) + [Path("scripts/e2e"), Path("scripts/eval")]
for path in files:
    text = path.read_text(encoding="utf-8")
    new = text
    for pattern, repl in ANCHORED:
        new = pattern.sub(repl, new)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print("rewrote", path)
```

Run: `python3 /tmp/prefix_paths.py`
Expected: about 40 files listed, including `tests/factory_project.py`,
`tests/installed_project.py`, `tests/test_loop.py`, `scripts/e2e`,
`scripts/eval`.

Check nothing outside the plugin was prefixed:

Run: `git diff -U0 -- tests scripts | grep '^+' | grep -E '"plugin" / "(tests|e2e)|plugin/tests'`
Expected: no output.

- [ ] **Step 5: Fix the tests that use root-relative strings**

`tests/test_check.py` edits files in a copy of the repo by root-relative
string and expects `scripts/check` to report them the same way. Prefix every
such string:

```bash
python3 - <<'EOF'
from pathlib import Path
p = Path("tests/test_check.py")
t = p.read_text()
t = t.replace('"vendor/', '"plugin/vendor/').replace('"skills/', '"plugin/skills/')
p.write_text(t)
EOF
```

`tests/test_known_hashes.py`, `CheckModeTest`: the copy must hold the new
layout. Replace the body of `setUp` and the two path literals:

```python
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(REPO / "plugin" / "vendor", self.root / "plugin" / "vendor")
```

```python
    def test_check_fails_when_a_vendored_file_changed(self):
        path = self.root / "plugin/vendor/factory/factory/bin/gate"
```

```python
    def test_check_fails_when_the_list_is_missing(self):
        (self.root / "plugin/vendor/known-hashes.json").unlink()
```

and `KNOWN = REPO / "plugin/vendor/known-hashes.json"`.

`tests/test_release.py`: the fake repo must have the new layout. Change the
constants and `setUp`:

```python
MARKET = '{\n  "name": "p",\n  "plugins": [ { "name": "p", "version": "0.2.0", "source": "./plugin" } ]\n}\n'
HASHES_STUB = ("import pathlib\npathlib.Path('plugin/vendor').mkdir(parents=True, exist_ok=True)\n"
               "pathlib.Path('plugin/vendor/known-hashes.json').write_text('{}\\n')\n")
```

```python
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / "plugin/.claude-plugin").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        (self.root / "plugin/.claude-plugin/plugin.json").write_text(PLUGIN)
        (self.root / ".claude-plugin/marketplace.json").write_text(MARKET)
```

and the two reads at lines 64 and 110: `self.root / "plugin/.claude-plugin/plugin.json"`.

- [ ] **Step 6: Point the scripts at `plugin/`**

`scripts/check`:

```python
FACTORY = Path("plugin/vendor/factory/factory")
JSON_FILES = (
    ".claude/settings.json",
    "plugin/.claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "plugin/vendor/factory/factory/config.json",
    "plugin/hooks/hooks.json",
)
```

```python
def check_license(root, opts):
    problems = []
    for rel in ("LICENSE", "plugin/LICENSE", "plugin/vendor/factory/NOTICE",
                "plugin/skills/agents-best-practices/LICENSE",
                "plugin/skills/agents-best-practices/SOURCE"):
```

In `check_json`: `plugin = json.loads((root / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))`.

```python
FRONTMATTER_GLOBS = (
    "plugin/skills/*/SKILL.md",
    "plugin/vendor/factory/.claude/skills/*/SKILL.md",
    "plugin/vendor/factory/factory/agents/*.md",
)
```

In `check_compile`:

```python
    for rel in ("plugin/bin/factory_files.py", "plugin/bin/factory-manifest", "plugin/bin/factory-state",
                "plugin/bin/factory-update-plan", "plugin/bin/factory-uninstall-settings",
                "plugin/hooks/factory-session.py",
                "scripts/known-hashes", "scripts/release", "scripts/e2e", "scripts/eval"):
```

`scripts/release`:

```python
PLUGIN_JSON = Path("plugin/.claude-plugin/plugin.json")
HASHES = Path("plugin/vendor/known-hashes.json")
```

`scripts/known-hashes`: paths, and follow the rename so history from before
the move is kept:

```python
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "bin"))

from factory_files import FILES, RETIRED  # noqa: E402

VENDOR = "plugin/vendor/factory"
OUT = Path("plugin/vendor/known-hashes.json")
```

```python
def versions(root, rel):
    """Sorted hashes of every committed version of plugin/vendor/factory/<rel>, plus the working copy.

    --follow keeps versions committed before the file moved (it lived in vendor/factory/ until
    the plugin moved into plugin/); --name-only gives the path each commit had it at."""
    path = f"{VENDOR}/{rel}"
    log = subprocess.run(["git", "log", "--follow", "--format=%x00%H", "--name-only", "--", path],
                         cwd=root, capture_output=True, text=True, check=True)
    hashes = set()
    for entry in log.stdout.split("\0")[1:]:
        fields = entry.split()
        if len(fields) < 2:
            continue
        commit, name = fields[0], fields[1]
        blob = subprocess.run(["git", "show", f"{commit}:{name}"], cwd=root, capture_output=True)
        if blob.returncode == 0:  # a commit that deleted the file has no blob
            hashes.add(sha(blob.stdout))
    current = root / path
    if current.is_file():
        hashes.add(sha(current.read_bytes()))
    return sorted(hashes)
```

In `missing`: `if sha((root / VENDOR / rel).read_bytes()) not in data.get(rel, []):`.
Update the module docstring's first line to name `plugin/vendor/known-hashes.json`.

- [ ] **Step 7: Run the checks**

Run: `scripts/check`
Expected: every line `PASS`, including `hashes` and `tests`.
If a test fails on a path, it is one the rewrite in Step 4 missed: fix it by
adding the `plugin/` prefix to that path and rerun.

Run: `python3 -m unittest tests.test_known_hashes -v`
Expected: PASS, including `test_generated_list_matches_the_committed_one`.

Run: `scripts/known-hashes && git diff --exit-code plugin/vendor/known-hashes.json`
Expected: exit 0, no diff (history survives the move).

Run: `python3 -c "import sys; sys.path.insert(0, 'plugin/bin'); import factory_files as f; print(f.vendor_hash())" | diff - /tmp/vendor-hash-before`
Expected: no output.

Run: `claude plugin validate plugin && claude plugin validate .`
Expected: both end `✔ Validation passed` (warnings allowed for `.`). The
`plugin` run must not mention `CLAUDE.md`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move the plugin into plugin/"
```

---

### Task 2: Clone fallback and NOTICE

**Files:**
- Modify: `plugin/skills/factory-install/SKILL.md`, `plugin/skills/factory-update/SKILL.md`, `plugin/skills/factory-uninstall/SKILL.md`, `plugin/vendor/factory/NOTICE`, `plugin/vendor/known-hashes.json`
- Test: `tests/test_any_agent_wording.py`

- [ ] **Step 1: Write the failing test**

Add to the test class in `tests/test_any_agent_wording.py`:

```python
    def test_clone_fallback_handles_both_layouts(self):
        for text in (INSTALL, UPDATE, UNINSTALL):
            self.assertIn('if [ -d "$CLONE/plugin" ]; then PLUGIN="$CLONE/plugin"; else PLUGIN="$CLONE"; fi',
                          text)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_any_agent_wording -v`
Expected: FAIL in `test_clone_fallback_handles_both_layouts`.

- [ ] **Step 3: Update the three skills**

In each of the three `SKILL.md` files, replace:

```bash
  PLUGIN=$(mktemp -d)/superpowers-factory
  git clone --depth 1 --branch "$TAG" https://github.com/nandan-exale/superpowers-factory "$PLUGIN"
fi
```

with:

```bash
  CLONE=$(mktemp -d)/superpowers-factory
  git clone --depth 1 --branch "$TAG" https://github.com/nandan-exale/superpowers-factory "$CLONE"
  if [ -d "$CLONE/plugin" ]; then PLUGIN="$CLONE/plugin"; else PLUGIN="$CLONE"; fi
fi
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest tests.test_any_agent_wording -v`
Expected: PASS.

- [ ] **Step 5: Commit the skills**

```bash
git add plugin/skills tests/test_any_agent_wording.py
git commit -m "fix: find the plugin in a clone of either layout"
```

- [ ] **Step 6: Update NOTICE (a vendored edit, its own commit)**

Replace the last paragraph of `plugin/vendor/factory/NOTICE` so the file reads:

```text
This directory is a modified version of software licensed under the GNU
General Public License, version 3 (see ../../LICENSE). It is distributed under
the same license.

Modified by Nandan Thakur, starting 2026-11-12. Commit 3a0b6bd is the
unmodified import (then at vendor/factory/); every later commit touching
these files is a modification. `git log --follow` on a file shows both.
```

`../../LICENSE` still resolves: from `plugin/vendor/factory/` it is
`plugin/LICENSE`.

- [ ] **Step 7: Refresh hashes, check, commit**

Run: `scripts/known-hashes && scripts/check --fast`
Expected: every line `PASS`.

```bash
git add plugin/vendor/factory/NOTICE plugin/vendor/known-hashes.json
git commit -m "chore: name the factory import commit in NOTICE"
```

---

### Task 3: The `plugin-folder` check

**Files:**
- Modify: `scripts/check`
- Test: `tests/test_check.py`

- [ ] **Step 1: Write the failing tests**

Add to `CheckTest` in `tests/test_check.py`:

```python
    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def add(self, rel, data):
        self.write(rel, data)
        git(self.root, "add", "--", rel)

    def test_clean_copy_passes_plugin_folder(self):
        code, out = self.run_check()
        self.assertIn("PASS plugin-folder", out)

    def test_too_many_plugin_files_fail(self):
        for i in range(400):
            self.write(f"plugin/skills/agents-best-practices/references/pad-{i}.md", b"x\n")
        git(self.root, "add", "-A")
        self.assertFails("plugin-folder", "files; the directory holds a plugin over 512")

    def test_large_text_file_fails(self):
        self.add("plugin/big.md", b"x" * (256 * 1024 + 1))
        self.assertFails("plugin-folder", "plugin/big.md: 262145 bytes")

    def test_large_image_passes(self):
        self.add("plugin/assets/big.png", b"\x89PNG" + b"x" * (256 * 1024))
        code, out = self.run_check()
        self.assertIn("PASS plugin-folder", out)

    def test_os_junk_file_fails(self):
        self.add("plugin/skills/.DS_Store", b"\0")
        self.assertFails("plugin-folder", "plugin/skills/.DS_Store: OS system file")

    def test_dev_file_in_plugin_fails(self):
        self.add("plugin/CLAUDE.md", b"@AGENTS.md\n")
        self.assertFails("plugin-folder", "plugin/CLAUDE.md: development file")

    def test_dev_folder_in_plugin_fails(self):
        self.add("plugin/tests/test_x.py", b"\n")
        self.assertFails("plugin-folder", "plugin/tests: development file")

    def test_key_shaped_string_fails(self):
        self.add("plugin/skills/factory-install/example.md", b'KEY = "sk-' + b"a1" * 10 + b'"\n')
        self.assertFails("plugin-folder", "example.md: looks like an API key")

    def test_license_copy_must_match(self):
        self.edit("plugin/LICENSE", lambda text: text + "\nextra\n")
        self.assertFails("plugin-folder", "plugin/LICENSE differs from LICENSE")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest tests.test_check -k plugin -k large -k junk -k dev_ -k key_shaped -k license_copy -v`
Expected: FAIL; the output has no `plugin-folder` lines.

- [ ] **Step 3: Implement the check**

In `scripts/check`, after `check_branding`, add:

```python
PLUGIN_DIR = "plugin"
MAX_PLUGIN_FILES = 400  # the directory holds a plugin over 512 files for review
MAX_TEXT_BYTES = 256 * 1024  # and any file over 256 KiB that isn't an image or font
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
OS_JUNK = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX"})
DEV_ONLY = ("CLAUDE.md", "tests", "docs", "scripts")
KEY_SHAPED = re.compile(rb"sk-[A-Za-z0-9-]{16,}")


def check_plugin_folder(root, opts):
    """What the directory installs: keep it small, readable and free of dev files."""
    files = [rel for rel in tracked_files(root) if rel.startswith(f"{PLUGIN_DIR}/")]
    problems = []
    if len(files) > MAX_PLUGIN_FILES:
        problems.append(f"{PLUGIN_DIR}/ holds {len(files)} files; the directory holds a plugin over 512 "
                        f"for review (this check stops at {MAX_PLUGIN_FILES})")
    for name in DEV_ONLY:
        top = f"{PLUGIN_DIR}/{name}"
        if any(rel == top or rel.startswith(f"{top}/") for rel in files):
            problems.append(f"{top}: development file in the installed folder; keep it at the repo root")
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        if OS_JUNK & set(Path(rel).parts):
            problems.append(f"{rel}: OS system file; the directory refuses it")
            continue
        data = path.read_bytes()
        if path.suffix.lower() not in IMAGE_SUFFIXES and len(data) > MAX_TEXT_BYTES:
            problems.append(f"{rel}: {len(data)} bytes; the directory holds files over 256 KiB for review")
        if KEY_SHAPED.search(data):
            problems.append(f"{rel}: looks like an API key (sk-...); the directory's secret scan blocks it")
    copy, original = root / PLUGIN_DIR / "LICENSE", root / "LICENSE"
    if copy.is_file() and original.is_file() and copy.read_bytes() != original.read_bytes():
        problems.append(f"{PLUGIN_DIR}/LICENSE differs from LICENSE; copy it again")
    return problems
```

Add it to `CHECKS`, before `tests`:

```python
    ("external-binaries", check_external_binaries),
    ("plugin-folder", check_plugin_folder),
    ("tests", check_tests),
```

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m unittest tests.test_check -v`
Expected: PASS, every test.

Run: `scripts/check`
Expected: every line `PASS`, including `PASS plugin-folder`.

- [ ] **Step 5: Commit**

```bash
git add scripts/check tests/test_check.py
git commit -m "test: check the plugin folder stays installable"
```

---

### Task 4: Split the README; update AGENTS.md

**Files:**
- Move: `README.md` → `plugin/README.md`; `assets/` → `plugin/assets/`
- Create: `README.md` (short)
- Modify: `plugin/README.md`, `AGENTS.md`

- [ ] **Step 1: Move the README and its image**

```bash
git mv README.md plugin/README.md
git mv assets plugin/assets
```

The banner link `assets/banner.svg` in `plugin/README.md` still resolves.

- [ ] **Step 2: Take the contributor section out of `plugin/README.md`**

Cut from `plugin/README.md` the whole `## Contributing and license` section,
from that heading to the end of the file (it ends with "Licensed under
**GPLv3** ..."), and remove its line from `## Contents`. Keep the
`### Proving changes with real agents` subsection's text for Step 3.

In `plugin/README.md`, `## Support and security`, replace the `SECURITY.md`
line with an absolute link, since the installed folder has no `SECURITY.md`:

```markdown
- **Security problems:** report them privately; see
  <https://github.com/nandan-exale/superpowers-factory/security/policy>.
```

Add at the end of `plugin/README.md`:

```markdown
---

## License

GPL-3.0-only (see `LICENSE`). The factory in `vendor/factory/` is a modified
version of GPLv3 software (see `vendor/factory/NOTICE`); the bundled
`agents-best-practices` skill is MIT (see its `LICENSE` and `SOURCE`).
Contributing: <https://github.com/nandan-exale/superpowers-factory#contributing>.
```

- [ ] **Step 3: Write the short root README**

Create `README.md` with exactly this content (outer fence shown as `~~~`):

~~~markdown
# superpowers-factory

![superpowers-factory: design with Superpowers, then the factory builds, gates, reviews and ships each plan as one PR](plugin/assets/banner.svg)

**You design the feature with Claude. The factory builds it.** A Claude Code
plugin: you brainstorm and plan with the Superpowers skills, the plan becomes
one GitHub issue, and an unattended factory of agents builds, checks, reviews
and ships it as one pull request.

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

Working on the plugin itself? Read `AGENTS.md` and run `scripts/check` before
calling a change done; CI runs the same script.

- `plugin/`: everything users install, and the folder submitted to
  Anthropic's directory. Keep development files out of it.
- `plugin/skills/`: the plugin's skills (`factory-install`, `factory-update`,
  `factory-handoff`, `factory-uninstall`, and the bundled
  `agents-best-practices`, MIT-licensed, vendored with the modifications
  listed in its `SOURCE`).
- `plugin/bin/`, `plugin/hooks/`: the plugin's session hook and update scripts.
- `plugin/vendor/factory/`: the factory copied into projects. Commit 3a0b6bd is
  the unmodified import; every later commit is a modification (see
  `plugin/vendor/factory/NOTICE`).
- `tests/`, `scripts/`, `docs/`: tests, maintainer tools, specs and plans.

### Proving changes with real agents

<paste the "### Proving changes with real agents" subsection from
plugin/README.md here unchanged, from "Two maintainer tools spend real money"
through the paragraph ending "is skipped without it.">
~~~

The one angle-bracket line is an instruction: replace it with that
subsection's text, which Step 2 cut from `plugin/README.md`. It holds two
`bash` blocks and needs no path changes.

- [ ] **Step 4: Update `AGENTS.md`**

In `## Map` and `## Workflow`, give every plugin path the `plugin/` prefix:

- `skills/factory-install`, `skills/factory-handoff` → `plugin/skills/...`
- `vendor/factory/` → `plugin/vendor/factory/` (every occurrence, including
  the Software factory section)
- `vendor/known-hashes.json` → `plugin/vendor/known-hashes.json`
- `bin/factory-uninstall-settings` → `plugin/bin/factory-uninstall-settings`
- `skills/factory-uninstall/` → `plugin/skills/factory-uninstall/`

Add one line at the top of `## Map`:

```markdown
- `plugin/`: everything users install, and the folder submitted to Anthropic's
  directory. Development files (`tests/`, `scripts/`, `docs/`) stay outside it;
  `scripts/check`'s `plugin-folder` check enforces that.
```

In `## Invariants`, change "Keep `LICENSE` (GPLv3) and `vendor/factory/NOTICE`"
to "Keep `LICENSE` (GPLv3, copied to `plugin/LICENSE`) and
`plugin/vendor/factory/NOTICE`".

Run: `git grep -nE '(^|[^/])\b(vendor/factory|skills/factory|bin/factory)' -- AGENTS.md README.md`
Expected: every hit already has `plugin/` in front.

- [ ] **Step 5: Check and commit**

Run: `scripts/check && claude plugin validate plugin`
Expected: every line `PASS`; validation ends `✔ Validation passed` with no
README or license warning.

```bash
git add -A
git commit -m "docs: split the README for the plugin folder"
```

---

### Task 5: Final verification

- [ ] **Step 1: Count and validate**

Run: `git ls-files plugin | wc -l`
Expected: under 120.

Run: `claude plugin validate plugin; claude plugin validate .`
Expected: `plugin` passes with no `CLAUDE.md` warning; `.` passes.

Run: `scripts/check`
Expected: every line `PASS`.

- [ ] **Step 2: Install from the local marketplace**

In a scratch Claude Code session:

```text
/plugin marketplace add /Users/nandanthakur/projects/superpowers-factory
/plugin install superpowers-factory@superpowers-factory
```

Open a new session in a GitHub-backed project without the factory.
Expected: Claude offers `/factory-install` (the session hook ran from
`plugin/hooks/`). Remove the scratch marketplace afterwards with
`/plugin marketplace remove superpowers-factory`.

---

### Task 6: After merge (human only)

These touch protected files or need a release; a factory job can't do them.

- [ ] Edit the installed factory's project adaptations to the new paths:
  `factory/agents/intake.md` (line 29), `factory/agents/approver.md` (line 63),
  `factory/agents/reviewer-security.md` (lines 50 and 52): `vendor/factory/` →
  `plugin/vendor/factory/`. Then run `factory/bin/doctor`.
- [ ] Release (`scripts/release X.Y.Z`), push, then run
  `/plugin marketplace update superpowers-factory` in your own Claude Code and
  confirm the session hook still fires.
- [ ] In the developer portal, delete the existing draft submission (it is for
  the repo root, and a submission's repository and folder can't change), then
  **Submit new** with plugin path `plugin`. The new submission also reads
  `plugin/.claude-plugin/icon.png`; the old draft was saved before the icon
  existed, and the directory takes the icon only at a submission's first save.
- [ ] Check `npx skills add nandan-exale/superpowers-factory` finds the four
  skills under `plugin/skills/`. If it doesn't, change that command in
  `plugin/README.md` to `npx skills add nandan-exale/superpowers-factory/plugin`.
