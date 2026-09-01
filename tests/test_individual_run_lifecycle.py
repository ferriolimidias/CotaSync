from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import tests  # noqa: F401

from backend.db import Run as DbRun, SessionLocal
from backend.schemas.actions import ActionDetail
from backend.schemas.runs import ActionRunRequest, RunRecord
from backend.services.action_runner import finish_action_run, schedule_finish_action_run
from backend.services.runs_repository import recover_stale_individual_runs


def _action() -> ActionDetail:
    return ActionDetail(
        id="lifecycle-action",
        key="lifecycle-action",
        name="Lifecycle action",
        description="",
        steps_count=1,
        has_url=False,
        browser_mode="desktop_browser",
    )


def _run() -> RunRecord:
    return RunRecord(
        id=str(uuid4()),
        action_id="lifecycle-action",
        action_key="lifecycle-action",
        status="running",
        mode="async",
        created_at="2026-09-01T00:00:00+00:00",
        started_at="2026-09-01T00:00:01+00:00",
    )


class IndividualRunLifecycleTests(unittest.TestCase):
    def test_replay_exception_becomes_terminal_error(self) -> None:
        run = _run()
        with patch("backend.services.action_runner._run_desktop_browser_replay", new=AsyncMock(side_effect=RuntimeError("replay failed"))), patch(
            "backend.services.action_runner.update_run"
        ):
            finished = asyncio.run(finish_action_run(_action(), ActionRunRequest(mode="async"), run))

        self.assertEqual(finished.status, "error")
        self.assertIsNotNone(finished.finished_at)

    def test_primary_persistence_failure_uses_terminal_fallback(self) -> None:
        run = _run()
        with patch("backend.services.action_runner._run_desktop_browser_replay", new=AsyncMock(return_value={"status": "success"})), patch(
            "backend.services.action_runner.update_run", side_effect=RuntimeError("json failure")
        ), patch("backend.services.action_runner.persist_terminal_run_fallback") as fallback:
            finished = asyncio.run(finish_action_run(_action(), ActionRunRequest(mode="async"), run))

        self.assertEqual(finished.status, "error")
        self.assertIsNotNone(finished.finished_at)
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.kwargs["code"], "UNHANDLED_RUN_EXCEPTION")

    def test_unexpected_task_exception_is_observed_and_recovered(self) -> None:
        run = _run()

        async def exercise() -> None:
            with patch(
                "backend.services.action_runner.finish_action_run",
                new=AsyncMock(side_effect=RuntimeError("unexpected task failure")),
            ), patch("backend.services.action_runner.persist_terminal_run_fallback") as fallback:
                task = schedule_finish_action_run(_action(), ActionRunRequest(mode="async"), run)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                self.assertTrue(task.done())
                fallback.assert_called_once()
                self.assertEqual(fallback.call_args.kwargs["code"], "UNHANDLED_RUN_EXCEPTION")

        asyncio.run(exercise())

    def test_startup_recovers_orphan_individual_run(self) -> None:
        run_id = str(uuid4())
        with SessionLocal.begin() as session:
            session.add(DbRun(id=run_id, status="running", run_origin="operational", batch_id=None))

        try:
            self.assertEqual(recover_stale_individual_runs(), 1)
            with SessionLocal() as session:
                row = session.get(DbRun, run_id)
                self.assertEqual(row.status, "error")  # type: ignore[union-attr]
                self.assertEqual(row.error_data["code"], "STALE_INDIVIDUAL_RUN_RECOVERED")  # type: ignore[union-attr]
        finally:
            with SessionLocal.begin() as session:
                row = session.get(DbRun, run_id)
                if row is not None:
                    session.delete(row)
