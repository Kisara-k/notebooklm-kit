"""Source listing."""

import json
from ._core import run_ts, _ts_client
from .config import UUID_COL_WIDTH

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_STATUS = {0: "UNKNOWN", 1: "PROCESSING", 2: "READY", 3: "FAILED"}


def list_sources(notebook_id: str, creds: dict) -> list[dict]:
    """Return all sources in *notebook_id* as a list of dicts."""
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';
import {{ SourceStatus }} from './src/types/source.js';

{_ts_client(creds)}

const notebook = await sdk.notebooks.get('{notebook_id}');
const sources  = await sdk.sources.list('{notebook_id}');
const out = {{
  notebookTitle: notebook.title ?? '{notebook_id}',
  sources: sources.map(s => ({{
    sourceId: s.sourceId,
    title:    s.title ?? s.url ?? 'Untitled',
    type:     s.type,
    status:   s.status ?? 0,
  }})),
}};
console.log('__DATA__' + JSON.stringify(out) + '__DATA__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_list_sources", script)
    data    = json.loads(raw[raw.find("__DATA__") + 8 : raw.rfind("__DATA__")])
    title   = data["notebookTitle"]
    sources = data["sources"]

    col_t = max((len(s["title"]) for s in sources), default=5)
    col_t = max(col_t, 5)
    UUID  = UUID_COL_WIDTH
    sep = f"+---+{'-' * (col_t + 2)}+------------+{'-' * (UUID + 2)}+"
    print(f"\nNotebook : {title}")
    print(sep)
    print(f"| # | {'Title':{col_t}} | {'Status':10} | {'Source ID':{UUID}} |")
    print(sep)
    for i, s in enumerate(sources):
        if s["status"] not in _STATUS:
            print(f"⚠ FALLBACK: unknown source status code {s['status']!r} for '{s['title']}' — displaying raw value")
        status = _STATUS.get(s["status"], str(s["status"]))
        print(f"| {i} | {s['title']:{col_t}} | {status:10} | {s['sourceId']:{UUID}} |")
    print(sep)
    return sources
