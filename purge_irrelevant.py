"""Remove stored headlines that fail the per-ticker relevance filter (off-topic mis-tags).

Run this AFTER updating the `exclude` lists in config.py. It backs up finpulse.db first, prints
exactly which rows it removes (for transparency), then deletes them.
To undo: stop the server and copy finpulse.db.bak back over finpulse.db.

Run from the repo root:  python purge_irrelevant.py
"""

import shutil
import sqlite3

from finpulse.sentiment.ticker_tagger import is_relevant

DB = "finpulse.db"


def purge(dry_run=False):
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT id, ticker, text FROM headlines").fetchall()
    bad = [(hid, tk, tx) for hid, tk, tx in rows if not is_relevant(tx, tk)]

    print(f"{len(bad)} off-topic rows found (of {len(rows)} total):")
    for _hid, tk, tx in bad:
        print(f"  [{tk}] {tx[:72]}")

    if dry_run:
        print("(dry run — nothing deleted)")
        con.close()
        return len(bad)

    if bad:
        shutil.copyfile(DB, DB + ".bak")
        print(f"backup -> {DB}.bak")
        con.executemany("DELETE FROM headlines WHERE id = ?", [(hid,) for hid, _, _ in bad])
        con.commit()
    con.close()
    print(f"removed {len(bad)} rows.")
    return len(bad)


if __name__ == "__main__":
    purge()
