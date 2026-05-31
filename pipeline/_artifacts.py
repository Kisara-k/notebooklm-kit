"""Artifact lifecycle: create → poll → download.

Supported artifact_type strings (match TypeScript ArtifactType enum members):
    FLASHCARDS    QUIZ          VIDEO         AUDIO
    SLIDE_DECK    INFOGRAPHIC

Each function is designed to be called identically regardless of artifact type.
Download behaviour is specialised per type where the SDK requires it.
"""

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from ._core import SDK_ROOT, run_ts, _ts_client
from .config import (
    FILENAME_COMPONENT_MAXLEN,
    FILENAME_TS_FORMAT,
    RENAME_SOURCE_MAXLEN,
    RENAME_TS_FORMAT,
    POLL_INTERVAL_SEC,
    POLL_MAX_WAIT_MIN,
    JOBS_SUBDIR,
    OUTPUTS_SUBDIR,
    UUID_COL_WIDTH,
)

# ---------------------------------------------------------------------------
# Internal constants (not intended for user tuning)
# ---------------------------------------------------------------------------

# Per-type download strategy:
# sdk.artifacts.download(id, folder, notebookId) → { filePath }
_DOWNLOAD_VIA_DOWNLOAD = {"FLASHCARDS", "QUIZ", "AUDIO", "INFOGRAPHIC"}
# sdk.artifacts.get(id, notebookId, { outputPath }) → { downloadPath }
_DOWNLOAD_VIA_GET = {"VIDEO", "SLIDE_DECK"}

# ArtifactType enum values (TS src/types/artifact.ts) → display label
_ARTIFACT_TYPE_LABELS = {
    0: "UNKNOWN", 1: "REPORT", 5: "QUIZ", 6: "FLASHCARDS",
    7: "MIND_MAP", 8: "INFOGRAPHIC", 9: "SLIDE_DECK",
    10: "AUDIO", 11: "VIDEO",
}


def _jobs_dir(artifact_type: str) -> Path:
    d = SDK_ROOT / JOBS_SUBDIR / artifact_type.lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class JobList(list):
    """list[dict] that also carries the path of the originating jobs file."""
    def __new__(cls, items, path):
        return super().__new__(cls, items)
    def __init__(self, items, path: Path):
        super().__init__(items)
        self.path = path


def _safe_filename(s: str, maxlen: int = FILENAME_COMPONENT_MAXLEN) -> str:
    """Strip non-filename characters; spaces are preserved."""
    s = re.sub(r'[^\w\s\-.]', '', s)
    return s.strip()[:maxlen]


def _artifact_stem(ts_str: str, src: str) -> str:
    """Canonical artifact filename stem: ``<ts>_<src>``."""
    return f"{ts_str} {src}"


def _print_jobs_table(jobs: list[dict], *, header: str, errors: list | None = None) -> None:
    col = max((len(j["sourceTitle"]) for j in jobs + [{"sourceTitle": "Source"}]), default=6)
    sep = f"+---+{'-' * (col + 2)}+----------------------------------------------+"
    print(header)
    print(sep)
    print(f"| {'#':1} | {'Source':{col}} | {'Artifact ID':44} |")
    print(sep)
    for i, j in enumerate(jobs):
        print(f"| {i:1} | {j['sourceTitle']:{col}} | {j['artifactId']:44} |")
    if errors:
        print(sep)
        for e in errors:
            print(f"  x  {e['title']}: {e['error']}")
    print(sep)


def _print_download_table(results: list[dict], errors: list, *, header: str) -> None:
    col = max((len(r["sourceTitle"]) for r in results + [{"sourceTitle": "Source"}]), default=6)
    sep = f"+---+{'-' * (col + 2)}+{'-' * 46}+{'-' * 12}+"
    print(header)
    print(sep)
    print(f"| {'#':1} | {'Source':{col}} | {'File':44} | {'Status':10} |")
    print(sep)
    for i, r in enumerate(results):
        fname = Path(r["filePath"]).name
        trunc = fname if len(fname) <= 44 else fname[:41] + "..."
        print(f"| {i:1} | {r['sourceTitle']:{col}} | {trunc:44} | {r.get('status', '?'):10} |")
    if errors:
        print(sep)
        for e in errors:
            print(f"  x  {e['sourceTitle']}: {e['error']}")
    print(sep)


