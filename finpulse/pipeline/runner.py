import queue, threading, time 
from datetime import datetime, timezone

from finpulse.ingestion.news_simulator import get_headlines
from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import tag
from finpulse.storage.db import init_db, insert_headline

q = queue.Queue()

def producer():
    """ def producer onto queue every half second(like live feed)"""
    for h in get_headlines():
        q.put(h)
        time.sleep(0.5)

def consumer():
    """pull headlines of the queue score + tag them and write them to database"""
    while True:
        h = q.get()
        if h is None:
            break
        s = score(h)
        lab = label(h)
        ts = datetime.now(timezone.utc).isoformat()
        for ticker in tag(h):
            insert_headline(h,ticker,s,lab,ts)
            print(f"saved{ticker:6s} {s:+.3f} {lab:8s} {h}")
        q.task_done()
    
def run():
    init_db()
    t_cons = threading.Thread(target = consumer)
    t_prod = threading.Thread(target = producer)
    t_cons.start()
    t_prod.start()
    t_prod.join()
    q.put(None)
    t_cons.join()

if __name__ == "__main__":
    run()

