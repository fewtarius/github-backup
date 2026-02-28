"""Unit tests for github_backup.utils."""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from github_backup.utils import (
    retry,
    format_duration,
    safe_filename,
    handle_rate_limit,
    get_all_pages,
)


class TestRetryDecorator(unittest.TestCase):
    def test_succeeds_on_first_try(self):
        """Should not retry if first call succeeds."""
        call_count = [0]

        @retry(max_attempts=3, backoff_seconds=0)
        def succeeds():
            call_count[0] += 1
            return "ok"

        result = succeeds()
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 1)

    def test_retries_on_failure_then_succeeds(self):
        """Should retry and eventually succeed."""
        call_count = [0]

        @retry(max_attempts=3, backoff_seconds=0)
        def fails_twice():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("temporary failure")
            return "success"

        result = fails_twice()
        self.assertEqual(result, "success")
        self.assertEqual(call_count[0], 3)

    def test_raises_after_max_attempts(self):
        """Should re-raise after all attempts exhausted."""
        call_count = [0]

        @retry(max_attempts=3, backoff_seconds=0)
        def always_fails():
            call_count[0] += 1
            raise RuntimeError("permanent failure")

        with self.assertRaises(RuntimeError) as ctx:
            always_fails()
        self.assertEqual(call_count[0], 3)
        self.assertIn("permanent failure", str(ctx.exception))

    def test_preserves_function_name(self):
        """Wrapped function should preserve __name__."""
        @retry(max_attempts=1)
        def my_function():
            pass

        self.assertEqual(my_function.__name__, "my_function")

    def test_zero_backoff_does_not_sleep(self):
        """backoff_seconds=0 should not add meaningful delay."""
        @retry(max_attempts=2, backoff_seconds=0)
        def fails_once():
            if not hasattr(fails_once, "_called"):
                fails_once._called = True
                raise ValueError("once")
            return "ok"

        start = time.time()
        result = fails_once()
        elapsed = time.time() - start
        self.assertEqual(result, "ok")
        self.assertLess(elapsed, 1.0)  # Should be nearly instant


class TestFormatDuration(unittest.TestCase):
    def test_seconds_only(self):
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(1), "1s")
        self.assertEqual(format_duration(0), "0s")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_duration(90), "1m 30s")
        self.assertEqual(format_duration(60), "1m 0s")

    def test_hours_minutes_seconds(self):
        self.assertEqual(format_duration(3661), "1h 1m 1s")
        self.assertEqual(format_duration(3600), "1h 0m 0s")

    def test_float_truncated(self):
        self.assertEqual(format_duration(45.9), "45s")


class TestSafeFilename(unittest.TestCase):
    def test_clean_name_unchanged(self):
        self.assertEqual(safe_filename("my-repo"), "my-repo")
        self.assertEqual(safe_filename("repo_name"), "repo_name")

    def test_slash_replaced(self):
        self.assertEqual(safe_filename("owner/repo"), "owner_repo")

    def test_multiple_special_chars(self):
        result = safe_filename("file:name*with?special<chars>")
        self.assertNotIn(":", result)
        self.assertNotIn("*", result)
        self.assertNotIn("?", result)
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

    def test_strips_whitespace(self):
        self.assertEqual(safe_filename("  name  "), "name")


class TestHandleRateLimit(unittest.TestCase):
    def test_no_sleep_when_remaining(self):
        """Should not sleep when rate limit not exhausted."""
        response = MagicMock()
        response.headers = {
            "X-RateLimit-Remaining": "100",
            "X-RateLimit-Reset": "9999999999",
        }
        # Should not raise or sleep significantly
        with patch("time.sleep") as mock_sleep:
            handle_rate_limit(response)
            mock_sleep.assert_not_called()

    def test_sleeps_when_exhausted(self):
        """Should sleep when rate limit is 0."""
        response = MagicMock()
        future_reset = int(time.time()) + 10
        response.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(future_reset),
        }
        with patch("time.sleep") as mock_sleep:
            handle_rate_limit(response)
            mock_sleep.assert_called_once()
            sleep_duration = mock_sleep.call_args[0][0]
            # Should sleep approximately 10s (reset - now + 2s buffer)
            self.assertGreater(sleep_duration, 0)
            self.assertLessEqual(sleep_duration, 15)


class TestGetAllPages(unittest.TestCase):
    def test_single_page(self):
        """Should return items from a single page."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = [{"id": 1}, {"id": 2}]
        mock_response.links = {}  # No next page
        mock_response.headers = {"X-RateLimit-Remaining": "100"}
        mock_session.get.return_value = mock_response

        result = get_all_pages(mock_session, "https://api.github.com/repos/test/issues")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        mock_session.get.assert_called_once()

    def test_multiple_pages(self):
        """Should follow pagination links."""
        mock_session = MagicMock()

        page1 = MagicMock()
        page1.json.return_value = [{"id": 1}]
        page1.links = {"next": {"url": "https://api.github.com/repos/test/issues?page=2"}}
        page1.headers = {"X-RateLimit-Remaining": "100"}

        page2 = MagicMock()
        page2.json.return_value = [{"id": 2}]
        page2.links = {}  # Last page
        page2.headers = {"X-RateLimit-Remaining": "99"}

        mock_session.get.side_effect = [page1, page2]

        result = get_all_pages(mock_session, "https://api.github.com/repos/test/issues")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        self.assertEqual(mock_session.get.call_count, 2)


if __name__ == "__main__":
    unittest.main()
