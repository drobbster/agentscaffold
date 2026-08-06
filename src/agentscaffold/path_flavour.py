"""Path-flavour-correct comparison for registry roots (Plan 249, Step A9b).

The registry records absolute roots as strings and later has to answer "does this
working path lie under that root?". Doing so with the *host's* path flavour is
wrong in both directions, and the failures are quiet ones.

``pathlib`` already implements the hard parts correctly, provided it is handed the
right flavour. Measured rather than assumed:

- ``PureWindowsPath`` folds case (``C:\\Repo`` == ``c:\\repo``), normalises
  separators (``C:\\repo\\src`` == ``C:/repo/src``), understands drive letters as
  distinct roots, and treats a UNC ``\\\\server\\share`` as the drive -- so a
  different share does not match, and server and share names fold case too.
- ``PurePosixPath`` is case-**sensitive**, which is equally required.
- Both compare on path components, so ``C:\\repo`` never captures ``C:\\repo-two``.

So this module contains no matching logic of its own. Its whole job is choosing
the flavour, which is the part that was actually wrong.

**Why WSL forces the flavour to come from the string, not the host.** A WSL path
is ``/mnt/c/repo``: genuinely POSIX, genuinely case-sensitive, and it names the
same bytes on disk as ``C:\\repo``. Deciding "windowsness" from the presence of a
drive letter would misclassify every WSL path, and WSL on Windows is the
environment this plan exists to support. Deciding it from the host would make the
Windows branches untestable anywhere but Windows, and this package has no CI.

**The two spaces deliberately do not cross-match.** ``C:\\repo`` and
``/mnt/c/repo`` can be one directory, but WSL and Windows have separate home
directories and therefore separate registries, and nothing here can know how
``/mnt`` is mounted without reading WSL configuration we do not own. Guessing an
equivalence would resolve a call to the wrong project; declining to guess yields a
refusal the caller already knows how to report.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

#: ``C:\``, ``C:/`` or a bare ``C:`` -- a drive letter at the *start* of the path.
#: Anchored deliberately: an unanchored search for a drive letter matches
#: ``/mnt/c/...`` and every other POSIX path containing a colon.
_DRIVE_RE = re.compile(r"^[A-Za-z]:([\\/]|$)")

#: ``\\server\share`` and the ``//server/share`` form pathlib also accepts.
_UNC_RE = re.compile(r"^(\\\\|//)[^\\/]+[\\/][^\\/]+")


def is_windows_shaped(value: str) -> bool:
    """Whether *value* is a Windows path by its own shape, not by the host."""
    return bool(_DRIVE_RE.match(value) or _UNC_RE.match(value))


def parse_recorded_path(value: PurePath | str) -> PurePath:
    """Parse a recorded path into the flavour it was recorded in.

    Pure by construction: it never touches the filesystem, so a path from another
    operating system can be compared on this one. That is what makes the Windows
    branches testable without a Windows machine.
    """
    if isinstance(value, PurePath):
        return value
    text = str(value)
    return PureWindowsPath(text) if is_windows_shaped(text) else PurePosixPath(text)


def normalise_for_match(value: PurePath | str) -> PurePath:
    """Prepare a path for comparison, resolving it only when that is meaningful.

    A native-flavour path is put through ``Path.resolve()`` so that ``..``,
    symlinks and relative inputs are dealt with before comparison. A foreign path
    cannot be resolved -- there is no such file here -- and must not be, since
    ``Path()`` on the wrong flavour mangles ``C:\\repo\\src`` into a single
    meaningless component.
    """
    parsed = parse_recorded_path(value)
    if _is_native(parsed):
        try:
            return Path(str(parsed)).resolve()
        except OSError:
            # An unresolvable path (a deleted cwd, a permission wall) is still
            # comparable as written; refusing to compare would be worse.
            return parsed
    return parsed


def path_contains(root: PurePath | str, target: PurePath | str) -> bool:
    """Whether *target* is *root* or lies beneath it, in *root*'s flavour.

    Paths of differing flavours never match. See the module docstring: that is a
    considered refusal to guess at a WSL mount mapping, not an oversight.
    """
    root_path = parse_recorded_path(root)
    target_path = parse_recorded_path(target)
    if not _same_flavour(root_path, target_path):
        return False
    return target_path == root_path or target_path.is_relative_to(root_path)


def paths_equal(left: PurePath | str, right: PurePath | str) -> bool:
    """Whether two recorded roots name the same directory.

    Case-insensitive on Windows, case-sensitive on POSIX. Used where the registry
    would otherwise compare roots as raw strings and let one directory be
    registered twice under different casing -- which makes every subsequent read
    of that workspace ambiguous.
    """
    left_path = parse_recorded_path(left)
    right_path = parse_recorded_path(right)
    return _same_flavour(left_path, right_path) and left_path == right_path


def match_depth(root: PurePath | str) -> int:
    """Component count of *root*, for picking the most specific match.

    Flavour-aware because the flavours count differently: a UNC root's
    ``\\\\server\\share\\`` is a single anchor component, as is ``C:\\``.
    """
    return len(parse_recorded_path(root).parts)


def _same_flavour(left: PurePath, right: PurePath) -> bool:
    return isinstance(left, PureWindowsPath) is isinstance(right, PureWindowsPath)


def _is_native(path: PurePath) -> bool:
    """Whether *path*'s flavour matches the running host's."""
    return isinstance(path, PureWindowsPath) is _host_is_windows()


def _host_is_windows() -> bool:
    return isinstance(Path(), PureWindowsPath)
