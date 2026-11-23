"""Raw live-gateway handshake (no session start => no data, no cost).
Usage: python live_auth.py DATASET [good|badkey|cr|badds]"""
import hashlib, os, socket, sys, time

ds = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "good"
key = os.environ["DATABENTO_API_KEY"]
if mode == "badkey":
    key = key[:-5] + "XXXXX"
if mode == "cr":
    key = key + "\r"
host = ds.lower().replace(".", "-") + ".lsg.databento.com"
t0 = time.perf_counter()
s = socket.create_connection((host, 13000), timeout=10)
t_conn = time.perf_counter() - t0
f = s.makefile("rwb", buffering=0)
greet = [f.readline().decode().strip() for _ in range(2)]
t_greet = time.perf_counter() - t0
cram = greet[1].split("=", 1)[1]
digest = hashlib.sha256(f"{cram}|{key}".encode()).hexdigest()
bucket = key[-5:]
auth_ds = "GLBX.MDP3" if mode == "badds" else ds
f.write(f"auth={digest}-{bucket}|dataset={auth_ds}|encoding=dbn|ts_out=0\n".encode())
reply = f.readline().decode().strip()
t_auth = time.perf_counter() - t0
s.close()
# never print the key or digest
print(f"host={host} peer={s.getpeername() if False else ''} mode={mode}")
print(f"greeting={greet[0]} | cram=<{len(cram)} chars>")
print(f"reply={reply}")
print(f"connect_ms={t_conn*1000:.1f} greeting_ms={t_greet*1000:.1f} auth_ms={t_auth*1000:.1f}")
