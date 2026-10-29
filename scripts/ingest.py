"""Screen and index files from the command line.

    python -m scripts.ingest data/sample_docs            # a folder (non-recursive)
    python -m scripts.ingest runbook.txt scan.xlsx       # individual files
    python -m scripts.ingest --reindex                   # rebuild the index from data/uploads/

Files go through the same screening guardrails as the UI; `--accept-review`
also ingests files whose relevance verdict is "needs review".
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.logging_setup import setup_logging
from src.guardrails.relevance import Verdict
from src.ingestion.pipeline import ingest_file, reindex_uploads
from src.ingestion.screening import discard, promote, screen_upload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--reindex", action="store_true", help="re-index everything in data/uploads/")
    parser.add_argument("--accept-review", action="store_true", help="ingest 'needs review' files too")
    args = parser.parse_args()
    setup_logging()

    if args.reindex:
        for report in reindex_uploads():
            print(f"[indexed ] {report.source}: {report.chunks} chunks" + (f", tables {report.tables}" if report.tables else ""))
        return 0

    files = [f for p in args.paths for f in (sorted(p.iterdir()) if p.is_dir() else [p]) if f.is_file()]
    if not files:
        parser.error("no files given")
    for path in files:
        result = screen_upload(path.name, path.read_bytes())
        accept = result.verdict is Verdict.ACCEPTED or (
            result.verdict is Verdict.NEEDS_REVIEW and args.accept_review
        )
        if not accept:
            discard(result)
            print(f"[{result.verdict.value:8}] {path.name}: {result.reason}")
            continue
        report = ingest_file(promote(result))
        extra = f", tables {report.tables}" if report.tables else ""
        flags = f", {report.untrusted_chunks} untrusted chunk(s)" if report.untrusted_chunks else ""
        print(f"[indexed ] {path.name}: {report.chunks} chunks{extra}{flags}  ({', '.join(result.domains)})")
        for warning in result.warnings:
            print(f"           ! {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
