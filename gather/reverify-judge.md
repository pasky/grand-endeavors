# Judge prompt: re-verify still-unverifiable legacy events (one section)

Used with `gather/reverify_legacy.py` (fetch first, then this judge, then `stage`).
One judge per batch of ~6 events (one judge for a whole section skimmed: it marked
34 of 38 unverifiable with a blanket note). Batches of one section may run in
parallel: their `fetch-url` calls are serialised by the script. Concatenate the
batch files into `<cache>/<section>/results-wayback2.jsonl` for `stage`.
Substitute {SECTION}, {REPO} (the code checkout), {CACHE} (the reverify cache dir),
{IDS} (the batch's event ids, one per line), {OUT} (the batch results file).

---

You are re-verifying old "legacy" events of the Grand Endeavors ledger, section
**{SECTION}**. Each event is one factual claim from a 2025 report, with the source URL(s)
the report cited. Earlier passes could not check them (dead pages, JS-only pages,
rate limits). The sources have now been fetched for you, live and as Wayback Machine
captures, into a local cache. Your job: decide for EACH of the events below whether the
fetched documents verify it, support a corrected version, refute it, or leave it
unverifiable, under a strict evidence rule.

Your events (judge every one of them individually and thoroughly — open its documents,
search them for the claim's subject, names and figures, and read the relevant
passages; a note must say specifically what the documents do and do not say):

{IDS}

## Inputs

- The events' records (claim, date, sources; one JSON per line, all of the section's
  pending events — judge only yours): `{CACHE}/{SECTION}/events.jsonl`
- Per event: `cd {REPO} && uv run gather/reverify_legacy.py show {SECTION} <event-id>`
  lists the cached documents (doc number, kind live/wayback/alt-*, ok, chars, URL).
  The text of doc NN is `{CACHE}/{SECTION}/<event-id>/NN.txt` (header lines, then
  TITLE/META/LD lines with the page's title, description and publication dates, then
  the body text). Documents can be long (PDFs): use `grep -n -i` with a few keywords
  and read around the hits with offset/limit; do not read huge files whole.
- Why earlier passes failed (context only, not evidence):
  `{REPO}/data/ledger/reverify/{SECTION}.2026-09-30.jsonl` and
  `{REPO}/data/ledger/reverify/{SECTION}.2026-10-01-wayback.jsonl`.

## The evidence rule (strict)

- Only text in a cached document counts. Never use background knowledge, memory,
  search-result snippets or "it is well known". If no document says it, it is unsupported.
- Every figure, date/year, named entity and qualifier ("first", "record", "half",
  "five missions") in a verified or corrected claim must be backed by a verbatim quote
  from a cached document of that event. The audit checks digits and years mechanically;
  you are responsible for the rest (spelled-out numbers, superlatives, attributions).
- Time matters: a page that changes over time (dashboard, company profile, running
  total, "latest" figures) supports a dated claim only in a capture from around the
  event's date (check the doc's Wayback timestamp; live = fetched today), unless the
  text itself dates the figure. META/LD dates can be a later re-publication or
  update; a date stated in the text wins.
- Quotes are copied exactly from the NN.txt file (whitespace and quote-mark style
  may differ; at least 15 characters). Quote enough context to show the metric scope.

## Results

- **verified**: the documents support the legacy claim exactly as worded (every detail).
- **corrected**: the core event is supported but some detail is unsupported or stated
  differently. Write a new claim containing ONLY supported content: one self-contained
  factual sentence (at least 6 words) with its numbers AND their metric scope, in the
  style of the legacy claim. Drop unsupported figures; if the source states a different
  value for the same quantity, use the source's value and say so in the note.
  A correction keeps the legacy claim's subject and metric: if the documents only
  support a different metric (e.g. an annual value for a long-term-average claim), a
  side remark, or something too vague to be useful on its own, the result is
  unverifiable, not corrected.
  If the documents date the event differently from the event's `date` (e.g. the claim
  is really about an October milestone, not the December date it was filed under), set
  `"date"` to the documented date (YYYY-MM-DD, YYYY-MM or YYYY) and quote it (year,
  month and day as far as given). A date after the event's `published` date must be a
  full YYYY-MM-DD: it also becomes the publication date. If the correction changes
  what kind of event it is (an "achievement" that is really a plan or forecast), set
  `"kind"` (achievement, announcement, projection, setback, data, analysis, policy).
- **refuted**: a document clearly contradicts the core of the claim (it did not happen,
  happened in a different year than the event's date, or the key figure is materially
  different such that the claim is wrong rather than imprecise). Give a tombstone claim
  starting exactly `Withdrawn after re-verification: ` then a short description of the
  event, ` - ` and the reason (e.g. "the archived report gives approx. 0.187 g, not 0.69 g").
  Absence of evidence is NOT refutation. Never refute from an alternative source: a
  different document may describe a different (earlier/later) event or paper.
- **unverifiable**: anything else (no usable document, the documents do not address the
  claim, paywall/JS shell, ambiguity).

## Alternative sources (only when the original is dead)

If NO cached document of an event has substantive text about its subject (every fetch
failed, or only a paywall / JS shell / error page / nav chrome came back), you may look
for the obvious alternative primary source: the organisation's own press release or
page, the paper itself, the official dataset/report page; else one reputable news report
of the same event. Find URLs with the web-search skill
(`/home/pasky/.pi/agent/packages/pi-amplike/skills/web-search/SKILL.md`), then fetch
them ONLY with

    cd {REPO} && uv run gather/reverify_legacy.py fetch-url {SECTION} <event-id> <url>

which records the document in the cache (it prints the new doc numbers) and also tries
Wayback captures. At most 3 alternative URLs per event. NEVER access archive.org /
web.archive.org yourself (no curl, no visit-webpage, no fetch tools): the script
serialises and throttles all archive.org access, and parallel access gets us blocked.
Do not use visit-webpage or other fetchers for evidence at all; only fetch-url documents
count. If the original source fetched fine but does not contain the claim, do not search
for alternatives: the result is unverifiable or corrected on what the document does say.

## Output

Write `{OUT}`, exactly one JSON object per line for each of your events:

    {"id": "<event-id>", "result": "verified|corrected|refuted|unverifiable",
     "claim": "<corrected claim | tombstone claim; omit for verified/unverifiable>",
     "sources": [{"url": "<source URL (the original or alternative URL, not a capture URL)>",
                  "title": "<publisher: title>", "primary": true|false}],
     "evidence": [{"doc": <doc number, integer>, "quote": "<verbatim text>"}],
     "date": "<only if corrected: the documented event date>",
     "kind": "<only if corrected and the kind changed>",
     "note": "<what was checked and found: which document/capture, key quotes in “”,
               what was dropped and why; for unverifiable: what was fetched and what it lacked>"}

`sources` = the source URL(s) whose documents back the claim (for verified/corrected);
a Wayback capture's source URL is its original URL (the script cites the capture itself).
`primary` = the issuing organisation's own publication.

Then run `cd {REPO} && uv run gather/reverify_legacy.py audit {SECTION} {OUT} --partial`
and fix every reported problem (make quotes verbatim, add the missing quote, or drop
the figure / downgrade the result) until it prints `audit OK`.

Final reply: counts per result, and one line per non-unverifiable event (id: result,
the gist). Keep it short.
