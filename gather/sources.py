#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Reference source lists (gather/sources/<section>.yaml; schema in gather/sources/README.md).

Curated primary sources per watch item, shown to gather intake agents as a starting
point (DESIGN.md §4 step 3). Not a whitelist: agents still search the open web.

    sources.py check [section...]     validate the files (default: all sections that have one)
    sources.py list <section> <topic>  the entries for one watch item (tagged with it or "*"),
                                       one line each, for the intake prompt
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "core"))
import ledger  # noqa: E402

DIR = os.path.join(HERE, "sources")
TIERS = ("primary", "secondary", "news")
REQUIRED = ("name", "url", "items", "covers", "cadence", "tier")
OPTIONAL = ("collector", "note")


def path(section: str) -> str:
    return os.path.join(DIR, f"{section}.yaml")


def load(section: str) -> list:
    """The section's entries ([] if it has no file). ValueError on a malformed file
    (anything but a mapping whose only key is a non-empty `sources` list)."""
    import yaml
    p = path(section)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as ex:
            raise ValueError(f"{p}: invalid YAML: {ex}") from None
    if not (isinstance(doc, dict) and list(doc) == ["sources"]
            and isinstance(doc["sources"], list) and doc["sources"]):
        raise ValueError(f"{p}: expected a mapping with one key, `sources:`, a non-empty list")
    return doc["sources"]


def check(section: str, entries: list[dict] | None = None) -> list[str]:
    if entries is None:
        try:
            entries = load(section)
        except ValueError as ex:
            return [str(ex)]
    topics = {t for t, _, _ in ledger.framework_items(section)} | {"*"}
    errs, seen = [], set()
    for i, e in enumerate(entries):
        where = f"{section}[{i}] {e.get('name', '?') if isinstance(e, dict) else e!r}"
        if not isinstance(e, dict):
            errs.append(f"{where}: not a mapping")
            continue
        errs += [f"{where}: missing {k}" for k in REQUIRED if not e.get(k)]
        errs += [f"{where}: unknown field {k}" for k in e if k not in REQUIRED + OPTIONAL]
        url = e.get("url") or ""
        if not str(url).startswith(("https://", "http://")):
            errs.append(f"{where}: bad url {url!r}")
        if url in seen:
            errs.append(f"{where}: duplicate url {url} (tag one entry with several items)")
        seen.add(url)
        if e.get("tier") and e["tier"] not in TIERS:
            errs.append(f"{where}: tier must be one of {TIERS}")
        items = e.get("items")
        if items is not None and not (isinstance(items, list) and items):
            errs.append(f"{where}: items must be a non-empty list")
        for t in items if isinstance(items, list) else []:
            if t not in topics:
                errs.append(f"{where}: unknown watch item {t!r} (valid: {', '.join(sorted(topics))})")
        if "collector" in e and e["collector"] is not True:
            errs.append(f"{where}: collector must be true (or omitted)")
    return errs


def for_item(section: str, topic: str, entries: list[dict] | None = None) -> list[dict]:
    """Entries tagged with the topic, then the section-wide ("*") ones; file order within each."""
    entries = load(section) if entries is None else entries
    return ([e for e in entries if topic in e["items"]]
            + [e for e in entries if "*" in e["items"] and topic not in e["items"]])


def line(e: dict) -> str:
    extra = "; partly fetched by the section collector" if e.get("collector") else ""
    return f"- {e['name']}: {e['url']} [{e['tier']}; {e['cadence']}{extra}] {e['covers']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("sections", nargs="*")
    li = sub.add_parser("list"); li.add_argument("section", choices=ledger.SECTIONS); li.add_argument("topic")
    a = ap.parse_args()
    if a.cmd == "check":
        bad = [s for s in a.sections if s not in ledger.SECTIONS]
        if bad:
            ap.error(f"unknown section(s): {' '.join(bad)}")
        sections = a.sections or [s for s in ledger.SECTIONS if os.path.exists(path(s))]
        errs = [x for s in sections for x in check(s)]
        for x in errs:
            print("ERROR", x)
        n = sum(len(load(s)) for s in sections) if not errs else "?"
        print(f"{n} sources in {len(sections)} section(s), {len(errs)} error(s)")
        return 1 if errs else 0
    topics = {t for t, _, _ in ledger.framework_items(a.section)}
    if a.topic not in topics:
        ap.error(f"unknown watch item {a.topic!r} for {a.section}")
    errs = check(a.section)
    if errs:   # a broken list must not silently vanish from the prompt
        print("\n".join(errs), file=sys.stderr)
        return 1
    entries = for_item(a.section, a.topic)
    print("\n".join(line(e) for e in entries) if entries else "(none listed for this item)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
