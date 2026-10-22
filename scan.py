"""The leak scan for the rendered Finks API evals site (Finks-ai/finks-api-evals), after finks-reports' scan.py.

`scan` re-reads every written file: HTML may use only TAGS and ATTRS, hrefs stay on the site, text is ASCII
(plus `·`), and no text, attribute value or CSS may match LEAKS, per node and joined across nodes after NFKC.
A finding names the file and rule, never the matched text. Only generic shapes and public vendor names are
checked here; this repo must contain no private value.
"""

import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

FILES = ("index.html", "gates/index.html")

TAGS = frozenset(
    "html head meta title style body main header nav h1 h2 p div span a table tr th td dl dt dd".split()
)
INLINE = frozenset({"a", "span"})
ATTRS = frozenset("lang charset name content class href".split())
HREF = re.compile(r"(\.\./)?([a-z]+/)?")
LEAKS = {
    "AWS account id": r"(?<!\d)\d{12}(?!\d)",
    "AWS access key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "s3:// path": r"(?i)s3://",
    "URL": r"(?i)\b[a-z][a-z0-9+.-]*://|\bwww\.",
    "dollar amount": r"\$",
    "email or handle": r"@",
    "PR or issue ref": r"(?i)#\d|/pull/|/issues/|\bPR ?\d",
    "snake_case identifier": r"[A-Za-z0-9]_[A-Za-z0-9]",
    "dotted name or hostname": r"(?i)\b[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*",
    "ARN": r"(?i)\barn:",
    "UUID": r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-",
    "hex id or build": r"(?i)\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,}\b|\b[0-9a-f]{12,}\b",
    "run id": r"\d{8}T\d{6}Z",
    "IP address": r"\b\d{1,3}(\.\d{1,3}){3}\b",
    "credential word": r"(?i)\b(secrets?|passwords?|api ?keys?|credentials?|bearer)\b|\b(access|auth|api|bearer)[ _-]?tokens?\b",
    "token word": r"(?i)\btokens?\b",
    "SQL": r"(?i)\bselect\b[\s\S]*\bfrom\b",
    "billing word": r"(?i)\b(usd|dollars?|credits?|invoices?|billing|spend|costs?)\b",
    "vendor or model name": r"(?i)\b(openai|anthropic|claude|gpt|gemini|deepseek|llama|mistral|qwen|cohere|aws|amazon|"
    r"azure|gcp|clickhouse|dagster|lambda|ecs)\b",
}


class Leak(Exception):
    pass


def leaks(text: str, where: str) -> list[str]:
    """LEAKS over the NFKC-normalised text without format characters (zero-width, bidi), plus non-ASCII as written."""
    norm = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")
    found = [f"{where}: {name}" for name, p in LEAKS.items() if re.search(p, norm)]
    if re.search(r"[^\x00-\x7f\u00b7]", text):
        found.append(f"{where}: non-ASCII text")
    return found


class _Scan(HTMLParser):
    def __init__(self, where: str):
        super().__init__(convert_charrefs=True)
        self.where, self.found, self.text, self.in_style = where, [], [], False

    def handle_starttag(self, tag, attrs):
        if tag not in TAGS:
            self.found.append(f"{self.where}: tag <{tag}>")
        self.in_style = tag == "style"
        if tag not in INLINE:  # joined text keeps inline runs together, as rendered
            self.text.append("\n")
        for k, v in attrs:
            if k not in ATTRS:
                self.found.append(f"{self.where}: attribute {k}")
            elif k == "href" and not HREF.fullmatch(v or ""):
                self.found.append(f"{self.where}: off-site href")
            else:
                self.found += leaks(v or "", f"{self.where} {k}=")

    def handle_endtag(self, tag):
        self.in_style = False
        if tag not in INLINE:
            self.text.append("\n")

    def handle_data(self, data):
        if self.in_style:  # no comments, generated content, escapes or external references; colors aside, LEAKS
            if re.search(r"(?i)/\*|(?<![\w-])content\s*:|\\|url\(|@import|expression\(|//", data):
                self.found.append(f"{self.where}: CSS comment, content, escape or external reference")
            self.found += leaks(re.sub(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?\b", "", data), f"{self.where} CSS")
        else:
            self.text.append(data)
            self.found += leaks(data, self.where)

    def handle_comment(self, data):
        self.found.append(f"{self.where}: comment")

    def handle_decl(self, decl):
        if decl.lower() != "doctype html":
            self.found.append(f"{self.where}: declaration")

    def unknown_decl(self, data):
        self.found.append(f"{self.where}: CDATA or unknown declaration")

    def handle_pi(self, data):
        self.found.append(f"{self.where}: processing instruction")


def scan(root: Path) -> None:
    """Raise Leak naming file and rule (never the matched text) for anything outside the allowlisted shapes: only
    FILES, no symlinks."""
    found = []
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            found.append(f"{rel}: symlink")
        elif p.is_dir():
            continue
        elif rel not in FILES:
            found.append(f"{rel}: unexpected file")
        else:
            s = _Scan(rel)
            s.feed(p.read_text())
            s.close()
            found += s.found + leaks("".join(s.text), f"{rel} (joined text)")
    if found:
        raise Leak("public site scan failed:\n  " + "\n  ".join(sorted(set(found))))
