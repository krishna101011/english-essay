"""One-off cleanup for `corrections` rows that duplicate an existing
(version_id, category, start_offset, end_offset) span.

submit_version() now dedupes on this same key before persisting new
corrections (see app/documents/service.py), but that only prevents future
duplicates - rows already in the database from before that fix are never
retroactively touched. This script does that cleanup: for every duplicate
group it keeps the earliest row (lowest id, i.e. first inserted) and
removes the rest.

Report-only by default - prints what would be removed without deleting
anything:

    venv\\Scripts\\python scripts\\dedupe_existing_corrections.py

Add --apply to actually delete the duplicate rows:

    venv\\Scripts\\python scripts\\dedupe_existing_corrections.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker

from app.db.models import Correction, Document, DocumentVersion
from app.db.session import engine


def find_duplicate_groups(session):
    rows = (
        session.query(
            Correction.id,
            Correction.version_id,
            Correction.category,
            Correction.start_offset,
            Correction.end_offset,
        )
        .order_by(
            Correction.version_id,
            Correction.category,
            Correction.start_offset,
            Correction.end_offset,
            Correction.id,
        )
        .all()
    )
    groups = {}
    for correction_id, version_id, category, start_offset, end_offset in rows:
        key = (version_id, category, start_offset, end_offset)
        groups.setdefault(key, []).append(correction_id)
    return {key: ids for key, ids in groups.items() if len(ids) > 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the duplicate rows. Without this flag, only reports what would be removed.",
    )
    args = parser.parse_args()

    session = sessionmaker(bind=engine)()

    total_before = session.query(Correction).count()
    duplicate_groups = find_duplicate_groups(session)

    if not duplicate_groups:
        print(f"No duplicate correction rows found ({total_before} total rows).")
        return

    total_rows_to_remove = 0
    print(f"{len(duplicate_groups)} duplicate group(s) found:\n")
    for (version_id, category, start_offset, end_offset), ids in sorted(duplicate_groups.items()):
        version = session.get(DocumentVersion, version_id)
        document = session.get(Document, version.document_id) if version else None
        keep_id, remove_ids = ids[0], ids[1:]
        total_rows_to_remove += len(remove_ids)
        doc_label = f'document_id={document.id} ("{document.title}")' if document else "document_id=?"
        print(
            f"  {doc_label} version_id={version_id} version_number={version.version_number if version else '?'} "
            f"category={category.value} span=({start_offset},{end_offset}): "
            f"keeping correction id={keep_id}, removing {len(remove_ids)} duplicate(s) {remove_ids}"
        )

    print(f"\n{total_rows_to_remove} duplicate row(s) to remove out of {total_before} total correction rows.")

    if not args.apply:
        print("\nReport-only mode - nothing was deleted. Re-run with --apply to remove the duplicates.")
        return

    for ids in duplicate_groups.values():
        remove_ids = ids[1:]
        session.query(Correction).filter(Correction.id.in_(remove_ids)).delete(synchronize_session=False)
    session.commit()

    total_after = session.query(Correction).count()
    print(f"\nRemoved {total_rows_to_remove} duplicate row(s).")
    print(f"Correction row count: {total_before} -> {total_after}")


if __name__ == "__main__":
    main()