def _parse_created_at(created_at: str) -> str:
    """Convert an ISO-8601 ``createdAt`` string to ``yyyymmdd_hhmmss`` local time."""
    try:
        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        return dt.astimezone().strftime(FILENAME_TS_FORMAT)
    except Exception as e:
        ts = _ts_now()
        print(f"⚠ FALLBACK: _parse_created_at could not parse {created_at!r} ({e}); using current time {ts}")
        return ts


def _expected_file(output_dir: Path, source_title: str, created_at: str) -> Path | None:
    """Return the expected output file if it already exists, or None.

    Matches by exact stem ``<yyyymmdd_hhmmss>_<Source>`` (any extension).
    The artifact type and notebook name are encoded in the directory path.
    """
    if not created_at:
        print(f"⚠ FALLBACK: _expected_file called with empty createdAt for '{source_title}' — SDK returned no createdAt; skip check disabled, file will always be re-downloaded")
        return None
    ts_str = _parse_created_at(created_at)
    src    = _safe_filename(source_title)
    expected_stem = _artifact_stem(ts_str, src)
    for f in output_dir.iterdir():
        if f.stem == expected_stem:
            return f
    return None


def _final_name(file_path: str, source_title: str, created_at: str | None = None) -> str:
    """Rename downloaded file to ``<yyyymmdd_hhmmss>_<Source><ext>``."""
    p = Path(file_path)
    if created_at:
        ts_str = _parse_created_at(created_at)
    else:
        print(f"⚠ FALLBACK: _final_name has no createdAt for '{source_title}' — falling back to filename timestamp")
        m = re.match(r'^.+_(\d{13})$', p.stem)
        if m:
            ts_str = (
                datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
                .astimezone().strftime(FILENAME_TS_FORMAT)
            )
        else:
            ts_str = _ts_now()
            print(f"⚠ FALLBACK: _final_name could not extract timestamp from filename {p.name!r} — using current time {ts_str}")
    src = _safe_filename(source_title)
    new_path = p.parent / f"{_artifact_stem(ts_str, src)}{p.suffix}"
    p.rename(new_path)
    return str(new_path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_artifacts(
    notebook_id: str,
    artifact_type: str,
    sources: list[dict],
    customization: dict,
    instructions: str | None,
    creds: dict,
) -> list[dict]:
    """Create one artifact per source entry.

    Job IDs are automatically saved to ``jobs/<type>/<yyyymmdd_hhmmss>_jobs.json``.
    Use :func:`load_jobs` to reload them in a later session.
    """
    if isinstance(sources, dict):
        sources = [sources]
    artifact_type = artifact_type.upper()
    label = artifact_type.replace("_", " ").title()
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';
import {{ ArtifactType }} from './src/types/artifact.js';

{_ts_client(creds)}

const notebook = await sdk.notebooks.get('{notebook_id}');
const notebookTitle = notebook.title ?? '{notebook_id}';

const SOURCES       = {json.dumps(sources)};
const CUSTOMIZATION = {json.dumps(customization)};
const INSTRUCTIONS  = {json.dumps(instructions or '')};

const jobs: Array<{{ sourceId: string; sourceTitle: string; artifactId: string; notebookTitle: string; createdAt: string }}> = [];
const errors: Array<{{ title: string; error: string }}> = [];

for (const source of SOURCES) {{
  try {{
    const artifact = await sdk.artifacts.create('{notebook_id}', ArtifactType.{artifact_type}, {{
      title: `{label} \u2014 ${{source.title}}`,
      sourceIds: [source.sourceId],
      ...(INSTRUCTIONS ? {{ instructions: INSTRUCTIONS }} : {{}}),
      customization: CUSTOMIZATION,
    }});
    jobs.push({{ sourceId: source.sourceId, sourceTitle: source.title, artifactId: artifact.artifactId, notebookTitle, createdAt: artifact.createdAt ?? '' }});
  }} catch (err: any) {{
    errors.push({{ title: source.title, error: err.message }});
  }}
}}

console.log('__JOBS__' + JSON.stringify({{ notebookTitle, jobs, errors }}) + '__JOBS__');
await sdk.dispose();
"""
    raw  = run_ts("_tmp_create_artifacts", script)
    data = json.loads(raw[raw.find("__JOBS__") + 8 : raw.rfind("__JOBS__")])
    jobs          = data["jobs"]
    errors        = data.get("errors", [])
    notebook_name = _safe_filename(data.get("notebookTitle", notebook_id))

    jobs_path = _jobs_dir(artifact_type) / f"{_ts_now()} {notebook_name}.json"
    jobs_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")

    _print_jobs_table(jobs, header=f"\nSubmitted {len(jobs)} job(s)  \u2192  {jobs_path.relative_to(SDK_ROOT)}", errors=errors)
    return JobList(jobs, jobs_path)


def load_jobs(artifact_type: str, filename: str | None = None) -> list[dict]:
    """Load a saved jobs list.

    Args:
        artifact_type: e.g. ``"FLASHCARDS"`` or ``"VIDEO"``.
        filename:      Specific filename inside ``jobs/<type>/``.
                       If omitted, the most recent file in that folder is used.
    """
    artifact_type = artifact_type.upper()
    d = _jobs_dir(artifact_type)
    if filename is not None:
        p = d / filename
        if not p.exists():
            raise FileNotFoundError(f"Jobs file not found: {p}")
    else:
        candidates = sorted(d.glob("*.json"))
        if not candidates:
            raise FileNotFoundError(f"No jobs files found in {d}. Run create_artifacts first.")
        p = candidates[-1]
    jobs = json.loads(p.read_text(encoding="utf-8"))
    _print_jobs_table(jobs, header=f"\nLoaded {len(jobs)} job(s) from {p.name}")
    return JobList(jobs, p)


def poll_jobs(
    jobs: list[dict],
    notebook_id: str,
    creds: dict,
    *,
    interval: int = POLL_INTERVAL_SEC,
    max_wait_min: int = POLL_MAX_WAIT_MIN,
) -> bool:
    """Poll artifact states until all are READY or FAILED.

    Args:
        jobs:          Job list from :func:`create_artifacts` or :func:`load_jobs`.
        notebook_id:   Target notebook.
        creds:         Credentials dict from :func:`load_credentials`.
        interval:      Seconds between polls.
        max_wait_min:  Timeout in minutes; prints a warning and returns False on expiry.

    Returns:
        True if every job reached READY or FAILED; False on timeout.
    """
    poll_script = f"""
import {{ NotebookLMClient }} from './src/index.js';
import {{ ArtifactState }} from './src/types/artifact.js';

{_ts_client(creds)}

const ids = {json.dumps([j['artifactId'] for j in jobs])};
const statuses: Record<string, string> = {{}};
for (const id of ids) {{
  const art = await sdk.artifacts.get(id, '{notebook_id}');
  statuses[id] = ArtifactState[art.state ?? ArtifactState.UNKNOWN] ?? 'UNKNOWN';
}}
console.log('__STATUS__' + JSON.stringify(statuses) + '__STATUS__');
await sdk.dispose();
"""
    poll_path = SDK_ROOT / "_tmp_poll_artifacts.ts"
    poll_path.write_text(poll_script, encoding="utf-8")

    deadline = time.time() + max_wait_min * 60
    while time.time() < deadline:
        result = subprocess.run(
            f'npx tsx "{poll_path}"',
            capture_output=True, text=True, cwd=str(SDK_ROOT), shell=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Poll failed:\n{result.stderr[-1000:]}")

        raw = result.stdout
        statuses = json.loads(raw[raw.find("__STATUS__") + 10 : raw.rfind("__STATUS__")])

        all_done = True
        for j in jobs:
            state = statuses.get(j["artifactId"], "UNKNOWN")
            icon = "✓" if state == "READY" else ("✗" if state == "FAILED" else "⏳")
            print(f"  {icon} {j['sourceTitle'][:55]:55s} {state}")
            if state not in ("READY", "FAILED"):
                all_done = False

        if all_done:
            print("\n✅ All artifacts ready — proceed to download.")
            return True

        print(f"\n  Waiting {interval}s…\n")
        time.sleep(interval)

    print("\n⚠️  Timed out. Check the web UI and proceed to download when ready.")
    return False


def download_artifacts(
    jobs: list[dict],
    notebook_id: str,
    artifact_type: str,
    creds: dict,
    *,
    output_dir: Path | None = None,
) -> list[dict]:
    """Download all READY artifacts.

    Saves to ``outputs/<artifact_type_lower>/`` by default.
    For VIDEO the file is named after the source title (``<title>.mp4``).
    For all other types the SDK's default naming is used.

    Returns:
        List of ``{sourceTitle, filePath}`` for successfully downloaded artifacts.
    """
    artifact_type = artifact_type.upper()

    # Backfill notebookTitle / createdAt for jobs created before those fields were stored.
    # Fetch from the SDK in a single TS call rather than silently degrading.
    stale = [j for j in jobs if not j.get("notebookTitle") or not j.get("createdAt")]
    if stale:
        stale_json = json.dumps([{"artifactId": j["artifactId"]} for j in stale])
        backfill_script = f"""
import {{ NotebookLMClient }} from './src/index.js';

{_ts_client(creds)}

const notebook = await sdk.notebooks.get('{notebook_id}');
const notebookTitle = notebook.title ?? '{notebook_id}';

const enriched: Array<{{ artifactId: string; notebookTitle: string; createdAt: string }}> = [];
for (const job of {stale_json}) {{
  const art = await sdk.artifacts.get(job.artifactId, '{notebook_id}');
  enriched.push({{ artifactId: job.artifactId, notebookTitle, createdAt: art.createdAt ?? '' }});
}}
console.log('__ENRICHED__' + JSON.stringify(enriched) + '__ENRICHED__');
await sdk.dispose();
"""
        raw_e = run_ts("_tmp_download_artifacts", backfill_script)
        enriched = json.loads(raw_e[raw_e.find("__ENRICHED__") + 12 : raw_e.rfind("__ENRICHED__")])
        by_id = {e["artifactId"]: e for e in enriched}
        for j in jobs:
            if j["artifactId"] in by_id:
                e = by_id[j["artifactId"]]
                if not j.get("notebookTitle"):
                    j["notebookTitle"] = e["notebookTitle"]
                if not j.get("createdAt"):
                    if e["createdAt"]:
                        j["createdAt"] = e["createdAt"]
                    else:
                        print(f"⚠ FALLBACK: SDK returned empty createdAt for '{j['sourceTitle']}' (artifactId={j['artifactId']}) — skip check disabled for this job")
        # Persist enriched fields back to the jobs file so future runs don't need to re-fetch
        if hasattr(jobs, "path") and jobs.path.exists():
            jobs.path.write_text(json.dumps(list(jobs), indent=2), encoding="utf-8")

    if output_dir is None:
        nb_name = _safe_filename(jobs[0].get("notebookTitle", notebook_id)) if jobs else _safe_filename(notebook_id)
        output_dir = SDK_ROOT / OUTPUTS_SUBDIR / artifact_type.lower() / nb_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_str = str(output_dir).replace("\\", "/")

    # Skip jobs whose exact output file (keyed on the artifact's own createdAt timestamp)
    # already exists locally.
    skipped     = []
    to_download = []
    for j in jobs:
        existing = _expected_file(output_dir, j["sourceTitle"], j.get("createdAt", ""))
        if existing:
            skipped.append({"sourceTitle": j["sourceTitle"], "filePath": str(existing), "status": "skipped"})
        else:
            to_download.append(j)

    if not to_download:
        # Nothing to download — build table from skipped only and return early
        results = skipped
        _print_download_table(results, [], header=f"\nDownloaded 0 / {len(jobs)} artifact(s)  ({len(skipped)} skipped)  \u2192  {output_dir}")
        return results

    if artifact_type in _DOWNLOAD_VIA_GET:
        dl_body = f"""  try {{
    const res = await sdk.artifacts.get(job.artifactId, '{notebook_id}', {{ outputPath: '{output_str}' }});
    results.push({{ sourceTitle: job.sourceTitle, notebookTitle, createdAt: job.createdAt ?? '', filePath: (res as any).downloadPath as string }});
  }} catch (err: any) {{
    errors.push({{ sourceTitle: job.sourceTitle, error: err.message }});
  }}"""
    else:
        dl_body = f"""  try {{
    const res = await sdk.artifacts.download(job.artifactId, '{output_str}', '{notebook_id}');
    results.push({{ sourceTitle: job.sourceTitle, notebookTitle, createdAt: job.createdAt ?? '', filePath: res.filePath }});
  }} catch (err: any) {{
    errors.push({{ sourceTitle: job.sourceTitle, error: err.message }});
  }}"""

    script = f"""
import {{ NotebookLMClient }} from './src/index.js';
import {{ ArtifactState }} from './src/types/artifact.js';

{_ts_client(creds)}

const notebook = await sdk.notebooks.get('{notebook_id}');
const notebookTitle = notebook.title ?? '{notebook_id}';

const results: Array<{{ sourceTitle: string; notebookTitle: string; createdAt: string; filePath: string }}> = [];
const errors:  Array<{{ sourceTitle: string; error: string }}> = [];

for (const job of {json.dumps(to_download)}) {{
  const artifact = await sdk.artifacts.get(job.artifactId, '{notebook_id}');
  if (artifact.state !== ArtifactState.READY) {{
    errors.push({{ sourceTitle: job.sourceTitle, error: `not ready: state=${{artifact.state}}` }});
    continue;
  }}
{dl_body}
}}

console.log('__RESULTS__' + JSON.stringify({{ results, errors }}) + '__RESULTS__');
await sdk.dispose();
"""
    raw  = run_ts("_tmp_download_artifacts", script)
    data = json.loads(raw[raw.find("__RESULTS__") + 11 : raw.rfind("__RESULTS__")])
    fresh  = data["results"]
    errors = data.get("errors", [])
    for r in fresh:
        r["filePath"] = _final_name(r["filePath"], r["sourceTitle"], r.get("createdAt") or None)
        r["status"] = "downloaded"

    # Merge: preserve job order, insert skipped entries
    by_title = {r["sourceTitle"]: r for r in fresh}
    results  = []
    for j in jobs:
        if j["sourceTitle"] in by_title:
            results.append(by_title[j["sourceTitle"]])
        elif j["sourceTitle"] in {s["sourceTitle"]: s for s in skipped}:
            results.append(next(s for s in skipped if s["sourceTitle"] == j["sourceTitle"]))

    n_dl   = sum(1 for r in results if r.get("status") == "downloaded")
    n_skip = sum(1 for r in results if r.get("status") == "skipped")
    _print_download_table(results, errors, header=f"\nDownloaded {n_dl} / {len(jobs)} artifact(s)" + (f"  ({n_skip} skipped)" if n_skip else "") + f"  \u2192  {output_dir}")
    return results


# ---------------------------------------------------------------------------
# Inventory: list artifacts in a notebook
# ---------------------------------------------------------------------------

def list_artifacts(notebook_id: str, sources: list[dict], creds: dict) -> list[dict]:
    """Return all artifacts in *notebook_id* and print a table.

    Each artifact's ``sourceIds`` is displayed as comma-separated indices into
    the supplied *sources* list (same list returned by ``list_sources``).
    Sources not present in that list show as ``?``.

    Returns the raw artifact list (dicts with ``artifactId``, ``title``, ``type``,
    ``state``, ``sourceIds``, ``createdAt``, ``updatedAt``).
    """
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';

{_ts_client(creds)}

const arts = await sdk.artifacts.list('{notebook_id}');
const out = arts.map(a => ({{
  artifactId: a.artifactId,
  title:      a.title ?? '',
  type:       a.type ?? 0,
  state:      a.state ?? 0,
  sourceIds:  a.sourceIds ?? [],
  createdAt:  a.createdAt ?? '',
  updatedAt:  a.updatedAt ?? '',
}}));
console.log('__DATA__' + JSON.stringify(out) + '__DATA__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_list_artifacts", script)
    artifacts = json.loads(raw[raw.find("__DATA__") + 8 : raw.rfind("__DATA__")])

    # Build sourceId → index lookup from the sources table
    idx_of = {s["sourceId"]: i for i, s in enumerate(sources)}

    def _fmt_created(iso: str) -> str:
        if not iso:
            print(f"⚠ FALLBACK: artifact has empty createdAt — column will show '(unknown)'")
            return "(unknown)"
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"⚠ FALLBACK: could not parse createdAt {iso!r} ({e}); showing raw")
            return iso

    def _fmt_sources(sids: list[str]) -> str:
        parts = []
        for sid in sids:
            if sid in idx_of:
                parts.append(str(idx_of[sid]))
            else:
                print(f"⚠ FALLBACK: artifact references sourceId {sid!r} not present in the sources list — shown as '?'")
                parts.append("?")
        return ",".join(parts) if parts else "(none)"

    rows = []
    for a in artifacts:
        type_code = a["type"]
        if type_code not in _ARTIFACT_TYPE_LABELS:
            print(f"⚠ FALLBACK: unknown artifact type code {type_code!r} for '{a['title']}' — displaying raw value")
        rows.append({
            "title":     a["title"] or "(untitled)",
            "type":      _ARTIFACT_TYPE_LABELS.get(type_code, str(type_code)),
            "created":   _fmt_created(a["createdAt"]),
            "sources":   _fmt_sources(a["sourceIds"]),
            "artifactId": a["artifactId"],
        })

    col_t = max((len(r["title"]) for r in rows), default=5)
    col_t = max(col_t, 5)
    col_y = max((len(r["type"]) for r in rows), default=4)
    col_y = max(col_y, 4)
    col_s = max((len(r["sources"]) for r in rows), default=7)
    col_s = max(col_s, 7)
    UUID  = UUID_COL_WIDTH

    sep = f"+----+{'-' * (col_t + 2)}+{'-' * (col_y + 2)}+---------------------+{'-' * (col_s + 2)}+{'-' * (UUID + 2)}+"
    print(f"\nArtifacts in notebook {notebook_id} ({len(rows)} total)")
    print(sep)
    print(f"| {'#':2} | {'Title':{col_t}} | {'Type':{col_y}} | {'Created':19} | {'Sources':{col_s}} | {'Artifact ID':{UUID}} |")
    print(sep)
    for i, r in enumerate(rows):
        print(f"| {i:2} | {r['title']:{col_t}} | {r['type']:{col_y}} | {r['created']:19} | {r['sources']:{col_s}} | {r['artifactId']:{UUID}} |")
    print(sep)
    return artifacts


# ---------------------------------------------------------------------------
# Rename single-source artifacts to "<source title> YYMMDD HHMM"
# ---------------------------------------------------------------------------

def rename_single_source_artifacts(
    artifacts: "list[dict] | dict",
    sources: list[dict],
    creds: dict,
    *,
    indices: list[int] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Rename every single-source artifact to ``<source title> YYMMDD HHMM``.

    Args:
        artifacts: list returned by ``list_artifacts``, a single artifact dict,
                   or any plain list of artifact dicts (e.g. ``artifacts[2:5]``).
        sources:   list returned by ``list_sources`` (used to resolve the source title).
        creds:     credentials dict.
        indices:   optional subset of artifact indices (rows in the artifacts table)
                   to consider; ``None`` means all.
        dry_run:   if True, prints the planned renames without calling the SDK.

    Returns a list of ``{artifactId, oldTitle, newTitle, status}`` dicts.
    """
    # Accept a single artifact dict or any iterable of dicts
    if isinstance(artifacts, dict):
        artifacts = [artifacts]

    title_of = {s["sourceId"]: s["title"] for s in sources}

    targets: list[dict] = []
    for i, a in enumerate(artifacts):
        if indices is not None and i not in indices:
            continue
        sids = a.get("sourceIds") or []
        if len(sids) != 1:
            continue
        sid = sids[0]
        if sid not in title_of:
            print(f"⚠ FALLBACK: artifact #{i} '{a.get('title')}' references unknown sourceId {sid!r} — skipped")
            continue
        created = a.get("createdAt") or ""
        if not created:
            print(f"⚠ FALLBACK: artifact #{i} '{a.get('title')}' has empty createdAt — skipped (cannot build timestamp)")
            continue
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone()
        except Exception as e:
            print(f"⚠ FALLBACK: artifact #{i} '{a.get('title')}' has unparseable createdAt {created!r} ({e}) — skipped")
            continue
        new_title = f"{title_of[sid][:RENAME_SOURCE_MAXLEN]} {dt.strftime(RENAME_TS_FORMAT)}"
        if new_title in (a.get("title") or ""):
            continue  # already contains the canonical name (may have extra prefix/suffix)
        targets.append({
            "index":      i,
            "artifactId": a["artifactId"],
            "oldTitle":   a.get("title") or "",
            "newTitle":   new_title,
        })

    if not targets:
        print("No single-source artifacts to rename.")
        return []

    col_o = max(len(t["oldTitle"]) for t in targets)
    col_n = max(len(t["newTitle"]) for t in targets)
    col_o = max(col_o, 8)
    col_n = max(col_n, 8)
    sep = f"+----+{'-' * (col_o + 2)}+{'-' * (col_n + 2)}+----------+"
    print(f"\n{'DRY RUN — ' if dry_run else ''}Renaming {len(targets)} single-source artifact(s)")
    print(sep)
    print(f"| {'#':2} | {'Old title':{col_o}} | {'New title':{col_n}} | {'Status':8} |")
    print(sep)

    if dry_run:
        for t in targets:
            print(f"| {t['index']:2} | {t['oldTitle']:{col_o}} | {t['newTitle']:{col_n}} | {'planned':8} |")
        print(sep)
        return targets

    # Build a single TS script that renames everything in one tsx invocation
    payload = json.dumps([{"artifactId": t["artifactId"], "newTitle": t["newTitle"]} for t in targets])
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';

{_ts_client(creds)}

const targets = {payload};
const results: Array<{{ artifactId: string; status: string; error?: string }}> = [];
for (const t of targets) {{
  try {{
    const a = await sdk.artifacts.rename(t.artifactId, t.newTitle);
    results.push({{ artifactId: t.artifactId, status: 'ok' }});
  }} catch (e: any) {{
    results.push({{ artifactId: t.artifactId, status: 'error', error: String(e?.message ?? e) }});
  }}
}}
console.log('__DATA__' + JSON.stringify(results) + '__DATA__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_rename_artifacts", script)
    results = json.loads(raw[raw.find("__DATA__") + 8 : raw.rfind("__DATA__")])
    status_by_id = {r["artifactId"]: r for r in results}

    out: list[dict] = []
    for t in targets:
        r = status_by_id.get(t["artifactId"], {"status": "missing"})
        status = r["status"]
        print(f"| {t['index']:2} | {t['oldTitle']:{col_o}} | {t['newTitle']:{col_n}} | {status:8} |")
        if status == "error":
            print(f"     error: {r.get('error', '')}")
        out.append({**t, "status": status, "error": r.get("error")})
        # Reflect the change in the in-memory artifacts list so re-printing shows new title
        if status == "ok":
            artifacts[t["index"]]["title"] = t["newTitle"]
    print(sep)
    return out



