"""Agent prompts: factory/agents/<role>.md, frontmatter (name, description, access) then the body."""

from pathlib import Path

ACCESS = ("read", "write")


def load(repo, role):
    """{"access": "read" | "write", "body": prompt text}; ValueError for a malformed file."""
    path = Path(repo) / "factory" / "agents" / f"{role}.md"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError(f"{path}: no --- frontmatter block")
    end = lines.index("---", 1)
    meta = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    if meta.get("access") not in ACCESS:
        raise ValueError(f"{path}: access must be read or write, not {meta.get('access')!r}")
    return {"access": meta["access"], "body": "\n".join(lines[end + 1:]).strip() + "\n"}
