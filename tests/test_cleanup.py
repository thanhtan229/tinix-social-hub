from __future__ import annotations
from unittest.mock import patch

from app.cleanup import cleanup_previous_sessions, main


def test_cleanup_execution():
    with patch("app.cleanup.terminate_processes", return_value=0):
        backends, chromes = cleanup_previous_sessions()
        assert isinstance(backends, int)
        assert isinstance(chromes, int)


def test_cleanup_main():
    with patch("app.cleanup.terminate_processes", return_value=0):
        main()

