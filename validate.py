#!/usr/bin/env python3
"""Deterministic, no-LLM validation gate for a generated newsletter section.

Run AFTER the review stage. Catches mechanical defects the LLM review can miss
(and can't be talked out of): footnote/reference integrity, mermaid chart
axis/series length mismatches, dead citation URLs, and (optional) coverage of
the run's PLAN slugs.

Usage:
    uv run validate.py <section.md> [--plan PLAN.txt] [--research DIR]

Exit status: 0 if no ERRORs (WARNs allowed), 1 otherwise.
Env:
    NO_NET=1   skip the network link check entirely.
"""
import argparse
import os
import re
import sys
import urllib.request
import urllib.error

ERRORS: list[str] = []
WARNS: list[str] = []


def strip_code(text: str) -> str:
    """Remove fenced code blocks so footnote/ref scanning ignores code/mermaid."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNS.append(msg)


# --- footnote + reference-link integrity ------------------------------------
def check_footnotes(text: str) -> None:
    # Definitions like:  [^id]: ....   (at line start)
    defs = set(re.findall(r"(?m)^\[\^([^\]]+)\]:", text))
    # Any [^id] occurrence; the ones immediately followed by ':' are defs.
    all_refs = re.findall(r"\[\^([^\]]+)\](:?)", text)
    used = {rid for rid, colon in all_refs if colon != ":"}
    for rid in sorted(used - defs):
        err(f"footnote [^{rid}] used but never defined")
    for rid in sorted(defs - used):
        warn(f"footnote [^{rid}] defined but never used")


def check_reference_links(text: str) -> None:
    # Reference-style definitions:  [label]: url    (label not a footnote ^id)
    defs = set(re.findall(r"(?m)^\[([^\]^][^\]]*)\]:\s*\S+", text))
    # Reference-style usages:  [text][label]  and collapsed  [label][].
    # Require neither bracket to start with '^' so adjacent footnotes like
    # [^a][^b] are NOT misread as a reference link.
    used = set(re.findall(r"\[[^\]^][^\]]*\]\[([^\]^][^\]]*)\]", text))
    used |= set(re.findall(r"\[([^\]^][^\]]*)\]\[\]", text))
    for label in sorted(used - defs):
        err(f"reference link [{label}] used but never defined")
    for label in sorted(defs - used):
        warn(f"reference link definition [{label}] never used")


# --- mermaid xychart axis/series consistency --------------------------------
def check_mermaid(text: str) -> None:
    blocks = re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)
    for i, block in enumerate(blocks, 1):
        if "xychart" not in block:
            continue
        xs = re.findall(r"x-axis\s+\[([^\]]*)\]", block)
        if not xs:
            warn(f"mermaid xychart #{i}: no x-axis array found")
            continue
        xn = len([c for c in xs[0].split(",") if c.strip()])
        for kind, arr in re.findall(r"^\s*(line|bar)\s+\[([^\]]*)\]", block, re.M):
            n = len([c for c in arr.split(",") if c.strip()])
            if n != xn:
                err(f"mermaid xychart #{i}: {kind} has {n} points but x-axis has {xn}")


# --- citation URL liveness --------------------------------------------------
def extract_urls(text: str) -> list[str]:
    raw = re.findall(r"https?://[^\s)\]<>\"']+", text)
    seen, out = set(), []
    for u in raw:
        u = u.rstrip(".,;:")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def check_links(text: str) -> None:
    if os.environ.get("NO_NET"):
        warn("link check skipped (NO_NET=1)")
        return
    for url in extract_urls(text):
        status = probe(url)
        if status in ("404", "410"):
            err(f"citation URL appears dead ({status}): {url}")
        elif status != "ok":
            # 403/5xx/redirect-loops/network errors are NOT hard failures: many
            # valid sources block bots or HEAD, or time out transiently.
            warn(f"citation URL uncertain ({status}, not a hard 404): {url}")


def probe(url: str) -> str:
    # Try HEAD then GET. A definitive 404/410 is returned immediately; any other
    # HEAD failure (403/405/5xx or socket error) falls through to GET, since many
    # servers reject HEAD but serve GET. Network-level failures map to "neterr"
    # (warn-level), never a hard "dead".
    last = "neterr"
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": "Mozilla/5.0 (validate.py)"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return "ok" if r.status < 400 else str(r.status)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return str(e.code)
            last = str(e.code)
            continue  # HEAD blocked/unsupported or 5xx — retry with GET
        except Exception:
            last = "neterr"  # timeout / DNS / TLS / connection — transient, warn
            continue
    return last


# --- coverage: every PLAN slug's note is cited in the output -----------------
def check_coverage(text: str, plan_path: str | None, research_dir: str | None) -> None:
    if not plan_path or not os.path.exists(plan_path):
        return
    urls_in_doc = set(extract_urls(text))
    with open(plan_path) as f:
        slugs = [
            ln.split("|", 1)[0].strip()
            for ln in f
            if ln.strip() and not ln.lstrip().startswith("#") and "|" in ln
        ]
    for slug in slugs:
        note = os.path.join(research_dir or "", f"{slug}.md") if research_dir else None
        if not note or not os.path.exists(note):
            warn(f"coverage: no research note found for plan slug '{slug}'")
            continue
        note_urls = set(extract_urls(open(note).read()))
        if note_urls and not (note_urls & urls_in_doc):
            warn(
                f"coverage: none of the {len(note_urls)} source URLs from note "
                f"'{slug}' appear in the output (item may be uncited/dropped)"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--plan")
    ap.add_argument("--research")
    args = ap.parse_args()

    text = open(args.doc, encoding="utf-8").read()
    prose = strip_code(text)  # footnote/ref checks ignore fenced code/mermaid
    check_footnotes(prose)
    check_reference_links(prose)
    check_mermaid(text)
    check_coverage(text, args.plan, args.research)
    check_links(text)  # network last (slowest)

    for w in WARNS:
        print(f"  WARN  {w}")
    for e in ERRORS:
        print(f"  ERROR {e}")
    n_e, n_w = len(ERRORS), len(WARNS)
    print(f"\nvalidation: {n_e} error(s), {n_w} warning(s) — {args.doc}")
    return 1 if n_e else 0


if __name__ == "__main__":
    sys.exit(main())
