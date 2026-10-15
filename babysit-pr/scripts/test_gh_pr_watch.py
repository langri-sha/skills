# Modified from openai/codex .codex/skills/babysit-pr at 5e96aabd68dc; see NOTICE.
import argparse
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("gh_pr_watch.py")
MODULE_SPEC = importlib.util.spec_from_file_location("gh_pr_watch", MODULE_PATH)
gh_pr_watch = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(gh_pr_watch)


def sample_pr():
    return {
        "number": 123,
        "url": "https://github.com/openai/codex/pull/123",
        "repo": "openai/codex",
        "head_sha": "abc123",
        "head_branch": "feature",
        "state": "OPEN",
        "merged": False,
        "closed": False,
        "mergeable": "MERGEABLE",
        "merge_state_status": "CLEAN",
        "review_decision": "",
    }


def sample_checks(**overrides):
    checks = {
        "pending_count": 0,
        "failed_count": 0,
        "passed_count": 12,
        "all_terminal": True,
    }
    checks.update(overrides)
    return checks


def test_collect_snapshot_fetches_review_items_before_ci(monkeypatch, tmp_path):
    call_order = []
    pr = sample_pr()

    monkeypatch.setattr(gh_pr_watch, "resolve_pr", lambda *args, **kwargs: pr)
    monkeypatch.setattr(gh_pr_watch, "load_state", lambda path: ({}, True))
    monkeypatch.setattr(
        gh_pr_watch,
        "get_authenticated_login",
        lambda: call_order.append("auth") or "octocat",
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "fetch_new_review_items",
        lambda *args, **kwargs: call_order.append("review") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "get_pr_checks",
        lambda *args, **kwargs: call_order.append("checks") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "summarize_checks",
        lambda checks: call_order.append("summarize") or sample_checks(),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "get_workflow_runs_for_sha",
        lambda *args, **kwargs: call_order.append("workflow") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "failed_runs_from_workflow_runs",
        lambda *args, **kwargs: call_order.append("failed_runs") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "failed_jobs_from_workflow_runs",
        lambda *args, **kwargs: call_order.append("failed_jobs") or [],
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "recommend_actions",
        lambda *args, **kwargs: call_order.append("recommend") or ["idle"],
    )
    monkeypatch.setattr(gh_pr_watch, "save_state", lambda *args, **kwargs: None)

    args = argparse.Namespace(
        pr="123",
        repo=None,
        state_file=str(tmp_path / "watcher-state.json"),
        max_flaky_retries=3,
    )

    gh_pr_watch.collect_snapshot(args)

    assert call_order.index("review") < call_order.index("checks")
    assert call_order.index("review") < call_order.index("workflow")


def test_default_state_file_lives_in_the_system_temp_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(gh_pr_watch.tempfile, "gettempdir", lambda: str(tmp_path))

    assert gh_pr_watch.default_state_file_for(sample_pr()) == (
        tmp_path / "babysit-pr-openai-codex-pr123.json"
    )


def test_recommend_actions_prioritizes_review_comments():
    actions = gh_pr_watch.recommend_actions(
        sample_pr(),
        sample_checks(failed_count=1),
        [{"run_id": 99}],
        [],
        [{"kind": "review_comment", "id": "1"}],
        0,
        3,
    )

    assert actions == [
        "process_review_comment",
        "diagnose_ci_failure",
        "retry_failed_checks",
    ]


