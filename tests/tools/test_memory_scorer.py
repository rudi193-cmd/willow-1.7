"""Unit tests for memory_scorer — no live DB required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.memory_scorer import age_bucket, overlap_score, word_set, check_contradiction


class TestAgeBucket:
    def test_hot_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=3)).isoformat()
        assert age_bucket(created) == "HOT"

    def test_warm_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=15)).isoformat()
        assert age_bucket(created) == "WARM"

    def test_stale_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=60)).isoformat()
        assert age_bucket(created) == "STALE"

    def test_dead_record(self):
        from datetime import datetime, timedelta
        created = (datetime.now() - timedelta(days=120)).isoformat()
        assert age_bucket(created) == "DEAD"

    def test_bad_date_returns_unknown(self):
        assert age_bucket("not-a-date") == "UNKNOWN"

    def test_empty_string_returns_unknown(self):
        assert age_bucket("") == "UNKNOWN"


class TestWordSet:
    def test_filters_short_words(self):
        result = word_set("the cat sat on mat")
        assert "the" not in result
        assert "cat" not in result
        assert "sat" in result
        assert "mat" in result

    def test_normalizes_hyphens(self):
        result = word_set("self-hosted memory-store")
        assert "self" in result
        assert "hosted" in result
        assert "memory" in result
        assert "store" in result

    def test_empty_string(self):
        assert word_set("") == set()

    def test_none_returns_empty(self):
        assert word_set(None) == set()


class TestOverlapScore:
    def test_identical_titles(self):
        score = overlap_score("Session Close 2026-03-27", "Session Close 2026-03-27")
        assert score == 1.0

    def test_no_overlap(self):
        score = overlap_score("Postgres schema truth", "Reddit post written")
        assert score == 0.0

    def test_partial_overlap(self):
        score = overlap_score("Session Close 2026-03-27 Session B",
                              "Session Close 2026-03-28 Session L")
        assert 0.4 < score < 1.0

    def test_empty_titles(self):
        assert overlap_score("", "") == 0.0
        assert overlap_score("something real", "") == 0.0


class TestCheckContradiction:
    def test_blocked_and_unblocked(self):
        hits = check_contradiction("SA002 progress", "cube_cells_indexer unblocked by schema fix")
        assert any("blocked" in h for h in hits)

    def test_no_contradiction(self):
        hits = check_contradiction("SLM benchmark results", "qwen2.5 fastest model confirmed")
        assert hits == []

    def test_complete_and_incomplete(self):
        hits = check_contradiction("feature complete but incomplete data", "")
        assert any("complete" in h for h in hits)
