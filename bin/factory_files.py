"""The vendored factory files /factory-install copies, and hashes over them."""

import copy
import hashlib
import json
import os
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
VENDOR = PLUGIN / "vendor" / "factory"
MANIFEST = "factory/manifest.json"
KNOWN_HASHES = PLUGIN / "vendor" / "known-hashes.json"
SETTINGS = "factory/runner-settings.json"
AGENTS = ("intake", "spec-writer", "builder", "reviewer-code",
          "reviewer-security", "reviewer-ux", "reviewer-ui", "approver", "learner")
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


def known_hashes():
    """{rel: [sha256, ...]}: every version each vendored file has had, from the plugin's history.
    {} when the list is missing or unreadable. $FACTORY_KNOWN_HASHES points elsewhere (tests)."""
    path = Path(os.environ.get("FACTORY_KNOWN_HASHES") or KNOWN_HASHES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vendor_hash(vendor=None):
    """One hash over every vendored file's path and content."""
    vendor = Path(vendor or vendor_dir())
    digest = hashlib.sha256()
    for rel in sorted(FILES):
        digest.update(rel.encode() + b"\0" + (vendor / rel).read_bytes() + b"\0")
    return digest.hexdigest()


def write_json(path, data, sort_keys=False, indent=2):
    Path(path).write_text(json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def settings_core(data):
    """Hash of runner-settings.json without the network domains a project is expected to add."""
    core = copy.deepcopy(data)
    sandbox = core.get("sandbox") if isinstance(core, dict) else None
    network = sandbox.get("network") if isinstance(sandbox, dict) else None
    if isinstance(network, dict):
        network.pop("allowedDomains", None)
    canonical = json.dumps(core, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def manifest_data(vendor=None):
    vendor = Path(vendor or vendor_dir())
    settings = json.loads((vendor / SETTINGS).read_text(encoding="utf-8"))
    return {"vendor_hash": vendor_hash(vendor),
            "files": {rel: sha256_file(vendor / rel) for rel in FILES},
            "settings_core": settings_core(settings),
            "settings_domains": list(settings["sandbox"]["network"]["allowedDomains"])}
