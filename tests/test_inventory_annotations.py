"""Inventory annotations: compose labels, Prefect tags and workflow comments (contract v2)."""

from __future__ import annotations

from agentscaffold.inventory.collectors import (
    read_compose,
    read_github_workflow,
    read_prefect,
)


def test_compose_labels_in_map_form() -> None:
    text = """
services:
  api:
    image: x
    labels:
      agentscaffold.owner_plan: "150"
      agentscaffold.layer: 5
      agentscaffold.roadmap_stage: "3"
      com.example.team: platform
"""
    (api,) = read_compose("compose.yaml", text)
    assert api.annotations == {"owner_plan": "150", "layer": "5", "roadmap_stage": "3"}


def test_compose_labels_in_list_form() -> None:
    text = """
services:
  api:
    image: x
    labels:
      - agentscaffold.owner_plan=150
      - agentscaffold.unknown=1
      - not-a-pair
"""
    (api,) = read_compose("compose.yaml", text)
    assert api.annotations == {"owner_plan": "150"}


def test_prefect_tags() -> None:
    text = """
deployments:
  - name: j
    entrypoint: flows/j.py:j
    tags: [plan:080, "layer:4", stage:5, nightly, "team:data", 3]
"""
    (job,) = read_prefect("prefect.yaml", text)
    assert job.annotations == {"owner_plan": "080", "layer": "4", "roadmap_stage": "5"}


def test_workflow_comment_line() -> None:
    text = "# agentscaffold: owner_plan=212 layer=cross-cutting\non: push\njobs: {}\n"
    (workflow,) = read_github_workflow(".github/workflows/ci.yml", text)
    assert workflow.annotations == {"owner_plan": "212", "layer": "cross-cutting"}


def test_no_annotations_is_an_empty_mapping() -> None:
    (api,) = read_compose("compose.yaml", "services:\n  api: {image: x, labels: [a=b]}\n")
    assert api.annotations == {}
    (workflow,) = read_github_workflow(".github/workflows/ci.yml", "on: push\n")
    assert workflow.annotations == {}


def test_empty_annotation_values_are_ignored() -> None:
    text = "services:\n  api:\n    image: x\n    labels: {agentscaffold.owner_plan: ''}\n"
    (api,) = read_compose("compose.yaml", text)
    assert api.annotations == {}
