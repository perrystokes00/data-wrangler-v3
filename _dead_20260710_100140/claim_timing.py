"""Time each claim_batch as the queue drains — single process, no real work.
Shows whether claiming itself slows down progressively as rows go to 'done'."""
import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_core as wc
import work_queue as wq

engine = wc.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
wq.reset_queue(engine, only_claimed=False)

claimed_total = 0
i = 0
print("batch_no  claim_ms  mark_ms  rows  total_claimed")
while True:
    t = time.time()
    rows = wq.claim_batch(engine, "timing", batch_size=500)
    claim_ms = (time.time() - t) * 1000
    n = len(rows) if rows else 0
    if n == 0:
        print(f"  (empty claim — queue drained at {claimed_total})")
        break
    claimed_total += n
    i += 1
    # mark them done (mimics the pool finishing work) and time that too
    t = time.time()
    for r in rows:
        iid = r["INVENTORY_ID"] if isinstance(r, dict) else r.INVENTORY_ID
        try:
            wq.mark_done(engine, iid, 0)
        except Exception as ex:
            print("  mark err:", ex); break
    mark_ms = (time.time() - t) * 1000
    print(f"  {i:5}    {claim_ms:7.0f}  {mark_ms:7.0f}  {n:4}   {claimed_total}")
    if i > 30:
        print("  (stopping after 30 batches)")
        break
