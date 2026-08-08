# Releasing AgentScaffold

## The order, and why it is not negotiable

```
feature/* or bugfix/*  ->  staging  ->  main  ->  tag  ->  PyPI
```

`staging` is a **pre-release integration gate**. Work lands there, integrates with
everything else already waiting, and soaks. `main` is what has been released.

The direction matters more than it looks. If a release reaches `main` before
`staging` has seen it, staging has not gated anything — it has become a mirror
that receives what was already published, and the question "has this soaked with
the other pending changes?" can no longer be asked, because the answer arrives
after the artifact is on PyPI and cannot be recalled.

**The rule that keeps this honest:** never tag or publish content that `staging`
has not seen.

```bash
# Must print OK. If it does not, main holds something staging never saw.
[ "$(git rev-parse main^{tree})" = "$(git rev-parse origin/staging^{tree})" ] \
  && echo "OK: main's content is exactly staging's"
```

Compare **trees**, not commits. The obvious phrasing — is this commit reachable
from `staging`? — cannot work here: merging `staging` into `main` creates a new
merge commit that by definition exists only on `main`, so the check fails on a
perfectly correct release. A check that fails on everything is not a check, and
would be switched off the first time it blocked a good release.

The tree comparison asks the question actually worth asking: does `main` contain
any content that did not come through `staging`? Verified to discriminate in both
directions on a scratch repository — it passes a staging-merged release and fails
a commit made straight to `main`.

## Steps

### 1. Land the work on staging

```bash
git checkout -b feature/NNN-short-description
# ... work, commit ...
git push -u origin feature/NNN-short-description
gh pr create --base staging --head feature/NNN-short-description
```

The PR base is **`staging`**, not `main`. Merge it once the full suite passes.

### 2. Let it soak

Nothing to run. This is the step that gives the gate its value: other pending work
merges alongside, and integration problems that no single branch's test run would
catch surface here rather than in a published artifact.

### 3. Cut the release branch from staging

```bash
git checkout -b release/agentscaffold-X.Y.Z origin/staging
```

From `origin/staging`. Cutting from `main` reintroduces exactly the inversion this
document exists to prevent.

### 4. Bump the version in all three places

| File | What |
|---|---|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `src/agentscaffold/__init__.py` | `__version__ = "X.Y.Z"` |
| `uv.lock` | Regenerates; run any `uv` command, or `uv lock` |

```bash
rg -n '^version|^__version__' pyproject.toml src/agentscaffold/__init__.py
```

All three must agree. A wheel whose `__version__` disagrees with its metadata is
confusing in exactly the situation where you least want confusion.

### 5. Date the changelog

Convert `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and leave a fresh empty
`## [Unreleased]` above it. Remove any "not yet cut" note.

Every user-visible change needs an entry. A shipped feature with no changelog line
is a feature nobody will discover. Before cutting, check the release's plans for
new CLI flags, new tools, and behaviour changes, and confirm each has one.

**Anything requiring action on upgrade goes at the top of the section**, not buried
in a list — a graph rebuild, a migration, a deprecation.

### 6. Verify, then commit

```bash
uv run ruff format . && uv run ruff check .
uv run pytest -q
```

```bash
git commit -m "Release agentscaffold X.Y.Z"
git push -u origin release/agentscaffold-X.Y.Z
gh pr create --base staging --head release/agentscaffold-X.Y.Z
```

This PR's base is **`staging`**, not `main`.

That is easy to get wrong, and the first cut following this document did. The
release branch is cut *from* staging, so it is tempting to treat it as already
gated and promote it straight to `main`. But step 4 and step 5 add a commit —
the version bump and the dated changelog — and that commit is the one that gets
tagged. Basing this PR on `main` means the tagged commit is the single commit in
the release that `staging` never saw, and step 7's check fails by construction.

### 7. Promote staging to main

```bash
gh pr create --base main --head staging --title "Promote staging to main for X.Y.Z"
```

Then confirm the gate before tagging:

