"""Pure synthetic immutable-write sizing; no provider, production DB or filesystem scan.

Compares current two-prefix, candidate flat three-prefix, and a proposed two-level
three-prefix descriptor index. JSON bytes include leaves, descriptors and root.
Does not estimate real filesystem blocks, network, latency or production payloads.
"""

import argparse
import hashlib
import json
import math


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def descriptor(payload, bucket, count):
    digest = sha(payload)
    return {
        "path": f"documents/{digest}.json",
        "sha256": digest,
        "bytes": len(payload),
        "mime": "application/json",
        "bucket": bucket,
        "count": count,
    }


def row(number):
    identifier = sha(str(number).encode())
    return identifier, encode(
        {
            "id": identifier,
            "observation": sha(f"observation{number}".encode()) + ".json",
            "url": f"https://example.com/announcements/2026/09/09/document-{number}.pdf",
            "expected_mime": "application/pdf",
            "download_status": "pending",
            "parse_status": "not_attempted",
            "download_tries": 0,
            "parse_tries": 0,
            "retry_after": 0.0,
            "parse_retry_after": 0.0,
            "result": {},
        }
    )


def leaf(bucket, identifiers, rows):
    # Exactly equivalent to canonical _json({'schema_version':2,'kind':'states',
    # 'bucket':bucket,'items':[json.loads(rows[id]) for id in sorted(identifiers)]}).
    return (
        b'{"bucket":'
        + encode(bucket)
        + b',"items":['
        + b",".join(rows[key] for key in sorted(identifiers))
        + b'],"kind":"states","schema_version":2}'
    )


def compare(n=316831, references=362139):
    rows = dict(row(i) for i in range(n))
    groups = {width: {} for width in (2, 3)}
    for key in rows:
        for width in groups:
            groups[width].setdefault(key[:width], set()).add(key)
    descriptors = {}
    for width in groups:
        descriptors[width] = {
            key: descriptor(leaf(key, ids, rows), key, len(ids))
            for key, ids in groups[width].items()
        }
    mapping_descriptors = [
        descriptor(
            encode({"fixture_mapping_bucket": i}),
            str(i),
            min(1000, references - i * 1000),
        )
        for i in range(math.ceil(references / 1000))
    ]

    def index(leaves, total, changed, nested):
        root = {
            "schema_version": 3 if nested else 2,
            "shard_rows": 1000,
            "mappings": mapping_descriptors,
            "attempts": [],
            "files": [],
            "states": leaves,
            "state_prefix_chars": len(next(iter(leaves))),
            "counts": [
                {
                    "download_status": "pending",
                    "parse_status": "not_attempted",
                    "count": total - changed,
                }
            ],
            "reference_counts": [{"status": "queued", "references_count": references}],
            "totals": {"mappings": references, "attempts": 0, "files": 0},
        }
        if changed:
            root["counts"].append(
                {
                    "download_status": "downloaded",
                    "parse_status": "parsed",
                    "count": changed,
                }
            )
        parts = {}
        if nested:
            for first in "0123456789abcdef":
                items = [
                    value
                    for key, value in sorted(leaves.items())
                    if key.startswith(first)
                ]
                payload = encode(
                    {
                        "schema_version": 2,
                        "kind": "state_descriptors",
                        "bucket": first,
                        "items": items,
                    }
                )
                parts[first] = descriptor(payload, first, len(items))
            root["states"] = parts
            root["state_descriptor_prefix_chars"] = 1
        return descriptor(encode(root), "root", 1), parts

    baseline = {
        name: index(descriptors[width], n, 0, nested)
        for name, width, nested in (
            ("two_hex_flat", 2, False),
            ("three_hex_flat", 3, False),
            ("three_hex_two_levels", 3, True),
        )
    }
    results = []
    for label, updates, added in (
        ("one_state_update", 1, 0),
        ("thirty_state_updates", 30, 0),
        ("append_1000", 0, 1000),
    ):
        original = {}
        affected = []
        for i in range(updates):
            key = sha(str(i).encode())
            original[key] = rows[key]
            value = json.loads(rows[key])
            value.update(
                download_status="downloaded",
                parse_status="parsed",
                download_tries=1,
                parse_tries=1,
            )
            value["result"] = {
                "status": "downloaded",
                "parse_status": "parsed",
                "fetched_at": "2026-09-09T00:00:00Z",
                "files": [
                    {
                        "path": "attachments/" + sha(str(i).encode()) + ".pdf",
                        "bytes": 100000,
                        "sha256": sha(str(i).encode()),
                        "mime": "application/pdf",
                    }
                ],
            }
            rows[key] = encode(value)
            affected.append(key)
        for i in range(n, n + added):
            key, value = row(i)
            rows[key] = value
            affected.append(key)
            for width in groups:
                groups[width].setdefault(key[:width], set()).add(key)
        for name, width, nested in (
            ("two_hex_flat", 2, False),
            ("three_hex_flat", 3, False),
            ("three_hex_two_levels", 3, True),
        ):
            current = dict(descriptors[width])
            changed = {key[:width] for key in affected}
            leaf_bytes = 0
            for bucket in changed:
                ids = groups[width][bucket]
                payload = leaf(bucket, ids, rows)
                current[bucket] = descriptor(payload, bucket, len(ids))
                leaf_bytes += len(payload)
            top, parts = index(current, n + added, updates, nested)
            changed_parts = [
                item
                for key, item in parts.items()
                if baseline[name][1].get(key) != item
            ]
            descriptor_bytes = sum(item["bytes"] for item in changed_parts)
            results.append(
                {
                    "scenario": label,
                    "layout": name,
                    "leaf_shards": len(changed),
                    "leaf_bytes": leaf_bytes,
                    "descriptor_shards": len(changed_parts),
                    "descriptor_bytes": descriptor_bytes,
                    "root_bytes": top["bytes"],
                    "total_new_bytes": leaf_bytes + descriptor_bytes + top["bytes"],
                }
            )
        rows.update(original)
        for key in affected[updates:]:
            rows.pop(key)
            for width in groups:
                groups[width][key[:width]].remove(key)
    return {
        "synthetic_only": True,
        "document_rows": n,
        "reference_rows": references,
        "fixed_mapping_descriptor_count": len(mapping_descriptors),
        "limits": "Exact bytes of synthetic JSON only; ignores allocation blocks/CPU/retained old artifacts. Attempts/files lists empty; production URL/result shapes and actual write pattern differ.",
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=316831)
    parser.add_argument("--references", type=int, default=362139)
    args = parser.parse_args()
    if args.rows < 30 or args.references < 0:
        parser.error("rows must be at least30 and references nonnegative")
    print(json.dumps(compare(args.rows, args.references), indent=2))
