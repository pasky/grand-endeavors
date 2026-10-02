#!/usr/bin/env python3
"""Regression tests for the bulletin/round-up gate (views/validate.py).

Run:  uv run views/tests/test_validate.py      (no network; builds a throwaway ledger)
Each case pins a behavior that a review found broken or easy to regress.
The fixture ledger is shared with core/tests/test_ledger.py (core/tests/ledger_fixture.py).
"""
import json
import os
import sys
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(REPO, "core", "tests"), os.path.join(REPO, "views")]
from ledger_fixture import fixture, has, kpi, ledger, obs, write_csv  # noqa: E402
import validate  # noqa: E402

FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def main():
    case("roundup numbers(): unit suffix + no partial decimals",
         validate.numbers("9% $8.99B 12.5GW in 2025 the") == {"9", "8.99", "12.5"})

    fixture()
    pdir = f"{kpi.ROOT}/pilot-26H1"
    snap = ledger.snapshot(pdir, "climate")
    chart = kpi.chart(pdir, "climate", ["co2-mlo-annual"], label="year", since="2021")

    # --- bulletin gate (validate --snapshot) --------------------------------------------------
    sp = f"{pdir}/snapshot/climate.json"
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    json.dump(snap, open(sp, "w"))
    names = [n for items in ledger.readme_topics("climate").values() for _, n in items]
    doc = (f"# Climate\n\nCO2 was 431.43 ppm in June 2026[^a].\n\n{chart}\n\n"
           + "\n".join(f"### {n}\nNo significant developments." for n in names)
           + "\n\n[^a]: [GCB](https://x.org/2026-05-13-gcb-final)\n")
    dp = f"{pdir}/climate.md"

    def gate(text):
        open(dp, "w").write(text)
        validate.ERRORS.clear(); validate.WARNS.clear()
        validate.check_snapshot(dp, text, sp)
        return list(validate.ERRORS)
    case("bulletin gate: faithful bulletin passes", gate(doc) == [])
    case("bulletin gate: number not in snapshot is caught", has(gate(doc.replace("431.43 ppm", "431.43 ppm (about 432)")), "number 432"))
    case("bulletin gate: URL outside the snapshot is caught", has(gate(doc.replace("https://x.org/2026-05-13-gcb-final", "https://evil.org/x")), "not a source"))
    case("bulletin gate: unreported KPI headline is caught", has(gate(doc.replace("431.43 ppm", "high")), "not reported"))
    case("bulletin gate: uncovered milestone is caught", has(gate(doc.replace("### The Bend", "### Something")), "The Bend"))
    case("bulletin gate: a name only in prose (no heading) does not count as coverage",
         has(gate(doc.replace("### The Bend\n", "The Bend is mentioned.\n")), "The Bend"))
    case("bulletin gate: charts come from the frozen snapshot, not today's ledger",
         (write_csv(ledger.path("observations", "climate"), ledger.OBS_COLUMNS,
                    [list(r.values())[:11] for r in ledger.observations("climate")]
                    + [obs("co2-mlo-annual", "2020", "414.21", "2021-01-10", "rule")]) or True)
         and gate(doc) == [])
    old = {k: v for k, v in snap.items() if k not in ("series", "framework")}
    json.dump(old, open(sp, "w"))
    case("pre-freeze snapshots fail explicitly (no silent live-ledger fallback)",
         has(gate(doc), "predates"))
    json.dump(snap, open(sp, "w"))

    # --- footnote / reference-link integrity (CommonMark label semantics) ---------------------
    def refs(text):
        validate.ERRORS.clear(); validate.WARNS.clear()
        prose = validate.strip_code(text)
        validate.check_footnotes(prose)
        validate.check_reference_links(prose)
        return list(validate.ERRORS), list(validate.WARNS)
    case("refs: duplicate footnote definition is an error",
         has(refs("A[^a].\n\n[^a]: one\n[^A]: two\n")[0], "[^a] defined 2 times"))
    case("refs: duplicate reference definition is an error",
         has(refs("See [x][gcb].\n\n[gcb]: https://a.org\n  [GCB]: https://b.org\n")[0], "defined 2 times"))
    case("refs: definitions indented up to 3 spaces count",
         refs("A[^a] and [x][r].\n\n   [^a]: note\n   [r]: https://a.org\n") == ([], []))
    case("refs: 4-space indent is a code block, not a definition",
         has(refs("A[^a].\n\n    [^a]: note\n")[0], "[^a] used but never defined"))
    case("refs: labels match case-insensitively with collapsed whitespace",
         refs("A[^Note] and [x][Global  Carbon\nBudget].\n\n[^note]: n\n[global carbon budget]: https://a.org\n") == ([], []))
    case("refs: shortcut [label] counts as a use when defined",
         refs("Per the [GCB] data.\n\n[gcb]: https://a.org\n") == ([], []))
    case("refs: unused definition still warns",
         has(refs("Nothing.\n\n[gcb]: https://a.org\n")[1], "[gcb] never used"))
    case("refs: footnotes inside inline code are ignored",
         refs("Write `[^x]` or ``a ` [^y]`` to cite.\n") == ([], []))
    case("refs: a definition in inline code is not a definition",
         has(refs("A[^a].\n\n`[^a]: x`\n")[0], "[^a] used but never defined"))
    case("refs: realistic paragraph has no false positives",
         refs("CO2 [ppm] rose ([NOAA](https://x.org/a)) in [June 2026], see [chart] below[^1][^2]. "
              "- [ ] todo, [x] done, ![img](i.png), `[^z]` and arr[0].\n\n"
              "```\n[^q]\n[a][b]\n```\n\n[^1]: [GCB](https://x.org/g)\n[^2]: Ibid.\n") == ([], []))
    case("URLs with balanced parentheses are extracted whole",
         validate.extract_urls("[x](https://a.org/S0092-8674(25)00284-3).") == ["https://a.org/S0092-8674(25)00284-3"])

    # --- link probe (mocked, no network) -----------------------------------------------------
    def seq(*codes):
        it = iter(codes)

        def fake(req, timeout=15):
            c = next(it)
            if c == 200:
                m = mock.MagicMock()
                m.__enter__.return_value.status = 200
                return m
            raise urllib.error.HTTPError(req.full_url, c, "x", {}, None)
        return fake

    with mock.patch("time.sleep"):
        for codes, want, name in [
            ((404, 200), "ok", "HEAD 404 then GET 200 is alive"),
            ((404, 404, 200), "ok", "one transient GET 404 is retried"),
            ((404, 404, 404), "404", "two GET 404s are dead"),
            ((403, 403), "403", "403 stays warn-level (not dead)"),
        ]:
            with mock.patch("urllib.request.urlopen", seq(*codes)):
                case(name, validate.probe("https://x.org/p") == want)

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
