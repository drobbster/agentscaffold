"""Scenario-level conftest: re-export session fixtures and generate report after run."""

from __future__ import annotations

from pathlib import Path

# Re-export fixtures from eval/conftest.py so pytest discovers them
from eval.conftest import baseline_config, fresh_sim, indexed_sim, sim_project_path  # noqa: F401


def pytest_sessionfinish(session, exitstatus):
    """Generate the evaluation report after all tests complete."""
    from eval.report import generate_report

    report_path = Path(__file__).parent.parent / "reports" / "latest.md"
    try:
        report = generate_report(output_path=report_path)
        if report and "No results" not in report:
            print(f"\n\nEval report written to: {report_path}")
    except Exception as exc:
        print(f"\nWarning: Could not generate report: {exc}")
