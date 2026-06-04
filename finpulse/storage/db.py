import sqlite3

DB_PATH = "finpulse.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
                    CREATE TABLE IF NOT EXISTS headlines (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            text      TEXT NOT NULL,
            ticker    TEXT NOT NULL,
            score     REAL NOT NULL,
            label     TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
                    """)
    conn.commit()
    conn.close()

def insert_headline(text,ticker,score,label,timestamp):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO headlines (text, ticker, score, label, timestamp) VALUES (?, ?, ?, ?, ?)",
        (text, ticker, score, label, timestamp),
    )
    conn.commit()
    conn.close()

def fetch_all():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM headlines ORDER by id").fetchall()
    conn.close
    return rows