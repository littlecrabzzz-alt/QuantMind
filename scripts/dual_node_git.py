#!/usr/bin/env python3
"""Explicit fast-forward of Git metadata; never checkout synchronized files."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from dual_node_sync import PROJECT


def git(*args, **kwargs):
    return subprocess.run(["git", "-C", str(PROJECT), *args], check=True, **kwargs)


def output(*args):
    return git(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def state():
    require(not output("diff", "--cached", "--name-only"), "Staged changes must be resolved before Git handoff")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "index.lock"):
        require(not Path(output("rev-parse", "--path-format=absolute", "--git-path", marker)).exists(), "Git operation is in progress: " + marker)
    branch = output("symbolic-ref", "--short", "HEAD")
    return output("rev-parse", "HEAD"), branch


def write_bundle(expected_head, base, stream):
    require(state()[0] == expected_head, "Source HEAD changed during handoff")
    git("merge-base", "--is-ancestor", base, expected_head)
    with tempfile.TemporaryDirectory(prefix="quantmind-git-") as directory:
        bundle = Path(directory) / "commits.bundle"
        git("bundle", "create", str(bundle), "HEAD", "^" + base)
        require(state()[0] == expected_head, "Source HEAD changed while exporting commits")
        with bundle.open("rb") as source:
            import shutil
            shutil.copyfileobj(source, stream)


def receive_bundle(expected_head, branch, target, digest, role, stream):
    require(state() == (expected_head, branch), "Destination Git state changed")
    with tempfile.TemporaryDirectory(prefix="quantmind-git-") as directory:
        bundle = Path(directory) / "commits.bundle"
        with bundle.open("wb") as destination:
            import shutil
            shutil.copyfileobj(stream, destination)
        git("bundle", "verify", str(bundle), stdout=subprocess.DEVNULL)
        git("fetch", "--no-write-fetch-head", str(bundle), "HEAD", stdout=subprocess.DEVNULL)
        git("merge-base", "--is-ancestor", expected_head, target)
        current = json.loads(subprocess.check_output([
            sys.executable, str(PROJECT / "scripts/dual_node_sync.py"), role, "--content-hash"], text=True))
        require(current["contentDigest"] == digest, "Working tree changed during handoff")
        require(state() == (expected_head, branch), "Destination Git state changed during verification")
        # --mixed updates only HEAD/index and retains every tracked/untracked file.
        # Staged changes were explicitly rejected above; no reset --hard/checkout.
        git("reset", "--mixed", "--no-refresh", target, stdout=subprocess.DEVNULL)
        require(state() == (target, branch), "Git metadata alignment did not complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("bundle")
    export.add_argument("expected_head")
    export.add_argument("base")
    receive = commands.add_parser("receive")
    for name in ("expected_head", "branch", "target", "digest", "role"):
        receive.add_argument(name)
    args = parser.parse_args()
    try:
        if args.command == "bundle":
            write_bundle(args.expected_head, args.base, sys.stdout.buffer)
        else:
            receive_bundle(args.expected_head, args.branch, args.target, args.digest, args.role, sys.stdin.buffer)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Git handoff refused: {exc}", file=sys.stderr)
        raise SystemExit(1)