```bash
git checkout main && git pull --ff-only
[ "$(git rev-parse main^{tree})" = "$(git rev-parse origin/staging^{tree})" ] \
  && echo "OK: staging saw this" || echo "STOP: main has content staging never saw"
```

If that fails, the release skipped the gate. Do not tag. Work out how it was
bypassed rather than tagging anyway — the check is only worth having if it is
allowed to stop a release.

### 8. Tag

```bash
git tag -a vX.Y.Z -m "agentscaffold X.Y.Z

<one paragraph: what shipped and anything users must do on upgrade>"
git push origin vX.Y.Z
```

### 9. Build and smoke-test the artifact before publishing

```bash
rm -rf dist/ && uv build
```

Install the built wheel into a throwaway environment and exercise the release's
headline changes — not just `--version`, which passes for a wheel that is broken in
every way that matters.

```bash
uv venv /tmp/verify && VIRTUAL_ENV=/tmp/verify uv pip install dist/agentscaffold-X.Y.Z-py3-none-any.whl
/tmp/verify/bin/scaffold --version
# then: import and call the things this release changed
```

### 10. Publish

`uv publish` expects trusted publishing or configured credentials and currently has
neither here, so use twine:

```bash
uv run --with twine twine upload dist/agentscaffold-X.Y.Z*
```

### 11. Verify from PyPI, not from the upload message

A successful upload says the bytes arrived, not that the package installs.

```bash
uv venv /tmp/pypicheck
VIRTUAL_ENV=/tmp/pypicheck uv pip install --no-cache "agentscaffold==X.Y.Z"
/tmp/pypicheck/bin/scaffold --version
```

The index takes a moment to propagate; a resolution failure in the first few
seconds means "not yet", not "broken". Retry before concluding anything.

### 12. Record it

In the governance repo, add the release to the **Recently Released** section of
`docs/ai/state/workflow_state.md`: what shipped, the tag, and any upgrade action.

## Why this document exists

The convention drifted. At 0.9.2 the flow was correct — PR #40 merged `staging` into
`main`. From 0.9.3 through 0.10.0 it inverted: the release branch went straight to
`main`, was tagged and published, and a `chore/sync-staging-*` branch afterwards
pushed main's state back down to staging. Five releases went out with staging
gating nothing, and no content diverged, so nothing ever failed loudly enough to
prompt a question.

It drifted because it was never written down. The only record of "how we release"
was the shape of git history, and git history reads as precedent rather than as a
decision — each release copied the last, including the mistake. That is the whole
reason this file is in the repository root instead of in someone's memory.

There is no `chore/sync-staging-*` step in the process above. Under the correct
order it cannot be needed: `staging` is already ahead of `main` by construction. If
you ever find yourself wanting to sync staging *from* main, something upstream went
in the wrong direction — fix that rather than papering over it.

## The first cut under this document found two holes in it

0.10.1 was the first release to follow these steps, and it did not survive them
unchanged.

**Step 6 named the wrong base.** It said to PR the release branch to `main`. But
steps 4 and 5 add a commit *after* the branch is cut from staging — the version
bump and the dated changelog — and that commit is the one that gets tagged.
Basing the PR on `main` leaves it as the single commit in the release that
`staging` never saw. Subtle, because the release branch really is cut from
staging, so it looks gated; only the commit that matters is not.

**The gate check itself was unrunnable.** It asked whether the commit being
tagged is reachable from `staging`. Merging `staging` into `main` creates a merge
commit that exists only on `main`, so the check failed on a completely correct
release. It had been written to express an invariant already believed to hold,
and was never run against a merge-based promotion, so its failure mode went
unnoticed until the release it was meant to protect.

That is the more instructive of the two. A check that says no to everything looks
exactly like a strict check right up to the moment you need to trust it, and the
natural response to one blocking a release you know is good is to stop running
it. The replacement compares trees, and was verified on a scratch repository to
pass a staging-merged release *and* fail a commit made straight to `main` — both
directions, before being written down. The original was only ever confirmed in
the direction that agreed with it.
