# Finks API evals

The public Finks API search quality site, served at https://finks-ai.github.io/finks-api-evals/. Everything here
is public and readable by anyone on the internet. It carries only aggregate scores of the Finks API release gates:
per gate, its day, its verdict, search relevance on development and held-out queries, found-in-top-5,
small-company on-topic share and screener screens passed.

## How it is built

1. finks-search-eval (private) writes `data/summary.json` with its `public_summary.py` after every release gate
   and commits it here, straight to `main` (its README, "Public summary");
2. the `render` check runs `render.py`, which refuses any key or value outside its schema (dates, scores from 0 to
   1, counts and the three verdict words only), renders `index.html` and `gates/index.html`, and runs `scan.py`,
   failing on any finding; then `pytest`;
3. on a push to `main`, the `deploy` job publishes the rendered site to GitHub Pages.

Every sentence on the pages is a constant in `render.py`; the summary can only supply numbers, dates and verdicts.
Because this repo is public, a commit is published the moment it is pushed, whatever the deploy does: render and
scan locally before every push (below).

## Updating the summary

```
python3 ../finks-search-eval/public_summary.py --out data/summary.json
python3 render.py --data data/summary.json --out _site     # schema check + leak scan; "refused: ..." stops here
git commit -am "summary $(date -u +%F)" && git push origin main
```

## Changing a page

Edit `render.py` and its tests, then update `tests/expected`:
`python render.py --data tests/summary.json --out /tmp/out && cp -R /tmp/out/. tests/expected/`, review the diff,
then `pytest -q`. A new field in the summary means extending `SCHEMA` here and `public_summary.py` together.

## Leak scan

`scan.py` (after finks-reports' scan) re-reads every rendered file and refuses anything outside the allowlisted
HTML shapes and generic leak shapes: AWS account ids and access keys, s3:// paths, URLs, dollar amounts, emails and
handles, PR and issue refs, snake_case identifiers, dotted names and hostnames, ARNs, UUIDs, hex ids and build
revisions, eval run ids, IP addresses, credential and token words, SQL, billing and cost words, and public vendor,
model and cloud service names. A finding names the file and rule, never the matched text.

## Never commit private values

Never commit query text, results, build revisions, PR numbers, table or column names, vendor or model names,
account ids, costs or any other private value here.
