import os, databento as db
k = os.environ["DATABENTO_API_KEY"]
for label, kk in [("trailing newline", k + "\n"), ("trailing space", k + " "), ("CRLF", k + "\r\n"), ("quoted", f"\"{k}\""), ("missing db- prefix", k[3:])]:
    try:
        c = db.Historical(kk); r = c.metadata.list_datasets(); print(label, "-> OK", len(r))
    except Exception as e:
        print(label, "->", type(e).__name__, str(e).replace(chr(10), " | ")[:250])
os.environ.pop("DATABENTO_API_KEY")
try:
    db.Historical()
except Exception as e:
    print("no key ->", type(e).__name__, str(e)[:200])
l = db.Live(key=k)
try:
    l.subscribe(dataset="GLBX.MDP3", schema="trades", symbols="ES.c.0", stype_in="continuous")
    print("live subscribe -> returned without error")
except Exception as e:
    print("live subscribe ->", type(e).__name__, str(e)[:300])
