"""Which files a plan changed, from git, for the post-implementation rule rows.

Sources, first that applies:

1. ``base_ref``: the diff from that ref to the working tree.
2. The plan's merged branches: merge commits whose message names a branch
   carrying the plan number (``feature/42-x``, ``docs/plan-42-completion``),
   and squash merges whose subject starts with the plan number (``Plans 41,
   42: ... (#17)``), on the first-parent history of HEAD and of each base
   branch that exists; the union of each one's first-parent diff. When the current branch is
   also a plan branch (a completion branch still open), its changes are added.
3. The plan's unmerged branch: the diff from its merge-base with the base
   branch, plus uncommitted and untracked files.
4. The commit recorded at the pre-implementation review: the diff from it to the
   working tree. Covers direct commits to main and squash merges.
5. The File Impact Map.

Git runs with an argument list and a timeout, never a shell. Refs and commit ids
are validated before they reach git.

With ``graph.extra_paths``, changed files outside the project folder
that match one of its globs are listed as well, as ``@repo/<path>``.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from agentscaffold.repo_paths import compile_extra_glob, extra_glob_problem, repo_node_path

logger = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 15
MERGE_SCAN_LIMIT = 2000

_SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")
_MERGE_SUBJECTS = (
    re.compile(r"^Merge (?:remote-tracking )?branch '([^']+)'"),
    re.compile(r"^Merge pull request #\d+ from (\S+)"),
)
_SQUASH_SUFFIX = re.compile(r"\(#\d+\)\s*$")
_PLAN_LIST = re.compile(r"^\s*Plans?\s+((?:\d+(?:\s*(?:,|&|/|and)\s*)?)+)", re.IGNORECASE)
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
    extra_paths: Sequence[str] = (),
) -> ChangeSet:
    """Files changed for *plan_number* under *root*; see the module docstring.

    Raises ValueError for an unsafe *base_ref* or *base_branch*, or a *base_ref*
    git does not know.
    """
    root = Path(root)
    extra = _ExtraPaths.for_root(root, extra_paths)
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
        files = _diff_to_worktree(root, base_ref, extra)
        if files is None:
            raise ValueError(f"git does not know base_ref {base_ref!r}")
        return ChangeSet(root, _sorted(files), "base_ref", f"diff from {base_ref}")

    current = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD") or ""
    base = _base_branch(root, current, base_branch)
    history = _history_refs(root, current, base_branch)
    merged = _merged_branches(root, plan_number, history, extra)
    unmerged = _unmerged_branch(root, plan_number, current, base, extra)
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
        files = _diff_to_worktree(root, reviewed_commit, extra)
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
    """Branch names carrying *plan_number* as a path segment prefix (``plan-`` allowed)."""
    return re.compile(rf"(?:^|/)(?:plans?[-_]?)?0*{int(plan_number)}(?:[-/_]|$)", re.IGNORECASE)


def squash_names_plan(subject: str, plan_number: int) -> bool:
    """A GitHub squash merge (``... (#N)``) whose subject starts with the plan number."""
    if not _SQUASH_SUFFIX.search(subject):
        return False
    match = _PLAN_LIST.match(subject)
    if match is None:
        return False
    return int(plan_number) in {int(n) for n in re.findall(r"\d+", match.group(1))}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def _merged_branches(
    root: Path, plan_number: int, starts: list[str], extra: _ExtraPaths | None = None
) -> tuple[list[str], str] | None:
    log = _git(
        root,
        "log",
        "--first-parent",
        f"--max-count={MERGE_SCAN_LIMIT}",
        "--format=%H%x00%P%x00%s",
        *starts,
    )
    if not log:
        return None
    pattern = plan_branch_pattern(plan_number)
    files: list[str] = []
    branches: list[str] = []
    squashes: list[str] = []
    for line in log.splitlines():
        commit, _, rest = line.partition("\x00")
        parents, _, subject = rest.partition("\x00")
        count = len(parents.split())
        branch = _merged_branch_name(subject) if count > 1 else None
        if branch is not None and pattern.search(branch):
            found = branches
            label = branch
        elif count == 1 and squash_names_plan(subject, plan_number):
            found = squashes
            label = commit[:12]
        else:
            continue
        diff = _diff_names(root, extra, f"{commit}^1", commit)
        if diff is None:
            continue
        files.extend(diff)
        found.append(label)
    parts = []
    if branches:
        names = ", ".join(reversed(branches))
        parts.append(f"{len(branches)} merge commit(s) of plan branches ({names})")
    if squashes:
        parts.append(f"{len(squashes)} squash merge(s) ({', '.join(reversed(squashes))})")
    if not parts:
        return None
    return files, "; ".join(parts)


def _merged_branch_name(subject: str) -> str | None:
    for pattern in _MERGE_SUBJECTS:
        match = pattern.match(subject)
        if match:
            return match.group(1)
    return None


def _unmerged_branch(
    root: Path,
    plan_number: int,
    current: str,
    base: str | None,
    extra: _ExtraPaths | None = None,
) -> tuple[list[str], str] | None:
    if not current or base is None or not plan_branch_pattern(plan_number).search(current):
        return None
    merge_base = _git(root, "merge-base", "HEAD", base)
    if not merge_base:
        return None
    files = _diff_to_worktree(root, merge_base, extra)
    if files is None:
        return None
    return files, f"branch {current} since its merge-base with {base}, plus uncommitted files"


def _base_branch(root: Path, current: str, configured: str | None) -> str | None:
    bases = _base_candidates(root, current, configured)
    return bases[0] if bases else None


def _history_refs(root: Path, current: str, configured: str | None) -> list[str]:
    """HEAD plus every base branch that exists: plans may land on any of them."""
    return ["HEAD", *_base_candidates(root, current, configured)]


def _base_candidates(root: Path, current: str, configured: str | None) -> list[str]:
    if configured:
        return [configured] if _ref_exists(root, configured) else []
    candidates: list[str] = []
    upstream = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if upstream:
        candidates.append(upstream)
    candidates.extend(_DEFAULT_BASES)
    return [
        name
        for name in dict.fromkeys(candidates)
        if name != current and _SAFE_REF.match(name) and _ref_exists(root, name)
    ]


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


@dataclass(frozen=True)
class _ExtraPaths:
    """Which repository-relative paths outside the project are extra-path files."""

    project_prefix: str
    patterns: tuple[re.Pattern[str], ...]

    @classmethod
    def for_root(cls, root: Path, globs: Sequence[str]) -> _ExtraPaths | None:
        valid = [g for g in globs if extra_glob_problem(g) is None]
        if not valid:
            return None
        prefix = _git(root, "rev-parse", "--show-prefix", allow_empty=True)
        if prefix is None:
            return None
        return cls(prefix, tuple(compile_extra_glob(g) for g in valid))

    def node_paths(self, repo_relative: Iterable[str]) -> list[str]:
        return [
            repo_node_path(p)
            for p in repo_relative
            if not p.startswith(self.project_prefix) and any(m.fullmatch(p) for m in self.patterns)
        ]


def _diff_names(root: Path, extra: _ExtraPaths | None, *revs: str) -> list[str] | None:
    """Changed files: project-relative, then matching extra-path files as ``@repo/``."""
    changed = _git_lines(root, "diff", "--name-only", "--relative", *revs)
    if changed is None or extra is None:
        return changed
    whole = _git_lines(root, "diff", "--name-only", "--no-relative", *revs) or []
    return changed + extra.node_paths(whole)


def _diff_to_worktree(root: Path, ref: str, extra: _ExtraPaths | None = None) -> list[str] | None:
    changed = _diff_names(root, extra, ref)
    if changed is None:
        return None
    untracked = _git_lines(root, "ls-files", "--others", "--exclude-standard") or []
    if extra is not None:
        everywhere = _git_lines(
            root, "ls-files", "--others", "--exclude-standard", "--full-name", ":/"
        )
        untracked += extra.node_paths(everywhere or [])
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
