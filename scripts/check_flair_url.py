#!/usr/bin/env python3
"""
Check whether a Google Calendar flair image URL is still reachable (HTTP 200).

Uses the URL pattern from the repository README:
  https://ssl.gstatic.com/calendar/images/eventillustrations/2024_v2/img_[ID].svg

For phrases, candidate image ids are built by stripping non-alphanumeric characters
from each whitespace-separated word, then trying longest-to-shortest *prefixes* of
those stripped tokens joined (no underscores). Optional: digit "2" -> "to" for a
second try (e.g. back2school -> backtoschool).

Batch: --keywords-file en_us/keywords.md checks every keyword line (TSV to stdout).
Optional --cluster-report groups keywords that resolve to the same URL and flags
rows where trailing words did not change the winning id.

A 200 from gstatic only means the asset exists on the CDN, not that Google Calendar
still maps the keyword to that flair in the app.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = (
    "https://ssl.gstatic.com/calendar/images/eventillustrations/2024_v2/img_{id}.svg"
)


def _strip_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _leet_variants(blob: str) -> list[str]:
    if "2" not in blob:
        return [blob]
    alt = blob.replace("2", "to")
    return [blob, alt] if alt != blob else [blob]


def phrase_attempts(raw: str) -> list[tuple[str, str, int, int]]:
    """
    Ordered (id, url, tokens_used, total_tokens) to try; deduped by URL.
    Generates all combinations of keeping k tokens (from total n down to 1).
    """
    s = raw.strip()
    if s.startswith("http://") or s.startswith("https://"):
        return [("", s, 1, 1)]
    if "/" in s or s.endswith(".svg"):
        raise ValueError(
            "pass a full https URL, or an id/phrase without path slashes."
        )
    toks = [_strip_token(t) for t in s.split()]
    toks = [t for t in toks if t]
    if not toks:
        return []
    n = len(toks)
    seen_url: set[str] = set()
    out: list[tuple[str, str, int, int]] = []
    for k in range(n, 0, -1):
        for combo in itertools.combinations(toks, k):
            blob = "".join(combo)
            for sid in _leet_variants(blob):
                if not sid:
                    continue
                url = BASE.format(id=sid)
                if url in seen_url:
                    continue
                seen_url.add(url)
                out.append((sid, url, k, n))
    return out


def _request_head(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, url
    except urllib.error.HTTPError as e:
        if e.code in (405, 501):
            return _request_get(url, timeout)
        return e.code, url
    except urllib.error.URLError:
        return _request_get(url, timeout)


def _request_get(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, url
    except urllib.error.HTTPError as e:
        return e.code, url


def check_url(url: str, timeout: float) -> tuple[int, str]:
    return _request_head(url, timeout)


def check_phrase_with_winner(
    phrase: str, timeout: float
) -> tuple[int, str, str, int, int]:
    """
    Return (http_status, url, winner_id, tokens_used, total_tokens).
    On failure, winner_id is "" and tokens_used is 0; total_tokens is still set when known.
    """
    attempts = phrase_attempts(phrase)
    if not attempts:
        return 404, "", "", 0, 0
    n_tokens = attempts[0][3]
    last_code, last_url = 404, ""
    for sid, url, k, _n in attempts:
        code, final = check_url(url, timeout)
        if code == 200:
            return code, final, sid, k, n_tokens
        last_code, last_url = code, final
    return last_code, last_url, "", 0, n_tokens


def iter_keywords_md(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("See [") and "README" in line:
            continue
        out.append(line)
    return out


def _redundant_tail(code: int, ku: int, nt: int) -> str:
    if code == 200 and ku > 0 and nt > 0 and ku < nt:
        return "yes"
    return "no"


def _row_for_phrase(
    phrase: str, timeout: float
) -> tuple[str, int, str, str, int, int, str]:
    code, url, wid, ku, nt = check_phrase_with_winner(phrase, timeout)
    return phrase, code, url, wid, ku, nt, _redundant_tail(code, ku, nt)


def _run_batch(
    path: Path,
    timeout: float,
    jobs: int,
    no_header: bool,
    cluster_report: Path | None,
) -> int:
    keywords = iter_keywords_md(path)
    if not keywords:
        print("error: no keywords found in file", file=sys.stderr)
        return 2

    if not no_header:
        print(
            "keyword\thttp_status\turl\twinner_id\ttokens_used\ttotal_tokens\t"
            "redundant_tail",
            flush=True,
        )

    rows: list[
        tuple[str, int, str, str, int, int, str] | None
    ] = [None] * len(keywords)

    def work(i: int, phrase: str) -> tuple[int, tuple[str, int, str, str, int, int, str]]:
        return i, _row_for_phrase(phrase, timeout)

    if jobs <= 1:
        for i, phrase in enumerate(keywords):
            rows[i] = _row_for_phrase(phrase, timeout)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = [ex.submit(work, i, phrase) for i, phrase in enumerate(keywords)]
            for fut in as_completed(futures):
                i, row = fut.result()
                rows[i] = row

    ok = 0
    resolutions: list[tuple[str, int, str, str, int, int, str]] = []
    for row in rows:
        assert row is not None
        phrase, code, url, wid, ku, nt, redundant = row
        resolutions.append((phrase, code, url, wid, ku, nt, redundant))
        print(
            f"{phrase}\t{code}\t{url}\t{wid}\t{ku}\t{nt}\t{redundant}",
            flush=True,
        )
        if code == 200:
            ok += 1

    print(f"# summary: {ok}/{len(keywords)} returned HTTP 200", file=sys.stderr)

    if cluster_report is not None:
        _write_cluster_report(cluster_report, resolutions)

    return 0 if ok == len(keywords) else 1


def _write_cluster_report(
    path: Path,
    resolutions: list[tuple[str, int, str, str, int, int, str]],
) -> None:
    """Group keywords by resolved URL; flag redundant-tail rows."""
    by_url: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for phrase, code, url, wid, _ku, _nt, redundant in resolutions:
        if code != 200 or not url:
            continue
        by_url[url].append((phrase, wid, redundant))

    lines: list[str] = []
    lines.append("# flair_url_clusters.tsv - one row per keyword in a 200 cluster")
    lines.append("cluster_url\twinner_id\tkeyword\tredundant_tail")
    for url in sorted(by_url):
        for phrase, wid, redundant in sorted(by_url[url], key=lambda x: x[0].lower()):
            lines.append(f"{url}\t{wid}\t{phrase}\t{redundant}")

    lines.append("")
    lines.append("# cluster_index - one line per distinct image URL")
    lines.append("cluster_url\twinner_id\tkeyword_count\tredundant_tail_count")
    for url in sorted(by_url):
        rows_u = sorted(by_url[url], key=lambda x: x[0].lower())
        wid0 = rows_u[0][1]
        rc = sum(1 for _p, _w, r in rows_u if r == "yes")
        lines.append(f"{url}\t{wid0}\t{len(rows_u)}\t{rc}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"# cluster report written: {path}", file=sys.stderr)


def _print_attempt_line(code: int, final: str, sid: str, stream=sys.stdout) -> None:
    slug = sid if sid else "-"
    print(f"{code}\t{slug}\t{final}", file=stream)


def _emit_results(
    attempts: list[tuple[str, str, int, int]],
    timeout: float,
    show_all: bool,
) -> int:
    results: list[tuple[int, str, str, int, int]] = []
    for sid, url, k, n in attempts:
        code, final = check_url(url, timeout)
        results.append((code, final, sid, k, n))

    if show_all or len(results) == 1:
        for code, final, sid, k, n in results:
            _print_attempt_line(code, final, sid)
        return 0 if any(c == 200 for c, _f, s, ku, nt in results) else 1

    for code, final, sid, k, n in results:
        if code == 200:
            _print_attempt_line(code, final, sid)
            return 0

    print(
        "No candidate returned HTTP 200. Re-run with --all to list each URL tried.",
        file=sys.stderr,
    )
    for code, final, sid, _k, _n in results:
        _print_attempt_line(code, final, sid, stream=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(
        description="Check flair image URL reachability (see README URL template)."
    )
    p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Full https URL, image id (e.g. coffee), or a phrase to derive ids from",
    )
    p.add_argument(
        "--keywords-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Markdown file of keywords (one per non-empty block), e.g. en_us/keywords.md",
    )
    p.add_argument(
        "--cluster-report",
        type=Path,
        default=None,
        metavar="PATH",
        help="With --keywords-file, write URL clusters and redundant-tail flags (TSV)",
    )
    p.add_argument(
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Parallel workers when using --keywords-file (default: 1)",
    )
    p.add_argument(
        "--no-header",
        action="store_true",
        help="With --keywords-file, omit the TSV header row",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Seconds per request (default: 15)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="List every candidate (status, slug, url) instead of stopping at first 200",
    )
    args = p.parse_args()

    if bool(args.keywords_file) == bool(args.target):
        p.error("Provide exactly one of: TARGET (positional) or --keywords-file")

    if args.cluster_report is not None and args.keywords_file is None:
        p.error("--cluster-report requires --keywords-file")

    if args.keywords_file is not None:
        path = args.keywords_file
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2
        if args.all:
            p.error("--all applies only to single TARGET mode")
        if args.jobs < 1:
            p.error("--jobs must be >= 1")
        return _run_batch(
            path, args.timeout, args.jobs, args.no_header, args.cluster_report
        )

    raw = args.target.strip()
    try:
        attempts = phrase_attempts(raw)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not attempts:
        print("error: no id candidates for input", file=sys.stderr)
        return 2
    return _emit_results(attempts, args.timeout, args.all)


if __name__ == "__main__":
    raise SystemExit(main())
