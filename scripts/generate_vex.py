#!/usr/bin/env python3
"""Generate an OpenVEX document from pip-audit JSON output."""

import json
import sys
import uuid
from datetime import datetime, timezone


def generate_vex(audit_path: str) -> dict:
    """Read pip-audit JSON and produce an OpenVEX document."""
    try:
        with open(audit_path) as f:
            audit_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        audit_data = {"dependencies": []}

    statements = []
    dependencies = audit_data.get("dependencies", [])

    for dep in dependencies:
        vulns = dep.get("vulns", [])
        for vuln in vulns:
            statements.append(
                {
                    "vulnerability": {
                        "@id": vuln.get("id", "UNKNOWN"),
                        "name": vuln.get("id", "UNKNOWN"),
                        "description": vuln.get("description", ""),
                    },
                    "products": [
                        {
                            "@id": f"pkg:pypi/{dep['name']}@{dep.get('version', 'unknown')}",
                            "subcomponents": [],
                        }
                    ],
                    "status": "affected",
                    "justification": "",
                    "action_statement": f"Update {dep['name']} to {vuln['fix_versions'][0]}"
                    if vuln.get("fix_versions")
                    else f"Monitor {dep['name']} for a fix",
                }
            )

    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": f"https://openvex.dev/docs/{uuid.uuid4()}",
        "author": "Pylon CI",
        "role": "document_author",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": 1,
        "tooling": "pylon/generate_vex.py",
        "statements": statements,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: generate_vex.py <audit.json>", file=sys.stderr)
        sys.exit(1)

    vex_doc = generate_vex(sys.argv[1])
    print(json.dumps(vex_doc, indent=2))


if __name__ == "__main__":
    main()
