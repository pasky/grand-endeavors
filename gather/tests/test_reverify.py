#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml", "brotli"]
# ///
"""Offline tests for gather/reverify_legacy.py: the mechanical audit of judged
results (the strict quote-per-figure rule) and the ledger records built from them.

Run:  uv run gather/tests/test_reverify.py      (no network; temp ledger + cache)
"""
import gzip
import json
import os
import sys
import tempfile

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(GATHER), "core", "tests"))
from ledger_fixture import ev, fixture, write_jsonl  # noqa: E402

sys.path.insert(0, GATHER)
import reverify_legacy as rv  # noqa: E402

FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def main():
    root = fixture()
    rv.ledger.DATA = root
    rv.CACHE = tempfile.mkdtemp()
    legacy = ev("2025-03-01-acme-plant", "2025-03-02", "Acme opened a 500 MW solar plant in Spain in March 2025.",
                status="legacy", collector="backfill:pilot-2025/climate.md")
    legacy["verification"] = {"status": "legacy", "by": "migration", "at": "2026-09-29"}
    write_jsonl(f"{root}/ledger/events/climate.jsonl", [legacy])
    src = legacy["sources"][0]["url"]
    cap = f"https://web.archive.org/web/20250305000000id_/{src}"
    rv.save_manifest("climate", legacy["id"], [
        {"n": 1, "url": src, "source_url": src, "kind": "live", "ok": False, "error": "HTTP 404"},
        {"n": 2, "url": cap, "source_url": src, "kind": "wayback", "ok": True, "timestamp": "20250305000000"}])
    with open(rv.doc_path("climate", legacy["id"], 2), "w") as f:
        f.write("Madrid, 3 March 2025 — Acme today opened its 450 MW solar plant near Seville.\n")

    def res(**kw):
        return {"id": legacy["id"], "note": "n", "sources": [{"url": src, "title": "Acme", "primary": True}],
                "evidence": [{"doc": 2, "quote": "Madrid, 3 March 2025 — Acme today opened its 450 MW solar plant"}]} | kw

    good = res(result="corrected", claim="Acme opened a 450 MW solar plant in Spain in March 2025.")
    errs = rv.cmd_audit("climate", [good])
    case("audit passes a corrected claim whose figures are quoted (typographic dash normalised)", errs == [])
    errs = rv.cmd_audit("climate", [res(result="verified")])
    case("audit: a legacy figure absent from every quote fails 'verified'", any("figure 500" in e for e in errs))
    bad = res(result="corrected", claim="Acme opened a 450 MW solar plant in Spain in March 2024.")
    case("audit: an unquoted year fails", any("year 2024" in e for e in rv.cmd_audit("climate", [bad])))
    bad = res(result="corrected", claim=good["claim"], evidence=[{"doc": 2, "quote": "Acme today opened its 450 MW plant"}])
    case("audit: a paraphrased quote fails", any("not verbatim" in e for e in rv.cmd_audit("climate", [bad])))
    bad = res(result="corrected", claim=good["claim"], sources=[{"url": "https://other.org/x", "title": "o"}])
    case("audit: a source that was never fetched fails", any("was not fetched" in e for e in rv.cmd_audit("climate", [bad])))
    bad = res(result="corrected", claim=good["claim"], evidence=[{"doc": 1, "quote": "Acme today opened its 450 MW solar"}])
    case("audit: a failed fetch is no evidence", any("not a fetched document" in e for e in rv.cmd_audit("climate", [bad])))
    case("audit: every pending event needs a result", any("no result" in e for e in rv.cmd_audit("climate", [])))

    _, recs = rv.build_records("climate", [good], "reverify-wayback2:test:2026-10-12", "2026-10-12")
    r = recs[0]
    case("corrected -> -rv replacement superseding the legacy id, capture cited",
         r["id"] == legacy["id"] + "-rv" and r["supersedes"] == [legacy["id"]] and r["verification"]["status"] == "corrected"
         and [s["url"] for s in r["sources"]] == [src, cap] and r["collector"] == "reverify:backfill:pilot-2025/climate.md")
    moved = good | {"date": "2025-03-03"}
    case("a corrected event date (quoted) moves the replacement's id", rv.cmd_audit("climate", [moved]) == []
         and rv.build_records("climate", [moved], "b", "2026-10-12")[1][0]["id"] == "2025-03-03-acme-plant-rv")
    case("audit: an unquoted corrected date fails",
         any("corrected date" in e for e in rv.cmd_audit("climate", [good | {"date": "2024-12"}])))
    tomb = res(result="refuted", claim="Withdrawn after re-verification: Acme's Spanish solar plant - the capture says 450 MW, not 500 MW.")
    case("audit: a tombstone may restate the legacy figure", rv.cmd_audit("climate", [tomb]) == [])
    _, recs2 = rv.build_records("climate", [tomb], "b", "2026-10-12")
    t = recs2[0]
    case("refuted -> withdrawal tombstone", t["id"] == legacy["id"] + "-wd" and t.get("withdrawn") is True
         and t["kind"] == "retraction" and t["published"] == "2026-10-12")
    for name, extra in (("replacement", r), ("tombstone", t)):
        errs, _ = rv.ledger.validate_state("climate", [legacy, extra], [], [])
        case(f"the {name} validates as a ledger record", errs == [])

    # fetch plumbing
    case("gzip-encoded raw captures are decoded", rv._decode(gzip.compress(b"<p>hi</p>"), "") == b"<p>hi</p>")
    case("archive.org rate-limit page is an interstitial (retry)",
         rv.Net._interstitial("https://web.archive.org/web/1id_/x", b"<html><title>429 Too Many Requests</title>") == "retry")
    txt = rv.html_text(b'<html><head><title>T</title><script type="application/ld+json">'
                       + json.dumps({"datePublished": "2025-03-03", "headline": "H"}).encode()
                       + b'</script><script>var x=1</script></head><body><p>Body &amp; text</p></body></html>', "")
    case("html text keeps title, JSON-LD dates and body, drops scripts",
         "TITLE: T" in txt and "datePublished: 2025-03-03" in txt and "Body & text" in txt and "var x" not in txt)
    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
