# NotebookLM Kit — Notebooks

## Flashcard Pipeline (`notebooklm-flashcard-pipeline.ipynb`)

Generates one flashcard set per source in a notebook and downloads them as JSON.

**Steps:**

1. Load credentials via patchright (`credentials.json`) or `.env` cookies
2. Set `NOTEBOOK_ID`
3. Configure card count, difficulty, and an optional focus prompt
4. List sources in the notebook
5. Submit one flashcard job per source — jobs auto-saved to `jobs/flashcards/<yyyymmdd_hhmmss>_jobs.json`
6. Poll until all jobs are ready (or resume from a saved jobs file)
7. Download all sets to `outputs/flashcards/`

**Flashcard options:**
| Parameter | Values |
|---|---|
| `numberOfCards` | `1` = Fewer, `2` = Standard / More (value `3` is accepted but mapped to `2`) |
| `difficulty` | `1` = Easy, `2` = Medium, `3` = Hard |
| `language` | BCP-47 code (omit to use notebook default) |

---

## Video Pipeline (`notebooklm-video-pipeline.ipynb`)

Generates one video per source in a notebook and downloads them as MP4.

**Steps:**

1. Load credentials via patchright (`credentials.json`) or `.env` cookies
2. Set `NOTEBOOK_ID`
3. Configure format, visual style, and focus prompt (prompt lives in `config.py`)
4. List sources in the notebook
5. Submit one video job per source — jobs auto-saved to `jobs/video/<yyyymmdd_hhmmss>_jobs.json`
6. Poll until all jobs are ready (or resume from a saved jobs file)
7. Download all videos to `outputs/video/`

**Video options:**

| Parameter     | Value  | Description                       |
| ------------- | ------ | --------------------------------- |
| `format`      | `1`    | Explainer                         |
| `format`      | `2`    | Brief                             |
| `format`      | `3`    | Cinematic (ignores `visualStyle`) |
| `visualStyle` |        | Auto                              |
| `visualStyle` | `2`    | Classic                           |
| `visualStyle` | `3`    | Whiteboard                        |
| `visualStyle` | `4`    | Heritage                          |
| `visualStyle` |        | Kawaii                            |
| `visualStyle` |        | Anime                             |
| `visualStyle` |        | Watercolor                        |
| `visualStyle` |        | Retro-print                       |
| `visualStyle` | `9`    | Kawaii                            |
| `visualStyle` |        | Paper-craft                       |
| `language`    | BCP-47 | Omit to use notebook default      |

---

## Authentication

Two modes are supported — use whichever fits your setup:

**Patchright (recommended)**  
Run `python pipeline/login.py` once — opens a browser window, you log in to Google, session cookies are saved to `credentials.json`.  
All subsequent runs call `load_credentials(mode="patchright")`, which reads `credentials.json` and fetches a fresh auth token automatically. No browser opens again until cookies expire.

**Cookies (`.env`)**  
Add `NOTEBOOKLM_AUTH_TOKEN` and `NOTEBOOKLM_COOKIES` to `.env` (copy from your browser's DevTools), then call `load_credentials(mode="cookies")`.  
You must manually update these values whenever they expire.

---

## Output Structure

```
outputs/
  flashcards/   ← downloaded flashcard JSON files
  video/        ← downloaded MP4 files
jobs/
  flashcards/   ← submitted job records (<yyyymmdd_hhmmss>_jobs.json)
  video/        ← submitted job records (<yyyymmdd_hhmmss>_jobs.json)
```
