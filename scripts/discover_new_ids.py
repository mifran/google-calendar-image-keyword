#!/usr/bin/env python3
import sys
import re
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://ssl.gstatic.com/calendar/images/eventillustrations/2024_v2/img_{id}.svg"

def check_id(sid: str, timeout: float = 10.0) -> tuple[int, str]:
    url = BASE.format(id=sid)
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, sid
    except urllib.error.HTTPError as e:
        # If HEAD is disallowed, fallback to GET (unlikely here, but just in case)
        if e.code in (405, 501):
            req_get = urllib.request.Request(url, method="GET")
            try:
                with urllib.request.urlopen(req_get, timeout=timeout) as resp_get:
                    return resp_get.status, sid
            except urllib.error.HTTPError as e2:
                return e2.code, sid
            except Exception:
                return 0, sid
        return e.code, sid
    except Exception:
        return 0, sid

def load_known_ids(cluster_tsv: Path) -> set[str]:
    known = set()
    if not cluster_tsv.is_file():
        return known
    
    lines = cluster_tsv.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            wid = parts[1]
            if wid != "winner_id" and wid != "-":
                known.add(wid)
    return known

def main():
    dict_path = Path("words_alpha.txt")
    if not dict_path.is_file():
        print("error: words_alpha.txt not found.", file=sys.stderr)
        return 1
        
    cluster_tsv = Path("en_us/flair_clusters.tsv")
    known_ids = load_known_ids(cluster_tsv)
    print(f"Loaded {len(known_ids)} known IDs to skip.", flush=True)

    words = dict_path.read_text(encoding="utf-8").splitlines()
    
    candidates = set()
    for w in words:
        sid = re.sub(r'[^a-z0-9]', '', w.lower())
        if sid and sid not in known_ids:
            candidates.add(sid)
            
    # Optional: We could also apply the `2` -> `to` leet variant just in case
    # there are words with '2' in them in other dictionaries, but words_alpha.txt is mostly letters.

    print(f"Testing {len(candidates)} new unique candidate IDs...", flush=True)
    
    out_file = Path("new_discovered_ids.tsv")
    if not out_file.exists():
        with out_file.open("w", encoding="utf-8") as f:
            f.write("id\turl\n")
            
    found_count = 0
    checked_count = 0
    total = len(candidates)
    
    # We use 50 workers. At roughly 50 req/sec, ~370,000 requests will take ~2 hours.
    with out_file.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=50) as ex:
        futs = {ex.submit(check_id, sid): sid for sid in candidates}
        for fut in as_completed(futs):
            code, sid = fut.result()
            checked_count += 1
            if code == 200:
                url = BASE.format(id=sid)
                print(f"FOUND 200: {sid}\t{url}", flush=True)
                f.write(f"{sid}\t{url}\n")
                f.flush()
                found_count += 1
                
            if checked_count % 5000 == 0:
                print(f"Progress: {checked_count}/{total} checked. Found {found_count} new so far...", flush=True)

    print(f"\nDone! Checked {total} candidates. Found {found_count} new IDs.", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())