"""Source listing."""

import json
from ._core import run_ts, _ts_client


def list_sources(notebook_id: str, creds: dict) -> list[dict]:
    """Return all sources in *notebook_id* as a list of dicts.

    Each dict has: sourceId, title, type, status.
    """
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';

{_ts_client(creds)}

const notebook = await sdk.notebooks.get('{notebook_id}');
console.log('Notebook:', notebook.title);

const sources = await sdk.sources.list('{notebook_id}');
console.log('__SOURCES__' + JSON.stringify(sources.map(s => ({{
  sourceId: s.sourceId,
  title: s.title ?? s.url ?? 'Untitled',
  type: s.type,
  status: s.status,
}}))) + '__SOURCES__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_list_sources", script)
    sources = json.loads(raw[raw.find("__SOURCES__") + 11 : raw.rfind("__SOURCES__")])
    print(f"\nFound {len(sources)} sources:")
    for i, s in enumerate(sources):
        print(f"  [{i}] {s['title']}")
        print(f"       id: {s['sourceId'][:12]}…  status: {s['status']}")
    return sources
