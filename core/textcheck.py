"""Text-only rewording check for assessment records (gather/assess.sh reader pass,
gather/editorial.py): a reworded record may change only its label and rationale, keeps
its verdict word (the label before its first colon), and states no number the drafted
record lacks. A number counts as present when it occurs in the drafted record (its basis
included) or is one of the record's numbers rounded to fewer decimals (7.9 -> 8,
1.79 -> 1.8), so a reword may round but never compute a new figure.

    python3 core/textcheck.py <draft.jsonl> <reworded.jsonl>
prints the number of records whose text changed; exit 1 when any pair breaks the rules.
Standard library only (assess.sh runs it with plain `uv run python`).
"""
import json
import re
import sys

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
TEXT = ("label", "rationale")


def _value(tok: str) -> tuple[float, int] | None:
    """(value, decimals) of a number token: commas are thousands separators
    ("1,673"); None for anything else ("2016,17", "1.2.3")."""
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", tok):
        t = tok.replace(",", "")
        return float(t), len(t.split(".")[1]) if "." in t else 0
    return None


def numbers_ok(text: str, record: dict) -> list[str]:
    """The number tokens of `text` that the record neither contains nor rounds to."""
    toks = set(NUM_RE.findall(json.dumps(record, ensure_ascii=False)))
    have = [v for v in map(_value, toks) if v]
    bad = []
    near = lambda x, d, v: abs(x - v[0]) < 1e-9 or d > v[1] and abs(x - v[0]) <= 0.5 * 10 ** -v[1] + 1e-9
    for m in re.finditer(NUM_RE.pattern + r"(\s?%)?", str(text)):
        tok = m.group(0).rstrip("% ")
        if tok in toks:  # a whole number token, not a substring ("3" is not in "2034")
            continue
        v = _value(tok)
        # the same value ("1,673" = 1673), or rounded: x has more decimals and lies within half a
        # unit of the token's last digit; "96%" may state a share of 0.96 (p_achieved)
        if not (v and any(near(x, d, v) or m.group(1) and 0 < x <= 1 and near(100 * x, max(d - 2, 0), v)
                          for x, d in have)):
            bad.append(tok)
    return bad


def verdict(r: dict) -> str:
    return str(r.get("label", "")).split(":", 1)[0]


def problems(draft: dict, new: dict) -> list[str]:
    rest = lambda r: {k: v for k, v in r.items() if k not in TEXT}
    out = []
    if rest(draft) != rest(new):
        out.append("changed more than label/rationale")
    if verdict(draft) != verdict(new):
        out.append(f"verdict word {verdict(draft)!r} -> {verdict(new)!r}")
    bad = numbers_ok(f"{new.get('label', '')} {new.get('rationale', '')}", draft)
    if bad:
        out.append("number(s) not in the drafted record: " + ", ".join(bad))
    return out


def main(a_path: str, b_path: str) -> int:
    a, b = ([json.loads(ln) for ln in open(p, encoding="utf-8") if ln.strip()] for p in (a_path, b_path))
    errs = [] if len(a) == len(b) else [f"{len(a)} drafted vs {len(b)} reworded records"]
    for x, y in zip(a, b):
        errs += [f"{x.get('id')}: {p}" for p in problems(x, y)]
    print(sum(tuple(x.get(k) for k in TEXT) != tuple(y.get(k) for k in TEXT) for x, y in zip(a, b)))
    for e in errs:
        print(f"textcheck: {e}", file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
