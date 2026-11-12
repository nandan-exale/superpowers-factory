"""The vendored factory files /factory-install copies, and hashes over them."""

import hashlib
import os
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR = PLUGIN / "vendor" / "factory"
MANIFEST = "factory/manifest.json"
AGENTS = ("intake", "spec-writer", "builder", "reviewer-code",
          "reviewer-security", "reviewer-ux", "reviewer-ui", "approver")
FILES = (
    ".claude/skills/factory/SKILL.md",
    *(f".claude/agents/{name}.md" for name in AGENTS),
    "factory/config.json",
    "factory/checks.sh",
    "factory/bin/job",
    "factory/bin/gate",
    "factory/bin/route",
    "factory/bin/stop-hook",
    "factory/bin/doctor",
    "factory/bin/runner",
    "factory/runner-settings.json",
    "factory/dashboard.html",
)


def vendor_dir():
    """The vendored factory, or $FACTORY_VENDOR_DIR (tests stand in a changed upstream)."""
    return Path(os.environ.get("FACTORY_VENDOR_DIR") or VENDOR)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vendor_hash(vendor=None):
    """One hash over every vendored file's path and content."""
    vendor = Path(vendor or vendor_dir())
    digest = hashlib.sha256()
    for rel in sorted(FILES):
        digest.update(rel.encode() + b"\0" + (vendor / rel).read_bytes() + b"\0")
    return digest.hexdigest()


def manifest_data(vendor=None):
    vendor = Path(vendor or vendor_dir())
    return {"vendor_hash": vendor_hash(vendor),
            "files": {rel: sha256_file(vendor / rel) for rel in FILES}}
