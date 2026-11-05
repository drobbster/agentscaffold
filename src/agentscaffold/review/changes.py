"""Which files a plan changed, from git, for the post-implementation rule rows (Plan 281).

Sources, first that applies:

1. ``base_ref``: the diff from that ref to the working tree.
2. The plan's merged branches: first-parent merge commits whose message names a
   branch carrying the plan number (``feature/278-x``, ``docs/278-completion``);
   the union of each merge's first-parent diff. When the current branch is also
   a plan branch (a completion branch still open), its changes are added.
3. The plan's unmerged branch: the diff from its merge-base with the base
   branch, plus uncommitted and untracked files.
4. The commit recorded at the pre-implementation review: the diff from it to the
   working tree. Covers direct commits to main and squash merges.
5. The File Impact Map.

Git runs with an argument list and a timeout, never a shell. Refs and commit ids
are validated before they reach git.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 15
MERGE_SCAN_LIMIT = 2000

_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")
_MERGE_SUBJECTS = (
    re.compile(r"^Merge (?:remote-tracking )?branch '([^']+)'"),
    re.compile(r"^Merge pull request #\d+ from (\S+)"),
)
_DEFAULT_BASES = ("staging", "main", "master")


@dataclass(frozen=True)
class ChangeSet:
    """Files a plan changed under *root*, and where that list came from."""

    root: Path
    files: list[str]
    source: str
    detail: str


def validate_ref(ref: str) -> str:
    """Return *ref* if it is safe to pass to git; raise ValueError otherwise."""
    if not ref or not _SAFE_REF.match(ref) or ref.startswith("-") or ".." in ref:
        raise ValueError(f"unsafe git ref: {ref!r}")
    return ref


def plan_changes(
    root: Path,
    plan_number: int,
    *,
    base_ref: str | None = None,
    base_branch: str | None = None,
    reviewed_commit: str | None = None,
    impact_paths: Iterable[str] = (),
) -> ChangeSet:
    """Files changed for *plan_number* under *root*; see the module docstring.

    Raises ValueError for an unsafe *base_ref* or *base_branch*, or a *base_ref*
    git does not know.
    """
    root = Path(root)
    if base_ref is not None:
        validate_ref(base_ref)
    if base_branch:
        validate_ref(base_branch)
    if reviewed_commit:
        try:
            validate_ref(reviewed_commit)
        except ValueError:
            logger.warning("ignoring unsafe reviewed commit %r", reviewed_commit)
            reviewed_commit = None

    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return _impact_map(root, impact_paths, "not a git work tree")

    if base_ref is not None:
        files = _diff_to_worktree(root, base_ref)
        if files is None:
            raise ValueError(f"git does not know base_ref {base_ref!r}")
        return ChangeSet(root, _sorted(files), "base_ref", f"diff from {base_ref}")

    merged = _merged_branches(root, plan_number)
    unmerged = _unmerged_branch(root, plan_number, base_branch)
    if merged and unmerged:
        return ChangeSet(
            root,
            _sorted(merged[0] + unmerged[0]),
            "merged_branches+unmerged_branch",
            f"{merged[1]}; {unmerged[1]}",
        )
    if merged:
        return ChangeSet(root, _sorted(merged[0]), "merged_branches", merged[1])
    if unmerged:
        return ChangeSet(root, _sorted(unmerged[0]), "unmerged_branch", unmerged[1])

    if reviewed_commit:
        files = _diff_to_worktree(root, reviewed_commit)
        if files is not None:
            return ChangeSet(
                root,
                _sorted(files),
                "reviewed_commits",
                f"diff from {reviewed_commit[:12]}, recorded at the pre-implementation review",
            )

    return _impact_map(root, impact_paths, "no plan branch or reviewed commit found")


def head_commit(root: Path) -> str | None:
    """HEAD's commit id under *root*, or None outside git."""
    out = _git(Path(root), "rev-parse", "HEAD")
    return out or None


def plan_branch_pattern(plan_number: int) -> re.Pattern[str]:
    """Branch names carrying *plan_number* as a path segment prefix."""
    return re.compile(rf"(?:^|/)0*{int(plan_number)}(?:[-/]|$)")


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def _merged_branches(root: Path, plan_number: int) -> tuple[list[str], str] | None:
    log = _git(
        root,
        "log",
        "--first-parent",
        "--merges",
        f"--max-count={MERGE_SCAN_LIMIT}",
        "--format=%H%x00%s",
        "HEAD",
    )
    if not log:
        return None
    pattern = plan_branch_pattern(plan_number)
    files: list[str] = []
    branches: list[str] = []
    for line in log.splitlines():
        commit, _, subject = line.partition("\x00")
        branch = _merged_branch_name(subject)
        if branch is None or not pattern.search(branch):
            continue
        diff = _git_lines(root, "diff", "--name-only", "--relative", f"{commit}^1", commit)
        if diff is None:
            continue
        files.extend(diff)
        branches.append(branch)
    if not branches:
        return None
    names = ", ".join(reversed(branches))
    return files, f"{len(branches)} merge commit(s) of plan branches: {names}"


def _merged_branch_name(subject: str) -> str | None:
    for pattern in _MERGE_SUBJECTS:
        match = pattern.match(subject)
        if match:
            return match.group(1)
    return None


def _unmerged_branch(
    root: Path, plan_number: int, base_branch: str | None
) -> tuple[list[str], str] | None:
    current = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not current or not plan_branch_pattern(plan_number).search(current):
        return None
    base = _base_branch(root, current, base_branch)
    if base is None:
        return None
    merge_base = _git(root, "merge-base", "HEAD", base)
    if not merge_base:
        return None
    files = _diff_to_worktree(root, merge_base)
    if files is None:
        return None
    return files, f"branch {current} since its merge-base with {base}, plus uncommitted files"


def _base_branch(root: Path, current: str, configured: str | None) -> str | None:
    if configured:
        return configured if _ref_exists(root, configured) else None
    candidates: list[str] = []
    upstream = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if upstream:
        candidates.append(upstream)
    candidates.extend(_DEFAULT_BASES)
    for name in candidates:
        if name != current and _SAFE_REF.match(name) and _ref_exists(root, name):
            return name
    return None


def _impact_map(root: Path, impact_paths: Iterable[str], why: str) -> ChangeSet:
    return ChangeSet(
        root,
        _sorted(p for p in impact_paths if p),
        "file_impact_map",
        f"the plan's File Impact Map ({why})",
    )


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def _diff_to_worktree(root: Path, ref: str) -> list[str] | None:
    changed = _git_lines(root, "diff", "--name-only", "--relative", ref)
    if changed is None:
        return None
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard") or []
    return changed + untracked


def _ref_exists(root: Path, ref: str) -> bool:
    return bool(_git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"))


def _git_lines(root: Path, *args: str) -> list[str] | None:
    out = _git(root, *args, allow_empty=True)
    if out is None:
        return None
    return [line for line in out.splitlines() if line]


def _git(root: Path, *args: str, allow_empty: bool = False) -> str | None:
    """Run git under *root*; stdout stripped, or None on any failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=off", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("git %s failed under %s: %s", args[0] if args else "", root, exc)
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out and not allow_empty:
        return None
    return out


def _sorted(paths: Iterable[str]) -> list[str]:
    return sorted({p for p in paths if p})
