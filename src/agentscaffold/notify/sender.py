"""Notification sending (stdout, GitHub Issues, Slack)."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from rich.console import Console

from agentscaffold.config import ScaffoldConfig, load_config

console = Console()


def send_notification(event: str, message: str, config: Any = None) -> None:
    """Send a notification for the given event and message.

    Parameters
    ----------
    event:
        Event name (e.g. ``plan_complete``, ``escalation``).
    message:
        Human-readable notification body.
    config:
        Optional pre-loaded :class:`ScaffoldConfig`. Loaded from disk when
        ``None``.
    """
    if config is None:
        config = load_config()

    if not isinstance(config, ScaffoldConfig):
        console.print("[yellow]Warning: invalid config, falling back to defaults[/yellow]")
        config = ScaffoldConfig()

    notif = config.semi_autonomous.notifications
    if not notif.enabled:
        return

    if event not in notif.notify_on:
        return

    channel = notif.channel
    if channel == "stdout":
        _send_stdout(event, message)
    elif channel == "github_issue":
        _send_github_issue(event, message)
    elif channel == "slack":
        _send_slack(event, message, webhook_env=notif.slack_webhook_env)
    else:
        console.print(f"[yellow]Unknown notification channel: {channel}[/yellow]")
        _send_stdout(event, message)


def _send_stdout(event: str, message: str) -> None:
    console.print(f"[bold]Notification[/bold] [{event}]: {message}")


def _send_github_issue(event: str, message: str) -> None:
    try:
        result = subprocess.run(
            ["gh", "issue", "create", "--title", f"[{event}] {message[:80]}", "--body", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            console.print(f"[green]GitHub issue created:[/green] {url}")
        else:
            console.print(f"[yellow]gh issue create failed:[/yellow] {result.stderr.strip()}")
            _send_stdout(event, message)
    except FileNotFoundError:
        console.print("[yellow]gh CLI not installed -- falling back to stdout[/yellow]")
        _send_stdout(event, message)
    except subprocess.TimeoutExpired:
        console.print("[yellow]gh issue create timed out -- falling back to stdout[/yellow]")
        _send_stdout(event, message)


def _send_slack(event: str, message: str, webhook_env: str) -> None:
    webhook_url = os.environ.get(webhook_env)
    if not webhook_url:
        console.print(
            f"[yellow]Slack webhook env var {webhook_env} not set "
            f"-- falling back to stdout[/yellow]"
        )
        _send_stdout(event, message)
        return

    payload = json.dumps({"text": f"*[{event}]* {message}"}).encode()
    req = Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=15):
            console.print("[green]Slack notification sent[/green]")
    except (URLError, OSError) as exc:
        console.print(
            f"[yellow]Slack notification failed: {exc} -- falling back to stdout[/yellow]"
        )
        _send_stdout(event, message)
