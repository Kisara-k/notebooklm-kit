"""Pipeline configuration — edit these values to tune pipeline behaviour."""

from pathlib import Path

# ===========================================================================
# Filesystem layout  (relative to SDK_ROOT)
# ===========================================================================

JOBS_SUBDIR    = "jobs"     # jobs/<artifact_type_lower>/<ts>_<notebook>.json
OUTPUTS_SUBDIR = "outputs"  # outputs/<artifact_type_lower>/<file>

# ===========================================================================
# Download / filename naming
# ===========================================================================

# Max length for each notebook/source component inside a downloaded filename:
#   <yyyymmdd_hhmmss>_<Notebook>__<Source>__<TYPE>.<ext>
# strftime format used inside downloaded filenames.
# This value is also used to build the skip-check glob, so it must produce
FILENAME_COMPONENT_MAXLEN = 80
FILENAME_TS_FORMAT = "%Y%m%d %H%M%S"

# ===========================================================================
# Rename: single-source artifact title
# ===========================================================================

# New title pattern:  "<source title>[:RENAME_SOURCE_MAXLEN] YYMMDD HHMM"
RENAME_SOURCE_MAXLEN = 80
RENAME_TS_FORMAT = "%y%m%d %H%M%S"





# ===========================================================================
# Polling
# ===========================================================================

POLL_INTERVAL_SEC = 30      # default seconds between artifact-state polls
POLL_MAX_WAIT_MIN = 15      # default total wait before timing out

# ===========================================================================
# Table rendering
# ===========================================================================

UUID_COL_WIDTH = 36         # full UUID width for table columns

# ===========================================================================
# Core / auth
# ===========================================================================

# Root of the notebooklm-kit repository (parent of this pipeline/ package)
SDK_ROOT: Path = Path(__file__).parent.parent

# Filename of credentials file produced by login.py (lives at SDK_ROOT)
CREDENTIALS_FILENAME = "credentials.json"

# HTTP timeout (seconds) when fetching a fresh SNlM0e CSRF token
AUTH_FETCH_TIMEOUT_SEC = 15

# User-Agent sent when fetching the NotebookLM page for the CSRF token
AUTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)