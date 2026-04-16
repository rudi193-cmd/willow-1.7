"""Tests for F-022 (silent exceptions) and F-023 (autocommit transaction).
b17: HA8KK
ΔΣ=42
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))


def _make_pg(fail_on_execute=False):
    from pg_bridge import PgBridge
    pg = PgBridge.__new__(PgBridge)
    pg._psycopg2 = MagicMock()
    mock_cur = MagicMock()
    if fail_on_execute:
        mock_cur.execute.side_effect = Exception("db error")
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_conn.cursor.return_value = mock_cur
    pg._conn = mock_conn
    return pg, mock_conn, mock_cur


class TestSilentExceptions:
    def test_opus_feedback_write_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.opus_feedback_write("domain", "principle")
        assert result is False
        mock_log.warning.assert_called_once()
        assert "opus_feedback_write" in mock_log.warning.call_args[0][0]

    def test_opus_journal_write_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.opus_journal_write("entry text")
        assert result is None
        mock_log.warning.assert_called_once()
        assert "opus_journal_write" in mock_log.warning.call_args[0][0]

    def test_submit_task_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.submit_task("do something")
        assert result is None
        mock_log.warning.assert_called_once()
        assert "submit_task" in mock_log.warning.call_args[0][0]

    def test_complete_task_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.complete_task("task-id", {"done": True})
        assert result is False
        mock_log.warning.assert_called_once()
        assert "complete_task" in mock_log.warning.call_args[0][0]

    def test_fail_task_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.fail_task("task-id", "something broke")
        assert result is False
        mock_log.warning.assert_called_once()
        assert "fail_task" in mock_log.warning.call_args[0][0]

    def test_claim_task_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.claim_task()
        assert result is None
        mock_log.warning.assert_called_once()
        assert "claim_task" in mock_log.warning.call_args[0][0]

    def test_pending_tasks_logs_on_failure(self):
        pg, conn, cur = _make_pg(fail_on_execute=True)
        with patch("pg_bridge._logger") as mock_log:
            result = pg.pending_tasks()
        assert result == []
        mock_log.warning.assert_called_once()
        assert "pending_tasks" in mock_log.warning.call_args[0][0]


class TestAgentCreateTransaction:
    def test_agent_create_rolls_back_on_failure(self):
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        mock_cur.fetchone.return_value = (0,)
        call_count = [0]
        def side_effect(*args, **kwargs):
            i = call_count[0]
            call_count[0] += 1
            if i == 2:
                raise Exception("disk full")
        mock_cur.execute.side_effect = side_effect
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            result = pg.agent_create("newagent")
        assert "error" in result
        mock_conn.rollback.assert_called_once()

    def test_agent_create_commits_on_success(self):
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        mock_cur.fetchone.return_value = (0,)
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            result = pg.agent_create("newagent")
        assert result.get("status") == "created"
        mock_conn.commit.assert_called_once()

    def test_agent_create_restores_autocommit(self):
        from pg_bridge import PgBridge
        pg = PgBridge.__new__(PgBridge)
        pg._psycopg2 = MagicMock()
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_conn.cursor.return_value = mock_cur
        pg._conn = mock_conn
        mock_cur.fetchone.return_value = (0,)
        mock_cur.execute.side_effect = [None, None, Exception("fail")]
        with patch("pg_bridge._MAX_AGENT_SCHEMAS", 30):
            pg.agent_create("newagent")
        assert mock_conn.autocommit == True
