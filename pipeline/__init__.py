"""
NotebookLM Kit — shared pipeline library.

Import everything you need from this package:

    from pipeline import load_credentials, check_tsx, SDK_ROOT
    from pipeline import list_sources
    from pipeline import create_artifacts, load_jobs, poll_jobs, download_artifacts
"""

from ._core import SDK_ROOT, load_credentials, check_tsx, login
from ._sources import list_sources
from ._artifacts import create_artifacts, load_jobs, poll_jobs, download_artifacts

__all__ = [
    "SDK_ROOT",
    "load_credentials",
    "login",
    "check_tsx",
    "list_sources",
    "create_artifacts",
    "load_jobs",
    "poll_jobs",
    "download_artifacts",
]
