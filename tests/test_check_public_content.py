"""The public-content scanner and the hooks that run it.

Bad examples are built by concatenation so this file does not itself contain a
home path or a machine-local address.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_public_content.py"
INSTALL = ROOT / "scripts" / "install_hooks.sh"

_spec = importlib.util.spec_from_file_location("check_public_content", SCRIPT)
assert _spec is not None and _spec.loader is not None
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)


def _home(name: str) -> str:
    return "/Users/" + name + "/repo"


def _email(local: str) -> str:
    return local + "@" + "buildbox.local"


def _run(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    stdin: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    base = {
        key: value for key, value in os.environ.items() if not key.startswith("PUBLIC_CONTENT_")
    }
    if env:
        base.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        env=base,
        input=stdin,
        check=False,
    )


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@users.noreply.github.com")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")


def _venv_python(repo: Path) -> None:
    bindir = repo / ".venv" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "python").symlink_to(sys.executable)


def _install_hooks(repo: Path) -> None:
    scripts = repo / "scripts"
    (scripts / "hooks").mkdir(parents=True)
    for name in ("pre-commit", "pre-push"):
        target = scripts / "hooks" / name
        target.write_bytes((ROOT / "scripts" / "hooks" / name).read_bytes())
        target.chmod(0o755)
    scanner = scripts / "check_public_content.py"
    scanner.write_bytes(SCRIPT.read_bytes())
    installer = scripts / "install_hooks.sh"
    installer.write_bytes(INSTALL.read_bytes())
    installer.chmod(0o755)
    result = subprocess.run(
        ["sh", "scripts/install_hooks.sh"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_placeholder_home_paths_are_allowed() -> None:
    samples = [
        "/Users/" + "alice/proj",
        "/home/" + "dev/proj",
        "/home/" + "runner/work",
        "/Users/" + "someone/notes",
        "/home/" + "you/x",
        "/Users/" + "me/x",
        "/home/" + "user/x",
        "/Users/" + "example/x",
        "/home/" + "bob/x",
    ]
    # The concatenations above still form a real path in the runtime string,
    # which is what we scan. The placeholder names must not be reported.
    assert scan.scan_text("\n".join(samples), "f.txt", [], []) == []


def test_real_home_path_and_local_email_are_reported_without_the_text() -> None:
    secret_home = _home("notaplaceholder")
    secret_email = _email("dev")
    text = f"see {secret_home} and {secret_email}\n"
    findings = scan.scan_text(text, "notes.md", [], [])
    rendered = "\n".join(findings)
    assert findings == ["notes.md:1: home-path", "notes.md:1: local-email"]
    assert "notaplaceholder" not in rendered
    assert "buildbox" not in rendered
    assert secret_email not in rendered


def test_noreply_and_ordinary_email_are_allowed() -> None:
    text = "a@users.noreply.github.com\na@example.com\n"
    assert scan.scan_text(text, "f.txt", [], []) == []


def test_private_literals_are_case_insensitive_and_not_echoed() -> None:
    findings = scan.scan_text("see ZZ-Secret-Token here\n", "f.txt", ["zz-secret-token"], [])
    assert findings == ["f.txt:1: private-literal"]
    assert "secret" not in findings[0].casefold()


def test_short_literals_are_rejected() -> None:
    with pytest.raises(ValueError, match="shorter than 4"):
        scan.parse_literals("ab\n")


def test_comments_and_blanks_are_skipped() -> None:
    assert scan.parse_literals("# comment\n\n  \nzz-token\nzz-token\n") == ["zz-token"]


def test_literals_load_from_the_environment_and_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = tmp_path / "list.txt"
    listed.write_text("# note\nfrom-file\n", encoding="utf-8")
    monkeypatch.setenv("PUBLIC_CONTENT_DENYLIST", "from-env\n")
    monkeypatch.setenv("PUBLIC_CONTENT_DENYLIST_FILE", str(listed))
    assert scan.load_private_literals() == ["from-env", "from-file"]


def test_missing_literal_file_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PUBLIC_CONTENT_DENYLIST", raising=False)
    monkeypatch.setenv("PUBLIC_CONTENT_DENYLIST_FILE", str(tmp_path / "missing.txt"))
    with pytest.raises(ValueError, match="cannot be read"):
        scan.load_private_literals()


def test_derived_home_and_email(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scan, "home_directory", lambda: "/opt/" + "notaplaceholder")
    monkeypatch.setattr(scan, "git_email", lambda _repo: "person@example.com")
    derived = scan.derived_terms(tmp_path)
    text = "cache /opt/" + "notaplaceholder/x and person@example.com\n"
    findings = scan.scan_text(text, "f.txt", [], derived)
    rendered = "\n".join(findings)
    assert "home-directory" in rendered
    assert "git-email" in rendered
    assert "notaplaceholder" not in rendered
    assert "person@example.com" not in rendered


def test_derived_home_skips_placeholders_and_noreply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(scan, "home_directory", lambda: "/home/" + "runner")
    monkeypatch.setattr(scan, "git_email", lambda _repo: "me@users.noreply.github.com")
    assert scan.derived_terms(tmp_path) == []


def test_binary_input_is_skipped() -> None:
    assert scan.scan_bytes(b"a\0" + _home("notaplaceholder").encode(), "bin", [], []) == []


def test_require_private_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path, "--stdin", "--require-private", stdin=b"hello\n")
    assert result.returncode == 2
    assert b"hello" not in result.stdout
    assert b"private list is required" in result.stderr


def test_stdin_reports_a_hit_without_echoing_it(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--stdin",
        env={"PUBLIC_CONTENT_DENYLIST": "zz-secret-token"},
        stdin=b"zz-secret-token\n",
    )
    assert result.returncode == 1
    assert result.stdout.decode() == "stdin:1: private-literal\n"
    assert b"zz-secret-token" not in result.stdout


def test_staged_scans_the_index_not_the_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "a.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "a.txt").write_text(_home("notaplaceholder") + "\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("edited back\n", encoding="utf-8")
    result = _run(repo, "--staged", "--repo", str(repo))
    assert result.returncode == 1
    assert b"home-path" in result.stdout
    assert b"notaplaceholder" not in result.stdout
    _git(repo, "add", "a.txt")
    assert _run(repo, "--staged", "--repo", str(repo)).returncode == 0


def test_rev_and_messages(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "a.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "clean")
    (repo / "a.txt").write_text(_home("notaplaceholder") + "\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": _email("dev"),
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": _email("dev"),
        }
    )
    committed = subprocess.run(
        ["git", "commit", "-m", "add a path"],
        cwd=repo,
        capture_output=True,
        env=env,
        check=False,
    )
    assert committed.returncode == 0, committed.stderr
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    rev = _run(repo, "--rev", tip, "--repo", str(repo))
    assert rev.returncode == 1
    assert b"home-path" in rev.stdout
    assert b"notaplaceholder" not in rev.stdout
    messages = _run(repo, "--messages", "HEAD", "--not-remotes", "--repo", str(repo))
    assert messages.returncode == 1
    assert b"local-email" in messages.stdout
    assert b"buildbox" not in messages.stdout


def test_dist_archives(tmp_path: Path) -> None:
    payload = (_home("notaplaceholder") + "\n").encode()
    wheel = tmp_path / "demo.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/mod.py", payload)
    sdist = tmp_path / "demo.tar.gz"
    source = tmp_path / "mod.py"
    source.write_bytes(payload)
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source, arcname="demo/mod.py")
    result = _run(tmp_path, "--dist", str(wheel), str(sdist))
    assert result.returncode == 1
    rendered = result.stdout.decode()
    assert rendered.count("home-path") == 2
    assert "notaplaceholder" not in rendered


def test_hooks_block_a_commit_and_a_push_and_chain(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    _venv_python(repo)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    previous = hooks / "pre-commit"
    previous.write_text("#!/bin/sh\necho chained >> chained.txt\n", encoding="utf-8")
    previous.chmod(0o755)
    _install_hooks(repo)
    assert (hooks / "pre-commit.local").is_file()
    assert "AGENTSCAFFOLD PUBLIC CONTENT HOOK" in (hooks / "pre-commit").read_text(encoding="utf-8")

    (repo / "ok.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "ok.txt")
    _git(repo, "commit", "-m", "clean")
    assert (repo / "chained.txt").read_text(encoding="utf-8") == "chained\n"

    (repo / "bad.txt").write_text(_home("notaplaceholder") + "\n", encoding="utf-8")
    _git(repo, "add", "bad.txt")
    blocked = _git(repo, "commit", "-m", "bad", check=False)
    assert blocked.returncode != 0
    combined = blocked.stdout + blocked.stderr
    assert "home-path" in combined
    assert "notaplaceholder" not in combined
    assert _git(repo, "log", "--oneline").stdout.count("\n") == 1

    _git(repo, "commit", "--no-verify", "-m", "slipped")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    pushed = _git(repo, "push", "origin", "HEAD:refs/heads/main", check=False)
    assert pushed.returncode != 0
    assert "notaplaceholder" not in pushed.stdout + pushed.stderr


def test_install_refuses_to_clobber_a_chained_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (hooks / "pre-commit.local").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    scripts = repo / "scripts" / "hooks"
    scripts.mkdir(parents=True)
    for name in ("pre-commit", "pre-push"):
        target = scripts / name
        target.write_bytes((ROOT / "scripts" / "hooks" / name).read_bytes())
    installer = repo / "scripts" / "install_hooks.sh"
    installer.write_bytes(INSTALL.read_bytes())
    result = subprocess.run(
        ["sh", str(installer)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "leaving them alone" in result.stderr
