"""Re-score every stored headline with the CURRENT sentiment engine.

Backs up finpulse.db -> finpulse.db.bak first, so this is fully reversible
(to undo: stop the server and copy finpulse.db.bak back over finpulse.db).

Run from the repo root:  python rescore.py
Force a specific engine first if needed (PowerShell):  $env:SENTIMENT_ENGINE='finbert'
"""

import shutil
import sqlite3

from finpulse.sentiment.analyzer import score, label, ENGINE

DB = "finpulse.db"


def rescore():
    shutil.copyfile(DB, DB + ".bak")
    print(f"backup -> {DB}.bak")
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT id, text FROM headlines").fetchall()
    print(f"re-scoring {len(rows)} headlines with engine={ENGINE} ...")
    for i, (hid, text) in enumerate(rows, 1):
        con.execute("UPDATE headlines SET score=?, label=? WHERE id=?",
                    (score(text), label(text), hid))
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}")
    con.commit()
    con.close()
    print("done.")


if __name__ == "__main__":
    rescore()
