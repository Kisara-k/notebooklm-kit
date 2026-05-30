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

# ---------------------------------------------------------------------------
# Internal: per-type download strategy
# ---------------------------------------------------------------------------

# These types use sdk.artifacts.download(id, folder, notebookId) → { filePath }
_DOWNLOAD_VIA_DOWNLOAD = {"FLASHCARDS", "QUIZ", "AUDIO", "INFOGRAPHIC"}

# These types use sdk.artifacts.get(id, notebookId, { outputPath }) → { downloadPath }
_DOWNLOAD_VIA_GET = {"VIDEO", "SLIDE_DECK"}


def _jobs_dir(artifact_type: str) -> Path:
    d = SDK_ROOT / "jobs" / artifact_type.lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ts_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _rename_downloaded(file_path: str) -> str:
    """Rename `name_<13-digit-ms>.ext` → `<yyyymmdd_hhmmss>_name.ext` in place."""
    p = Path(file_path)
    m = re.match(r"^(.+)_(\d{13})$", p.stem)
    if not m:
        return file_path
    name_part, ts_ms = m.group(1), int(m.group(2))
    ts_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    new_path = p.parent / f"{ts_str}_{name_part}{p.suffix}"
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
    label = artifact_type.replace("_", " ").title()
    script = f"""
import {{ NotebookLMClient }} from './src/index.js';
import {{ ArtifactType }} from './src/types/artifact.js';

{_ts_client(creds)}

const SOURCES       = {json.dumps(sources)};
const CUSTOMIZATION = {json.dumps(customization)};
const INSTRUCTIONS  = {json.dumps(instructions or '')};

const jobs: Array<{{ sourceId: string; sourceTitle: string; artifactId: string }}> = [];

for (const source of SOURCES) {{
  console.log(`Creating {label} for: ${{source.title}}`);
  try {{
    const artifact = await sdk.artifacts.create('{notebook_id}', ArtifactType.{artifact_type}, {{
      title: `{label} \u2014 ${{source.title}}`,
      sourceIds: [source.sourceId],
      ...(INSTRUCTIONS ? {{ instructions: INSTRUCTIONS }} : {{}}),
      customization: CUSTOMIZATION,
    }});
    console.log(`  \u2713 ${{artifact.artifactId}}  state: ${{artifact.state}}`);
    jobs.push({{ sourceId: source.sourceId, sourceTitle: source.title, artifactId: artifact.artifactId }});
  }} catch (err: any) {{
    console.error(`  \u2717 ${{source.title}}: ${{err.message}}`);
  }}
}}

console.log('__JOBS__' + JSON.stringify(jobs) + '__JOBS__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_create_artifacts", script)
    print(raw)
    jobs = json.loads(raw[raw.find("__JOBS__") + 8 : raw.rfind("__JOBS__")])

    jobs_path = _jobs_dir(artifact_type) / f"{_ts_now()}_jobs.json"
    jobs_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    print(f"\n✓ Submitted {len(jobs)} job(s)  →  {jobs_path}")
    for j in jobs:
        print(f"  {j['sourceTitle']}  →  {j['artifactId']}")
    return jobs


def load_jobs(artifact_type: str, filename: str | None = None) -> list[dict]:
    """Load a saved jobs list.

    Args:
        artifact_type: e.g. ``"FLASHCARDS"`` or ``"VIDEO"``.
        filename:      Specific filename inside ``jobs/<type>/``.
                       If omitted, the most recent file in that folder is used.
    """
    d = _jobs_dir(artifact_type)
    if filename is not None:
        p = d / filename
        if not p.exists():
            raise FileNotFoundError(f"Jobs file not found: {p}")
    else:
        candidates = sorted(d.glob("*_jobs.json"))
        if not candidates:
            raise FileNotFoundError(f"No jobs files found in {d}. Run create_artifacts first.")
        p = candidates[-1]
    jobs = json.loads(p.read_text(encoding="utf-8"))
    print(f"Loaded {len(jobs)} job(s) from {p.name}:")
    for j in jobs:
        print(f"  {j['sourceTitle']}  →  {j['artifactId']}")
    return jobs


def poll_jobs(
    jobs: list[dict],
    notebook_id: str,
    creds: dict,
    *,
    interval: int = 30,
    max_wait_min: int = 15,
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
    if output_dir is None:
        output_dir = SDK_ROOT / "outputs" / artifact_type.lower()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_str = str(output_dir).replace("\\", "/")

    if artifact_type in _DOWNLOAD_VIA_GET:
        extra_imports = "import * as path from 'path';\nimport * as fs from 'fs/promises';"
        dl_body = f"""  try {{
    const res = await sdk.artifacts.get(job.artifactId, '{notebook_id}', {{ outputPath: '{output_str}' }});
    const tmpPath = (res as any).downloadPath as string;
    const safeName = job.sourceTitle.replace(/[^\\w\\s\\-]/g, '').replace(/\\s+/g, '_').substring(0, 100);
    const finalPath = path.join('{output_str}', safeName + '.mp4');
    if (tmpPath !== finalPath) {{ await fs.rename(tmpPath, finalPath); }}
    console.log(`  \u2713 ${{finalPath}}`);
    results.push({{ sourceTitle: job.sourceTitle, filePath: finalPath }});
  }} catch (err: any) {{
    console.error(`  \u2717 ${{err.message}}`);
  }}"""
    else:
        extra_imports = ""
        dl_body = f"""  try {{
    const res = await sdk.artifacts.download(job.artifactId, '{output_str}', '{notebook_id}');
    console.log(`  \u2713 ${{res.filePath}}`);
    results.push({{ sourceTitle: job.sourceTitle, filePath: res.filePath }});
  }} catch (err: any) {{
    console.error(`  \u2717 ${{err.message}}`);
  }}"""

    script = f"""{extra_imports}
import {{ NotebookLMClient }} from './src/index.js';
import {{ ArtifactState }} from './src/types/artifact.js';

{_ts_client(creds)}

const results: Array<{{ sourceTitle: string; filePath: string }}> = [];

for (const job of {json.dumps(jobs)}) {{
  console.log(`Downloading: ${{job.sourceTitle}}`);
  const artifact = await sdk.artifacts.get(job.artifactId, '{notebook_id}');
  if (artifact.state !== ArtifactState.READY) {{
    console.log(`  \u26a0 Skipping \u2014 state: ${{artifact.state}}`);
    continue;
  }}
{dl_body}
}}

console.log('__RESULTS__' + JSON.stringify(results) + '__RESULTS__');
await sdk.dispose();
"""
    raw = run_ts("_tmp_download_artifacts", script)
    print(raw)
    results = json.loads(raw[raw.find("__RESULTS__") + 11 : raw.rfind("__RESULTS__")])
    if artifact_type in _DOWNLOAD_VIA_DOWNLOAD:
        for r in results:
            r["filePath"] = _rename_downloaded(r["filePath"])
    print(f"\n✅ Downloaded {len(results)} / {len(jobs)} artifact(s)  →  {output_dir}")
    for r in results:
        print(f"  {r['filePath']}")
    return results
