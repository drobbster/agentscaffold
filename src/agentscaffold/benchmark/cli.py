"""Typer command group for `scaffold benchmark`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agentscaffold.benchmark.doctor import CheckStatus, DoctorReport, run_doctor
from agentscaffold.benchmark.metrics import load_summary
from agentscaffold.benchmark.models import BUILTIN_MODELS, DEFAULT_MODEL, BenchmarkModel, get_model
from agentscaffold.benchmark.report import BenchmarkComparison, compare_summary, render_markdown
from agentscaffold.benchmark.runner import (
    BenchmarkRunRequest,
    DryRunPlan,
    build_dry_run_plan,
    run_benchmark,
    validate_live_request,
)

app = typer.Typer(
    help="Live AgentScaffold benchmark tools. Live runs are opt-in and cost bounded.",
    no_args_is_help=True,
)
console = Console()


@app.command("doctor")
def doctor(
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help="Benchmark model config to check.",
    ),
    live: bool = typer.Option(
        False,
        "--live",
        help="Require live-run checks, including API key presence.",
    ),
) -> None:
    """Check whether the benchmark environment is ready."""

    selected_model = _resolve_model(model)
    report = run_doctor(model=selected_model, require_api_key=live)
    _print_doctor_report(report)
    if not report.ok:
        raise typer.Exit(1)


@app.command("run")
def run(
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help="Benchmark model config to use.",
    ),
    task_slice: str = typer.Option(
        "0:1",
        "--task-slice",
        help="Task slice to run, Python slice syntax.",
    ),
    max_cost_usd: float | None = typer.Option(
        None,
        "--max-cost-usd",
        help="Maximum live LLM spend in USD. Required unless --dry-run is set.",
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        "-w",
        help="Parallel workers for live task execution.",
    ),
    seeds: int = typer.Option(
        1,
        "--seeds",
        help="Number of seeds per task/model arm.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve and print the run plan without starting containers or model calls.",
    ),
    confirm_live: bool = typer.Option(
        False,
        "--confirm-live",
        help="Required to start live model calls.",
    ),
    output: Path = typer.Option(
        Path(".scaffold/benchmark/results/latest"),
        "--output",
        "-o",
        help="Output directory for live benchmark results.",
    ),
) -> None:
    """Run or plan an AgentScaffold benchmark."""

    selected_model = _resolve_model(model)
    request = BenchmarkRunRequest(
        model=selected_model,
        task_slice=task_slice,
        max_cost_usd=max_cost_usd,
        workers=workers,
        seeds=seeds,
        dry_run=dry_run,
        confirm_live=confirm_live,
    )
    report = run_doctor(
        model=selected_model,
        require_api_key=request.live_requested,
        require_docker=request.live_requested,
        require_live_dependencies=request.live_requested,
    )
    errors = validate_live_request(request, report)
    if errors:
        for error in errors:
            console.print(f"[red]Error:[/red] {error}")
        raise typer.Exit(1)

    if dry_run:
        plan = build_dry_run_plan(request, report)
        _print_dry_run(plan)
        return

    try:
        summary = run_benchmark(
            request=request,
            package_root=Path.cwd(),
            output_dir=output,
            doctor_report=report,
        )
    except RuntimeError as exc:
        console.print(f"[red]Live benchmark did not start:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"[green]Benchmark summary written to {output / 'summary.json'}[/green]")
    console.print(f"Run ID: {summary.run_id}")


@app.command("models")
def models() -> None:
    """List built-in benchmark model configs."""

    table = Table(title="Benchmark Models")
    table.add_column("Name", style="bold")
    table.add_column("Model ID")
    table.add_column("Provider")
    table.add_column("API Key Env")
    table.add_column("Pricing")
    for item in BUILTIN_MODELS.values():
        table.add_row(
            item.name,
            item.model_id,
            item.provider,
            item.api_key_env,
            item.pricing_source,
        )
    console.print(table)


@app.command("compare")
def compare(
    results: Path = typer.Argument(..., help="Benchmark summary JSON file or result directory."),
) -> None:
    """Compare benchmark result directories."""

    comparison = _load_comparison(results)
    table = Table(title=f"Benchmark Compare: {comparison.summary.run_id}")
    table.add_column("Arm", style="bold")
    table.add_column("Runs")
    table.add_column("Pass Rate")
    table.add_column("Defect Caught")
    table.add_column("Total Cost")
    table.add_column("API Calls")
    table.add_column("Scaffold Tools")
    for aggregate in comparison.aggregates:
        table.add_row(
            aggregate.arm,
            str(aggregate.total_runs),
            _pct(aggregate.pass_rate),
            _optional_pct(aggregate.defect_caught_rate),
            _optional_money(aggregate.total_cost_usd),
            str(aggregate.total_api_calls),
            str(aggregate.scaffold_tool_calls),
        )
    console.print(table)


@app.command("report")
def report(
    results: Path = typer.Argument(..., help="Benchmark summary JSON file or result directory."),
) -> None:
    """Render a benchmark report."""

    comparison = _load_comparison(results)
    console.print(render_markdown(comparison))


def _resolve_model(name: str) -> BenchmarkModel:
    try:
        return get_model(name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def _print_doctor_report(report: DoctorReport) -> None:
    table = Table(title="Benchmark Doctor")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Required")
    table.add_column("Message")
    for check in report.checks:
        color = {
            CheckStatus.PASS: "green",
            CheckStatus.WARN: "yellow",
            CheckStatus.FAIL: "red",
        }[check.status]
        table.add_row(
            check.name,
            f"[{color}]{check.status.value}[/{color}]",
            "yes" if check.required else "no",
            check.message,
        )
    console.print(table)


def _print_dry_run(plan: DryRunPlan) -> None:
    request = plan.request
    console.print(
        "[bold green]Benchmark dry-run only; no containers or model calls started.[/bold green]"
    )
    console.print(f"Model: {request.model.name} ({request.model.model_id})")
    console.print(f"Pricing source: {request.model.pricing_source}")
    console.print(f"Task slice: {request.task_slice}")
    console.print(f"Arms: {', '.join(plan.arms)}")
    console.print(f"Seeds: {request.seeds}")
    console.print(f"Workers: {request.workers}")
    console.print(
        f"Max cost USD: {request.max_cost_usd if request.max_cost_usd is not None else 'not set'}"
    )
    console.print("Live calls: no")


def _load_comparison(path: Path) -> BenchmarkComparison:
    try:
        return compare_summary(load_summary(path))
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        console.print(f"[red]Unable to load benchmark results:[/red] {exc}")
        raise typer.Exit(1) from exc


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _optional_pct(value: float | None) -> str:
    return "n/a" if value is None else _pct(value)


def _optional_money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"