def test_pending_review_feedback_surfaces_only_after_publication(monkeypatch):
    state = {
        "seen_review_comment_ids": ["20"],
        "seen_review_ids": ["10"],
    }
    review = {
        "id": 10,
        "user": {"login": "octocat"},
        "author_association": "MEMBER",
        "state": "PENDING",
        "body": "Please rename this.",
        "created_at": "2026-06-08T10:00:00Z",
        "submitted_at": None,
        "html_url": "https://github.com/openai/codex/pull/123#pullrequestreview-10",
    }
    review_comment = {
        "id": 20,
        "pull_request_review_id": 10,
        "user": {"login": "octocat"},
        "author_association": "MEMBER",
        "body": "Please rename this.",
        "created_at": "2026-06-08T10:00:00Z",
        "path": "src/example.rs",
        "line": 7,
        "html_url": "https://github.com/openai/codex/pull/123#discussion_r20",
    }

    def fake_list(endpoint, **kwargs):
        if endpoint.endswith("/issues/123/comments"):
            return []
        if endpoint.endswith("/pulls/123/comments"):
            return [review_comment]
        if endpoint.endswith("/pulls/123/reviews"):
            return [review]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(gh_pr_watch, "gh_api_list_paginated", fake_list)

    assert (
        gh_pr_watch.fetch_new_review_items(
            sample_pr(),
            state,
            fresh_state=True,
            authenticated_login="octocat",
        )
        == []
    )
    assert state["seen_review_comment_ids"] == []
    assert state["seen_review_ids"] == []

    review["state"] = "COMMENTED"
    review["submitted_at"] = "2026-06-08T10:05:00Z"

    published_items = gh_pr_watch.fetch_new_review_items(
        sample_pr(),
        state,
        fresh_state=False,
        authenticated_login="octocat",
    )

    assert {(item["kind"], item["id"]) for item in published_items} == {
        ("review", "10"),
        ("review_comment", "20"),
    }
    assert state["seen_review_comment_ids"] == ["20"]
    assert state["seen_review_ids"] == ["10"]


