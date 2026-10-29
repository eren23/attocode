"""Independent TTL cleanup restricted to timestamped scale-owned SSH keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error

PATTERN = re.compile(r"attocode-scale-key-(\d{1,12})-([0-9a-f]{16})\Z")
TTL = 7200


def key_name(row):
    return (
        f"attocode-scale-key-{int(row.get('created_at', time.time()))}-"
        + hashlib.sha256(row["id"].encode()).hexdigest()[:16]
    )


def key_rows(api):
    result = []
    for page in range(1, 101):
        data = api.request("GET", f"/account/keys?per_page=200&page={page}")
        result.extend(data["ssh_keys"])
        if not data.get("links", {}).get("pages", {}).get("next"):
            return result
    raise ValueError("SSH key pagination limit")


def destroy_key(api, identity):
    try:
        api.request("DELETE", "/account/keys/" + str(identity))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    try:
        api.request("GET", "/account/keys/" + str(identity))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True
        raise
    return False


def cleanup_key(api, name, *, known_id=None, attempted=False):
    identities = {k["id"] for k in key_rows(api) if k["name"] == name}
    if known_id is not None:
        identities.add(known_id)
    deleted = all(destroy_key(api, identity) for identity in identities)
    return (
        deleted
        and not any(k["name"] == name for k in key_rows(api))
        and (not attempted or bool(identities))
    )


def reap_keys(api, *, now=None, apply=False):
    now = time.time() if now is None else now
    rows = []
    for key in key_rows(api):
        match = PATTERN.fullmatch(key["name"])
        if match and now - int(match[1]) >= TTL:
            row = {"id": key["id"], "name": key["name"], "expired": True, "deleted": False}
            if apply:
                try:
                    row["deleted"] = destroy_key(api, key["id"])
                except Exception as error:
                    row["error"] = type(error).__name__
            rows.append(row)
    return {
        "dry_run": not apply,
        "keys": rows,
        "cleanup_verified": not apply or all(r["deleted"] for r in rows),
    }


def main():
    from eval.quality.cloud import API

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    result = reap_keys(API(), apply=parser.parse_args().apply)
    print(json.dumps(result))
    return 0 if result["cleanup_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
