#!/usr/bin/env python3
"""Check static local HTML references without executing pages or fetching URLs."""

import argparse
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit


ATTRIBUTES = {
    "a": ("href",), "area": ("href",), "link": ("href",),
    "img": ("src",), "script": ("src",), "iframe": ("src",),
    "audio": ("src",), "video": ("src", "poster"), "source": ("src",),
    "track": ("src",), "object": ("data",), "embed": ("src",),
    "image": ("href", "xlink:href"), "use": ("href", "xlink:href"),
}
EXCLUDED_DIRS = {".git", ".kb-local", "node_modules", "__pycache__", ".venv"}
MARKUP_SUFFIXES = {".html", ".htm", ".svg"}
LIMITS = [
    "Checks static file references; does not execute JavaScript or fetch websites.",
    "Does not inspect CSS URLs, srcset, dynamic routes, codecs, layout, or PPT playback.",
    "Anchor checking covers static HTML/SVG IDs and named anchors only.",
    "Skipped references and unexamined content are not verified successes.",
]


class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.base = ""
        self.ids = set()
        self.references = []
        self.feed(path.read_text(encoding="utf-8-sig"))
        self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "a" and values.get("name"):
            self.ids.add(values["name"])
        if tag == "base" and not self.base and values.get("href"):
            self.base = values["href"]
        for attr in ATTRIBUTES.get(tag, ()):
            if values.get(attr) and values[attr].strip():
                self.references.append((self.getpos()[0], tag, attr, values[attr].strip()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def as_url(value, base):
    value = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", value):
        return "file:///" + value
    return urljoin(base, value)


def local_target(value, base):
    """Return (path, fragment, skip_reason) without touching network shares."""
    parsed = urlsplit(as_url(value, base))
    if parsed.scheme.lower() != "file":
        return None, "", "non-local-address"
    if parsed.netloc.lower() not in ("", "localhost"):
        return None, "", "network-file-share"
    text = unquote(parsed.path)
    windows_drive = re.match(r"^/[A-Za-z]:/", text)
    if windows_drive:
        if os.name != "nt":
            return None, "", "windows-path-on-another-platform"
        text = text[1:]
    path = Path(text).resolve()
    if os.name == "nt" and str(path).startswith("\\\\"):
        return None, "", "network-file-share"
    return path, unquote(parsed.fragment), ""


def collect_html(inputs):
    found = set()
    for raw in inputs:
        path = Path(raw).resolve()
        if path.is_file():
            if path.suffix.lower() not in {".html", ".htm"}:
                raise ValueError("Input is not an HTML file: " + str(path))
            found.add(path)
        elif path.is_dir():
            for current, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRS]
                for name in files:
                    if Path(name).suffix.lower() in {".html", ".htm"}:
                        found.add((Path(current) / name).resolve())
        else:
            raise ValueError("Input does not exist: " + str(path))
    if not found:
        raise ValueError("No HTML files found in the specified inputs.")
    return sorted(found)


def check(paths, anchors=False):
    cache, broken, skipped = {}, [], []
    checked = 0

    def document(path):
        if path not in cache:
            cache[path] = Document(path)
        return cache[path]

    for source in paths:
        try:
            page = document(source)
        except (OSError, UnicodeError) as exc:
            broken.append({"source": str(source), "reason": "unreadable-html", "error": str(exc)})
            continue
        base = as_url(page.base, source.as_uri()) if page.base else source.as_uri()
        for line, tag, attr, value in page.references:
            item = {"source": str(source), "line": line, "attribute": tag + "." + attr,
                    "reference": value[:300]}
            try:
                target, fragment, skip = local_target(value, base)
            except (ValueError, OSError) as exc:
                broken.append(dict(item, reason="invalid-address", error=str(exc)))
                continue
            if skip:
                skipped.append(dict(item, reason=skip))
                continue
            checked += 1
            item["target"] = str(target)
            try:
                exists = target.exists()
            except OSError as exc:
                broken.append(dict(item, reason="unreadable-target", error=str(exc)))
                continue
            if not exists:
                broken.append(dict(item, reason="missing-file"))
                continue
            if anchors and fragment:
                if not target.is_file() or target.suffix.lower() not in MARKUP_SUFFIXES:
                    skipped.append(dict(item, reason="anchor-format-not-checked"))
                    continue
                try:
                    if fragment not in document(target).ids:
                        broken.append(dict(item, reason="missing-static-anchor", anchor=fragment))
                except (OSError, UnicodeError) as exc:
                    broken.append(dict(item, reason="unreadable-anchor-document", error=str(exc)))

    return {"summary": {"html_files": len(paths), "local_references_checked": checked,
                        "broken": len(broken), "skipped_checks": len(skipped),
                        "anchors_requested": anchors},
            "broken": broken, "skipped": skipped, "limits": LIMITS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="HTML files or directories to check")
    parser.add_argument("--anchors", action="store_true", help="Also check static HTML/SVG anchors")
    parser.add_argument("--report", type=Path, help="Write the complete JSON report to this path")
    args = parser.parse_args()
    try:
        paths = collect_html(args.inputs)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    report = check(paths, args.anchors)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("summary", "broken", "limits")},
                     ensure_ascii=False, indent=2))
    return 1 if report["broken"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