def test_run_watch_keeps_polling_open_ready_to_merge_pr(monkeypatch):
    sleeps = []
    events = []
    snapshot = {
        "pr": sample_pr(),
        "checks": sample_checks(),
        "failed_runs": [],
        "failed_jobs": [],
        "new_review_items": [],
        "actions": ["ready_to_merge"],
        "retry_state": {
            "current_sha_retries_used": 0,
            "max_flaky_retries": 3,
        },
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (snapshot, Path("/tmp/codex-babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )

    class StopWatch(Exception):
        pass

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise StopWatch

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)

    with pytest.raises(StopWatch):
        gh_pr_watch.run_watch(
            argparse.Namespace(poll_seconds=30, changes_only=False, heartbeat_polls=10)
        )

    assert sleeps == [30, 30]
    assert [event for event, _ in events] == ["snapshot", "snapshot"]


def watch_snapshot(
    actions=("idle",),
    head_sha="abc123",
    failed_job_ids=(),
    review_item_ids=(),
    **pr_overrides,
):
    pr = sample_pr()
    pr.update(head_sha=head_sha, **pr_overrides)
    return {
        "pr": pr,
        "checks": sample_checks(pending_count=1, all_terminal=False),
        "failed_runs": [],
        "failed_jobs": [{"job_id": job_id} for job_id in failed_job_ids],
        "new_review_items": [
            {"kind": "review_comment", "id": item_id} for item_id in review_item_ids
        ],
        "actions": list(actions),
        "retry_state": {"current_sha_retries_used": 0, "max_flaky_retries": 3},
    }


class WatchStopped(Exception):
    pass


def run_changes_only_watch(monkeypatch, snapshots, polls, heartbeat_polls=2):
    events = []
    feed = iter(snapshots)
    sleeps = []

    monkeypatch.setattr(
        gh_pr_watch,
        "collect_snapshot",
        lambda args: (next(feed), Path("/tmp/babysit-pr-state.json")),
    )
    monkeypatch.setattr(
        gh_pr_watch,
        "print_event",
        lambda event, payload: events.append((event, payload)),
    )

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= polls:
            raise WatchStopped

    monkeypatch.setattr(gh_pr_watch.time, "sleep", fake_sleep)
    args = argparse.Namespace(
        poll_seconds=30, changes_only=True, heartbeat_polls=heartbeat_polls
    )
    try:
        result = gh_pr_watch.run_watch(args)
    except WatchStopped:
        result = None
    return result, events


def test_changes_only_watch_replaces_unchanged_snapshots_with_heartbeats(
    monkeypatch,
):
    _, events = run_changes_only_watch(
        monkeypatch, [watch_snapshot() for _ in range(5)], polls=5
    )

    assert [event for event, _ in events] == ["snapshot", "heartbeat", "heartbeat"]
    assert events[1][1] == {
        "pr": 123,
        "head_sha": "abc123",
        "actions": ["idle"],
        "next_poll_seconds": 30,
    }


def test_changes_only_watch_emits_snapshot_when_state_changes(monkeypatch):
    _, events = run_changes_only_watch(
        monkeypatch,
        [
            watch_snapshot(),
            watch_snapshot(),
            watch_snapshot(head_sha="def456"),
            watch_snapshot(actions=("process_review_comment",), head_sha="def456"),
        ],
        polls=4,
        heartbeat_polls=10,
    )

    assert [event for event, _ in events] == ["snapshot", "snapshot", "snapshot"]
    assert [payload["snapshot"]["pr"]["head_sha"] for _, payload in events] == [
        "abc123",
        "def456",
        "def456",
    ]


def test_changes_only_watch_emits_each_batch_of_new_review_items(monkeypatch):
    reviewing = ("process_review_comment",)
    _, events = run_changes_only_watch(
        monkeypatch,
        [
            watch_snapshot(actions=reviewing, review_item_ids=("1",)),
            watch_snapshot(actions=reviewing, review_item_ids=("2",)),
        ],
        polls=2,
        heartbeat_polls=10,
    )

    assert [
        [item["id"] for item in payload["snapshot"]["new_review_items"]]
        for _, payload in events
    ] == [["1"], ["2"]]


def test_changes_only_watch_emits_snapshot_when_another_job_fails(monkeypatch):
    failing = ("diagnose_ci_failure",)
    _, events = run_changes_only_watch(
        monkeypatch,
        [
            watch_snapshot(actions=failing, failed_job_ids=(555,)),
            watch_snapshot(actions=failing, failed_job_ids=(555, 556)),
        ],
        polls=2,
        heartbeat_polls=10,
    )

    assert [event for event, _ in events] == ["snapshot", "snapshot"]


def test_changes_only_watch_stops_with_final_snapshot_when_pr_closes(monkeypatch):
    closed = watch_snapshot(actions=("stop_pr_closed",), closed=True, state="CLOSED")
    result, events = run_changes_only_watch(
        monkeypatch, [watch_snapshot(), watch_snapshot(), closed], polls=5
    )

    assert result == 0
    assert [event for event, _ in events] == ["snapshot", "snapshot", "stop"]
    assert events[1][1]["snapshot"]["actions"] == ["stop_pr_closed"]


def test_failed_jobs_include_direct_logs_endpoint(monkeypatch):
    jobs_by_run = {
        99: [
            {
                "id": 555,
                "name": "unit tests",
                "status": "completed",
                "conclusion": "failure",
                "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
            },
            {
                "id": 556,
                "name": "lint",
                "status": "completed",
                "conclusion": "success",
            },
        ]
    }

    monkeypatch.setattr(
        gh_pr_watch,
        "get_jobs_for_run",
        lambda repo, run_id: jobs_by_run[run_id],
    )

    failed_jobs = gh_pr_watch.failed_jobs_from_workflow_runs(
        "openai/codex",
        [
            {
                "id": 99,
                "name": "CI",
                "status": "in_progress",
                "conclusion": "",
                "head_sha": "abc123",
            }
        ],
        "abc123",
    )

    assert failed_jobs == [
        {
            "run_id": 99,
            "workflow_name": "CI",
            "run_status": "in_progress",
            "run_conclusion": "",
            "job_id": 555,
            "job_name": "unit tests",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/openai/codex/actions/runs/99/job/555",
            "logs_endpoint": "repos/openai/codex/actions/jobs/555/logs",
        }
    ]
