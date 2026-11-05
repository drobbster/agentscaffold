#!/usr/bin/env python3
"""Scan for private data that must not ship in this public repository.

Generic rules cover home-directory paths and machine-local email addresses.
Private literals come from PUBLIC_CONTENT_DENYLIST or
PUBLIC_CONTENT_DENYLIST_FILE. Findings are ``path:line: <label>`` and never
include the matched text.

Exit 0 when nothing is found, 1 when something is, 2 when the scan itself
cannot run.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

MIN_LITERAL = 4
PLACEHOLDERS = frozenset(
    {"me", "you", "user", "someone", "dev", "runner", "example", "alice", "bob"}
)
HOME_PATH = re.compile(r"/(?:Users|home)/([A-Za-z0-9._-]+)")
LOCAL_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.local\b", re.IGNORECASE)
ZERO_SHA = "0" * 40

LABEL_HOME = "home-path"
LABEL_EMAIL = "local-email"
LABEL_PRIVATE = "private-literal"


class ScanError(Exception):
    """The scan could not run. The message must not contain scanned content."""


def parse_literals(text: str) -> list[str]:
    """Non-comment lines, case-folded, in order. Rejects short literals."""
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) < MIN_LITERAL:
            raise ValueError("private list has a literal shorter than 4 characters")
        folded = line.casefold()
        if folded not in found:
            found.append(folded)
    return found


def load_private_literals() -> list[str]:
    """Literals from the environment variable and the file, if either is set."""
    chunks: list[str] = []
    env = os.environ.get("PUBLIC_CONTENT_DENYLIST")
    if env:
        chunks.append(env)
    path = os.environ.get("PUBLIC_CONTENT_DENYLIST_FILE")
    if path:
        file = Path(path)
        if not file.is_file():
            raise ValueError("private list file was set but cannot be read")
        chunks.append(file.read_text(encoding="utf-8"))
    literals: list[str] = []
    for chunk in chunks:
        for item in parse_literals(chunk):
            if item not in literals:
                literals.append(item)
    return literals


def is_noreply(email: str) -> bool:
    return email.casefold().endswith("@users.noreply.github.com")


def git_email(repo: Path) -> str | None:
    result = _git(repo, ["config", "--get", "user.email"], check=False)
    email = result.stdout.decode("utf-8", "replace").strip()
    return email or None


def home_directory() -> str:
    return str(Path.home())


def derived_terms(repo: Path) -> list[tuple[str, str]]:
    """Home directory and git email, unless they are placeholders or noreply."""
    terms: list[tuple[str, str]] = []
    home = home_directory()
    segment = Path(home).name.casefold()
    plain_root = home not in {"/", "/Users", "/home"}
    if segment not in PLACEHOLDERS and plain_root and len(home) >= MIN_LITERAL:
        terms.append((home.casefold(), "home-directory"))
    email = git_email(repo)
    if email and not is_noreply(email) and len(email) >= MIN_LITERAL:
        terms.append((email.casefold(), "git-email"))
    return terms


def line_labels(line: str, private: list[str], derived: list[tuple[str, str]]) -> list[str]:
    labels: list[str] = []
    folded = line.casefold()
    for match in HOME_PATH.finditer(line):
        if match.group(1).casefold() in PLACEHOLDERS:
            continue
        if LABEL_HOME not in labels:
            labels.append(LABEL_HOME)
    if LOCAL_EMAIL.search(line) and LABEL_EMAIL not in labels:
        labels.append(LABEL_EMAIL)
    for literal in private:
        if literal in folded:
            labels.append(LABEL_PRIVATE)
            break
    for literal, label in derived:
        if literal in folded and label not in labels:
            labels.append(label)
    return labels


def scan_text(
    text: str,
    path: str,
    private: list[str],
    derived: list[tuple[str, str]],
) -> list[str]:
    if "\0" in text:
        return []
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        labels = line_labels(line, private, derived)
        findings.extend(f"{path}:{number}: {label}" for label in labels)
    return findings


def scan_bytes(
    data: bytes,
    path: str,
    private: list[str],
    derived: list[tuple[str, str]],
) -> list[str]:
    if b"\0" in data:
        return []
    return scan_text(data.decode("utf-8", "replace"), path, private, derived)


def _git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").splitlines()
        summary = detail[0] if detail else "no stderr"
        raise ScanError(f"git {args[0]} failed ({summary})")
    return result


def staged_blobs(repo: Path) -> list[tuple[str, bytes]]:
    listed = _git(repo, ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"])
    names = [name for name in listed.stdout.decode("utf-8", "replace").split("\0") if name]
    blobs: list[tuple[str, bytes]] = []
    for name in names:
        shown = _git(repo, ["show", f":{name}"], check=False)
        if shown.returncode != 0:
            continue
        blobs.append((name, shown.stdout))
    return blobs


def tracked_worktree(repo: Path) -> list[tuple[str, bytes]]:
    listed = _git(repo, ["ls-files", "-z"])
    blobs: list[tuple[str, bytes]] = []
    for name in listed.stdout.decode("utf-8", "replace").split("\0"):
        if not name:
            continue
        path = repo / name
        if path.is_file():
            blobs.append((name, path.read_bytes()))
    return blobs


def rev_blobs(repo: Path, rev: str) -> list[tuple[str, bytes]]:
    listed = _git(repo, ["ls-tree", "-r", "-z", rev])
    entries: list[tuple[str, str]] = []
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        meta, _, path = raw.partition(b"\t")
        parts = meta.split(b" ")
        if len(parts) < 3 or parts[1] != b"blob":
            continue
        entries.append((parts[2].decode("ascii"), path.decode("utf-8", "replace")))
    if not entries:
        return []
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None
    for sha, _path in entries:
        proc.stdin.write(f"{sha}\n".encode())
    proc.stdin.close()
    blobs: list[tuple[str, bytes]] = []
    for _sha, path in entries:
        header = proc.stdout.readline()
        if b" missing" in header or not header:
            proc.kill()
            raise ScanError("git cat-file could not read a blob")
        try:
            size = int(header.split()[-1])
        except ValueError as exc:
            proc.kill()
            raise ScanError("unexpected git cat-file header") from exc
        data = proc.stdout.read(size)
        if proc.stdout.read(1) != b"\n":
            proc.kill()
            raise ScanError("truncated git cat-file output")
        blobs.append((path, data))
    if proc.wait() != 0:
        raise ScanError("git cat-file --batch failed")
    return blobs


def commit_texts(repo: Path, range_expr: str, *, not_remotes: bool) -> list[tuple[str, bytes]]:
    fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%s%x1f%b%x1e"
    args = ["log", f"--format={fmt}"]
    if not_remotes:
        args.extend([range_expr, "--not", "--remotes"])
    else:
        args.append(range_expr)
    result = _git(repo, args)
    records: list[tuple[str, bytes]] = []
    for raw in result.stdout.split(b"\x1e"):
        if not raw.strip():
            continue
        fields = raw.split(b"\x1f")
        if len(fields) < 7:
            continue
        sha = fields[0].decode("ascii", "replace")[:12]
        records.append((f"commit:{sha}", b"\n".join(fields[1:7])))
    return records


def dist_members(path: Path) -> list[tuple[str, bytes]]:
    name = path.name
    members: list[tuple[str, bytes]] = []
    if name.endswith(".whl") or name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                members.append((f"{name}:{info.filename}", archive.read(info)))
        return members
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(path, "r:gz") as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                extracted = archive.extractfile(info)
                if extracted is None:
                    continue
                members.append((f"{name}:{info.name}", extracted.read()))
        return members
    raise ScanError(f"unsupported dist file: {name}")


def scan_pairs(
    pairs: list[tuple[str, bytes]],
    private: list[str],
    derived: list[tuple[str, str]],
) -> list[str]:
    findings: list[str] = []
    for path, data in pairs:
        findings.extend(scan_bytes(data, path, private, derived))
    return findings


def collect(args: argparse.Namespace, repo: Path) -> list[tuple[str, bytes]]:
    if args.staged:
        return staged_blobs(repo)
    if args.all:
        return tracked_worktree(repo)
    if args.rev:
        return rev_blobs(repo, args.rev)
    if args.messages:
        return commit_texts(repo, args.messages, not_remotes=args.not_remotes)
    if args.dist:
        members: list[tuple[str, bytes]] = []
        for raw in args.dist:
            path = Path(raw)
            if not path.is_file():
                raise ScanError(f"dist file not found: {path.name}")
            members.extend(dist_members(path))
        return members
    return [("stdin", sys.stdin.buffer.read())]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan for private data that must not ship in this public repository."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="Scan the index, not the worktree.")
    mode.add_argument("--all", action="store_true", help="Scan every tracked file.")
    mode.add_argument("--rev", metavar="REV", help="Scan every file at a commit.")
    mode.add_argument("--messages", metavar="RANGE", help="Scan commit messages and identities.")
    mode.add_argument("--dist", nargs="+", metavar="FILE", help="Scan wheel and sdist archives.")
    mode.add_argument("--stdin", action="store_true", help="Scan text on standard input.")
    parser.add_argument(
        "--not-remotes",
        action="store_true",
        help="With --messages TIP, scan commits on TIP that are on no remote.",
    )
    parser.add_argument(
        "--require-private",
        action="store_true",
        help="Fail if no private literal list was loaded.",
    )
    parser.add_argument("--repo", default=".", help="Repository root. Defaults to cwd.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.not_remotes and not args.messages:
        parser.error("--not-remotes requires --messages")
    repo = Path(args.repo).resolve()
    try:
        private = load_private_literals()
        if args.require_private and not private:
            raise ScanError("private list is required and none was loaded")
        findings = scan_pairs(collect(args, repo), private, derived_terms(repo))
    except ScanError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not findings:
        return 0
    print("\n".join(findings))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
