"""Strip metadata from .ipynb files without touching cell outputs.
Used before committing notebooks for a clean git history.

Clears:
  - notebook-level metadata (kernelspec, language_info, etc.)
  - cell-level metadata (execution timestamps, collapsed, scrolled, etc.)
  - cell execution_count (reset to null)

Preserves:
  - cell outputs (all output types)
  - cell ids (required by nbformat >= 4.5)
  - cell source, cell_type, attachments

Usage:
  python strip_nb_metadata.py                   # all *.ipynb in cwd
  python strip_nb_metadata.py a.ipynb b.ipynb   # specific files
  python strip_nb_metadata.py --dry-run         # preview only, no writes
"""

import argparse
import json
import sys
from pathlib import Path


def strip(nb: dict) -> int:
    """Strip metadata in-place. Returns number of cells modified."""
    nb["metadata"] = {}
    changed = 0
    for cell in nb.get("cells", []):
        dirty = False
        if cell.get("metadata"):
            cell["metadata"] = {}
            dirty = True
        if cell.get("cell_type") == "code" and cell.get("execution_count") is not None:
            cell["execution_count"] = None
            dirty = True
        if dirty:
            changed += 1
    return changed


def process(path: Path, dry_run: bool) -> None:
    raw = path.read_text(encoding="utf-8")
    nb = json.loads(raw)
    changed = strip(nb)
    if changed == 0 and nb.get("metadata") == {}:
        print(f"  clean   {path}")
        return
    if dry_run:
        print(f"  dry-run {path}  ({changed} cell(s) would be modified)")
        return
    path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  cleaned {path}  ({changed} cell(s) modified)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", help=".ipynb files to process (default: all in cwd)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change without writing")
    args = parser.parse_args()

    paths = [Path(f) for f in args.files] if args.files else sorted(Path(".").glob("*.ipynb"))
    if not paths:
        print("No .ipynb files found.", file=sys.stderr)
        sys.exit(1)

    for p in paths:
        process(p, args.dry_run)


if __name__ == "__main__":
    main()
