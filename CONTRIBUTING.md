# Contributing

## Private data

This repository is public. Tests, fixtures, examples, and commit metadata use
synthetic data. Do not commit a home-directory path, a machine-local email
address, or text copied from a private project. The public package author name
is the one already in `pyproject.toml`.

## Local checks

Install the checks once per clone:

```bash
scripts/install_hooks.sh
```

The pre-commit hook scans what is staged. The pre-push hook scans the tree and
the commit messages you are about to publish. Either one failing stops the
command. Findings name the file, the line, and the rule. They do not repeat
the text that matched.

The maintainer list of private literals is not in this repository. Keep it at
`~/.config/agentscaffold/public-content-denylist.txt`, or set
`PUBLIC_CONTENT_DENYLIST_FILE` to wherever you keep it. Without that file the
hooks still enforce the generic rules.

Pull requests to `staging` and `main` run the same scan, and that run fails
closed when the private list is not configured.
