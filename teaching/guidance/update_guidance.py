#!/usr/bin/env python3
"""Download dissertation guidance notes from Dropbox and publish HTML pages safely."""

from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


DROPBOX_FOLDER_URL = (
    "https://www.dropbox.com/scl/fo/hehgs9rqpjf4lopqxxtod/"
    "AMwKexGXCRuz7cpMuHl3A_A"
    "?rlkey=lepf8wydkv36697a7c1ad42g8&st=2vndl8an&dl=1"
)

IGNORED_DIRECTORY_NAMES = {"guidance notes online"}
WEB_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
MINIMUM_CONVERTED_TEXT_LENGTH = 120
TEMPLATE_VERSION = "1"


@dataclass(frozen=True)
class Note:
    slug: str
    source: str
    output: str
    title: str
    description: str
    pdf_url: str


NOTES = (
    Note(
        slug="getting-started",
        source="Getting Started with your Dissertation.tex",
        output="getting-started.html",
        title="Getting Started with Your Dissertation",
        description="Guidance by Arthur Galichère on getting started with an economics dissertation.",
        pdf_url=(
            "https://www.dropbox.com/scl/fi/39dgnnt0nqzxzjnbkxoe7/"
            "Getting-Started-with-your-Dissertation.pdf"
            "?rlkey=h3ch13gj4z0f6jds83ey456s9&st=6dlbom4l&dl=1"
        ),
    ),
    Note(
        slug="writing-dissertation",
        source="A Guide to writing your Dissertation.tex",
        output="writing-dissertation.html",
        title="A Guide to Writing Your Dissertation",
        description="Guidance by Arthur Galichère on writing an economics dissertation.",
        pdf_url=(
            "https://www.dropbox.com/scl/fi/1unhpr8pmujck02cnqy2z/"
            "A-Guide-to-writing-your-Dissertation.pdf"
            "?rlkey=b6rj35sb9hql0hsfc5a2hf8lz&st=jnxjdp8q&dl=1"
        ),
    ),
    Note(
        slug="literature-review",
        source="A Guide to writing your Literature Review.tex",
        output="literature-review.html",
        title="A Guide to Writing Your Literature Review",
        description="Guidance by Arthur Galichère on writing a literature review for an economics dissertation.",
        pdf_url=(
            "https://www.dropbox.com/scl/fi/es6yhoobdindeqhrip37y/"
            "A-Guide-to-writing-your-Literature-Review.pdf"
            "?rlkey=hh09xo8pqs4dna7hxb0qisqt7&st=sxqdxiy4&dl=1"
        ),
    ),
    Note(
        slug="dissertation-structure",
        source="Structure of the dissertation.tex",
        output="dissertation-structure.html",
        title="Structure of the Dissertation",
        description="Guidance by Arthur Galichère on structuring an economics dissertation.",
        pdf_url=(
            "https://www.dropbox.com/scl/fi/70uu4hmon81ekrnwunlsq/"
            "Structure-of-the-dissertation.pdf"
            "?rlkey=s1on52nrda7vc3ffhn5x5q7qf&st=tn1rx8v4&dl=1"
        ),
    ),
)


class GuidanceUpdateError(RuntimeError):
    def __init__(self, stage: str, message: str, note: str | None = None):
        self.stage = stage
        self.note = note
        location = f"[{stage}]"
        if note:
            location += f"[{note}]"
        super().__init__(f"{location} {message}")


class ImageSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attributes = dict(attrs)
        source = attributes.get("src")
        if source:
            self.sources.append(source)


def log(stage: str, message: str, note: str | None = None) -> None:
    prefix = f"[{stage}]"
    if note:
        prefix += f"[{note}]"
    print(f"{prefix} {message}", flush=True)


def repo_paths() -> tuple[Path, Path, Path]:
    """Return the repository root, guidance directory, and supervision template.

    This script lives in ``teaching/guidance/``. Generated guidance pages and
    their images are published beside the script, while the shared template is
    read from ``teaching/supervision.html``.
    """
    script_path = Path(__file__).resolve()
    guidance_dir = script_path.parent
    teaching_dir = guidance_dir.parent
    repo_root = teaching_dir.parent
    supervision_template = teaching_dir / "supervision.html"
    return repo_root, guidance_dir, supervision_template


def direct_download_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query["dl"] = ["1"]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query, doseq=True), parsed.fragment)
    )


def download_dropbox_zip(destination: Path) -> None:
    log("DOWNLOAD", "Downloading the shared Dropbox guidance folder.")
    request = urllib.request.Request(
        direct_download_url(DROPBOX_FOLDER_URL),
        headers={"User-Agent": "Arthur-Galichere-Guidance-Updater/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output)
    except urllib.error.HTTPError as exc:
        raise GuidanceUpdateError(
            "DOWNLOAD",
            f"Dropbox returned HTTP {exc.code} ({exc.reason}). Check that the folder link is public and downloadable.",
        ) from exc
    except urllib.error.URLError as exc:
        raise GuidanceUpdateError(
            "DOWNLOAD",
            f"Could not reach Dropbox: {exc.reason}.",
        ) from exc
    except (TimeoutError, OSError) as exc:
        raise GuidanceUpdateError(
            "DOWNLOAD",
            f"The Dropbox download could not be completed: {exc}.",
        ) from exc

    size = destination.stat().st_size if destination.exists() else 0
    if size < 1_000:
        raise GuidanceUpdateError(
            "DOWNLOAD",
            f"The downloaded archive is unexpectedly small ({size} bytes; content type: {content_type or 'unknown'}).",
        )

    if not zipfile.is_zipfile(destination):
        preview = destination.read_bytes()[:80]
        raise GuidanceUpdateError(
            "ZIP_VALIDATE",
            "Dropbox did not return a valid ZIP archive. "
            f"The first bytes were {preview!r}; verify the shared-folder URL and dl=1 setting.",
        )

    log("DOWNLOAD", f"Downloaded a valid ZIP archive ({size:,} bytes).")


def safe_extract_zip(archive: Path, destination: Path) -> None:
    log("ZIP_EXTRACT", "Validating and extracting the Dropbox archive.")
    destination_resolved = destination.resolve()

    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            if not members:
                raise GuidanceUpdateError("ZIP_EXTRACT", "The Dropbox ZIP archive is empty.")

            for member in members:
                path = PurePosixPath(member.filename)

                if path.is_absolute() or ".." in path.parts:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Unsafe archive path rejected: {member.filename!r}.",
                    )

                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Symbolic links are not permitted in the archive: {member.filename!r}.",
                    )

                target = (destination / Path(*path.parts)).resolve()
                if os.path.commonpath((destination_resolved, target)) != str(destination_resolved):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Archive entry escapes the extraction directory: {member.filename!r}.",
                    )

            zipped.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise GuidanceUpdateError("ZIP_EXTRACT", f"The ZIP archive could not be read: {exc}.") from exc
    except OSError as exc:
        raise GuidanceUpdateError("ZIP_EXTRACT", f"The ZIP archive could not be extracted: {exc}.") from exc

    log("ZIP_EXTRACT", f"Extracted {len(members)} archive entries safely.")


def ignored_path(path: Path) -> bool:
    return any(part.casefold() in IGNORED_DIRECTORY_NAMES for part in path.parts)


def locate_source_root(extracted: Path) -> Path:
    log("SOURCE_DISCOVERY", "Locating the four allowlisted TeX source files.")
    candidates: list[Path] = []

    for directory in [extracted, *(path for path in extracted.rglob("*") if path.is_dir())]:
        try:
            relative = directory.relative_to(extracted)
        except ValueError:
            continue

        if ignored_path(relative):
            continue

        if all((directory / note.source).is_file() for note in NOTES):
            candidates.append(directory)

    if not candidates:
        expected = ", ".join(note.source for note in NOTES)
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "Could not find one directory containing all four expected TeX files. "
            f"Expected exact filenames: {expected}.",
        )

    candidates.sort(key=lambda path: (len(path.relative_to(extracted).parts), str(path).casefold()))
    source_root = candidates[0]

    if len(candidates) > 1:
        alternatives = ", ".join(str(path.relative_to(extracted)) or "." for path in candidates[1:])
        log(
            "SOURCE_DISCOVERY",
            f"Multiple source roots matched; using {source_root.relative_to(extracted) or Path('.')}. "
            f"Ignored alternatives: {alternatives}.",
        )

    for note in NOTES:
        source_path = source_root / note.source
        if source_path.stat().st_size < 20:
            raise GuidanceUpdateError(
                "SOURCE_VALIDATE",
                f"The TeX source is unexpectedly small ({source_path.stat().st_size} bytes).",
                note.slug,
            )

    log("SOURCE_DISCOVERY", f"Using source directory: {source_root}.")
    return source_root


def decode_tex(path: Path, note: Note) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GuidanceUpdateError("SOURCE_DECODE", "The TeX source encoding could not be decoded.", note.slug)


def command_argument(text: str, command: str) -> str | None:
    pattern = re.compile(rf"\\{re.escape(command)}\s*\{{")
    match = pattern.search(text)
    if not match:
        return None

    depth = 1
    start = match.end()
    index = start
    while index < len(text):
        if text[index] == "{" and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif text[index] == "}" and (index == 0 or text[index - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[start:index]
        index += 1
    return None


def strip_document_wrapper(tex: str) -> tuple[str, str | None]:
    title = command_argument(tex, "title")
    begin = re.search(r"\\begin\s*\{document\}", tex)
    end_matches = list(re.finditer(r"\\end\s*\{document\}", tex))

    if begin:
        tex = tex[begin.end() : end_matches[-1].start() if end_matches else len(tex)]

    tex = re.sub(r"\\maketitle\b", "", tex)
    return tex.strip(), title


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\\(?:textbf|textit|emph)\s*\{([^{}]*)\}", r"\1", value)
    value = value.replace("~", " ")
    value = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", "", value)
    value = value.replace("{", "").replace("}", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def require_pandoc() -> str:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            "Pandoc is not installed or is not available on PATH. Install Pandoc before running the updater.",
        )

    try:
        result = subprocess.run(
            [pandoc, "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise GuidanceUpdateError("DEPENDENCY", f"Pandoc could not be executed: {exc}.") from exc

    first_line = result.stdout.splitlines()[0] if result.stdout else "unknown version"
    log("DEPENDENCY", f"Using {first_line}.")
    return pandoc


def convert_tex_to_fragment(pandoc: str, source: Path, work_dir: Path, note: Note) -> tuple[str, str | None]:
    log("CONVERT", f"Preparing and converting {source.name}.", note.slug)
    tex = decode_tex(source, note)
    body, tex_title = strip_document_wrapper(tex)

    if len(body.strip()) < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "SOURCE_VALIDATE",
            f"The TeX document body contains fewer than {MINIMUM_CONVERTED_TEXT_LENGTH} characters.",
            note.slug,
        )

    prepared_source = work_dir / f"{note.slug}.tex"
    prepared_source.write_text(body, encoding="utf-8")

    command = [
        pandoc,
        str(prepared_source),
        "--from=latex",
        "--to=html5",
        "--mathjax",
        "--wrap=none",
    ]

    try:
        result = subprocess.run(
            command,
            cwd=source.parent,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GuidanceUpdateError("CONVERT", "Pandoc timed out after 120 seconds.", note.slug) from exc
    except OSError as exc:
        raise GuidanceUpdateError("CONVERT", f"Pandoc could not be started: {exc}.", note.slug) from exc

    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout or "No diagnostic was produced.").strip()
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc exited with status {result.returncode}: {diagnostic[:1_500]}",
            note.slug,
        )

    if result.stderr.strip():
        log("CONVERT_WARNING", result.stderr.strip()[:1_500], note.slug)

    fragment = result.stdout.strip()
    if not fragment:
        raise GuidanceUpdateError("CONVERT_VALIDATE", "Pandoc produced an empty HTML fragment.", note.slug)

    return fragment, normalize_title(tex_title)


def html_text_length(fragment: str) -> int:
    without_scripts = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", fragment, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    text = html.unescape(without_tags)
    return len(re.sub(r"\s+", " ", text).strip())


def normalize_image_reference(source: str) -> str | None:
    source = source.strip()
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme or source.startswith(("//", "data:", "#")):
        return None

    decoded = urllib.parse.unquote(parsed.path).replace("\\", "/")
    path = PurePosixPath(decoded)
    if path.is_absolute() or ".." in path.parts:
        raise GuidanceUpdateError("IMAGE_SECURITY", f"Unsafe image reference rejected: {source!r}.")

    parts = list(path.parts)
    if parts and parts[0].casefold() == "images":
        parts = parts[1:]
    if not parts:
        return None
    return PurePosixPath(*parts).as_posix()


def resolve_image(source_images: Path, reference: str, note: Note) -> Path:
    candidate = source_images / Path(*PurePosixPath(reference).parts)
    if candidate.is_file():
        return candidate

    if candidate.suffix:
        matches = [
            path
            for path in source_images.rglob("*")
            if path.is_file()
            and path.relative_to(source_images).as_posix().casefold() == reference.casefold()
        ]
    else:
        stem = PurePosixPath(reference).name.casefold()
        parent = PurePosixPath(reference).parent.as_posix().casefold()
        matches = []
        for path in source_images.rglob("*"):
            if not path.is_file() or path.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
                continue
            relative = path.relative_to(source_images)
            if relative.stem.casefold() == stem and relative.parent.as_posix().casefold() == parent:
                matches.append(path)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(str(path.relative_to(source_images)) for path in matches)
        raise GuidanceUpdateError(
            "IMAGE_RESOLVE",
            f"Image reference {reference!r} is ambiguous. Matches: {choices}.",
            note.slug,
        )

    raise GuidanceUpdateError(
        "IMAGE_MISSING",
        f"The converted note references {reference!r}, but no matching file exists in the top-level images folder.",
        note.slug,
    )


def rewrite_and_collect_images(
    fragment: str,
    source_images: Path | None,
    staging_images: Path,
    note: Note,
) -> tuple[str, set[str]]:
    parser = ImageSourceParser()
    try:
        parser.feed(fragment)
    except Exception as exc:
        raise GuidanceUpdateError("IMAGE_PARSE", f"Could not inspect converted image references: {exc}.", note.slug) from exc

    referenced: set[str] = set()
    replacements: dict[str, str] = {}

    for source in parser.sources:
        reference = normalize_image_reference(source)
        if reference is None:
            continue
        if source_images is None or not source_images.is_dir():
            raise GuidanceUpdateError(
                "IMAGE_MISSING",
                f"The note references {source!r}, but the Dropbox archive has no top-level images directory.",
                note.slug,
            )

        source_path = resolve_image(source_images, reference, note)
        relative = source_path.relative_to(source_images)
        if source_path.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            raise GuidanceUpdateError(
                "IMAGE_FORMAT",
                f"Image {relative} uses unsupported format {source_path.suffix or '(none)'}. "
                f"Use one of: {', '.join(sorted(WEB_IMAGE_EXTENSIONS))}.",
                note.slug,
            )

        destination = staging_images / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)

        new_source = "images/" + urllib.parse.quote(relative.as_posix(), safe="/.-_~")
        replacements[source] = new_source
        referenced.add(relative.as_posix())

    for old, new in replacements.items():
        escaped = re.escape(old)
        fragment = re.sub(
            rf"(?P<prefix>\bsrc\s*=\s*['\"]){escaped}(?P<suffix>['\"])",
            lambda match: f"{match.group('prefix')}{new}{match.group('suffix')}",
            fragment,
            flags=re.I,
        )

    return fragment, referenced


def extract_template_parts(template: str) -> tuple[str, str, str]:
    nav_match = re.search(r"<nav\b[^>]*class=[\"'][^\"']*index-nav[^\"']*[\"'][^>]*>.*?</nav>", template, re.I | re.S)
    footer_match = re.search(r"<footer\b[^>]*class=[\"'][^\"']*foot[^\"']*[\"'][^>]*>.*?</footer>", template, re.I | re.S)
    style_match = re.search(r"<style\b[^>]*>(.*?)</style>", template, re.I | re.S)

    missing = []
    if not nav_match:
        missing.append("navigation (.index-nav)")
    if not footer_match:
        missing.append("footer (.foot)")
    if not style_match:
        missing.append("style block")
    if missing:
        raise GuidanceUpdateError(
            "TEMPLATE_PARSE",
            "The supervision template is missing: " + ", ".join(missing) + ".",
        )

    nav = nav_match.group(0)
    footer = footer_match.group(0)
    styles = style_match.group(1).strip()
    return nav, footer, styles


def adapt_template_paths(fragment: str) -> str:
    replacements = {
        'href="../index.html"': 'href="../../index.html"',
        'href="../cv.html"': 'href="../../cv.html"',
        'href="../research.html"': 'href="../../research.html"',
        'href="../teaching.html"': 'href="../../teaching.html"',
        'href="../economics.html"': 'href="../../economics.html"',
        "href='../index.html'": "href='../../index.html'",
        "href='../cv.html'": "href='../../cv.html'",
        "href='../research.html'": "href='../../research.html'",
        "href='../teaching.html'": "href='../../teaching.html'",
        "href='../economics.html'": "href='../../economics.html'",
        'href="index.html"': 'href="../../index.html"',
        'href="cv.html"': 'href="../../cv.html"',
        'href="research.html"': 'href="../../research.html"',
        'href="teaching.html"': 'href="../../teaching.html"',
        'href="economics.html"': 'href="../../economics.html"',
    }
    for old, new in replacements.items():
        fragment = fragment.replace(old, new)
    return fragment


def guidance_styles() -> str:
    return """
    .guidance-body { padding: 3rem 2.5rem; }

    .guidance-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 2rem;
    }

    .back-link,
    .download-link {
      display: inline-flex;
      align-items: center;
      gap: 0.55rem;
      padding: 0.7rem 0.95rem;
      color: var(--accent-strong);
      background: var(--accent-soft);
      border: 1px solid rgba(59, 90, 117, 0.25);
      border-radius: 4px;
      font-size: 0.86rem;
      font-weight: 600;
      text-decoration: none;
      transition: color 0.16s ease, background-color 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
    }

    .back-link:hover,
    .download-link:hover {
      color: #fff;
      background: var(--accent);
      border-color: var(--accent);
      transform: translateY(-1px);
    }

    .guidance-title {
      margin-bottom: 2rem;
      font-family: var(--display);
      font-size: 2.5rem;
      font-weight: 700;
      line-height: 1.15;
    }

    .guidance-content {
      color: var(--ink-soft);
      font-size: 0.96rem;
      line-height: 1.72;
    }

    .guidance-content > * + * { margin-top: 1rem; }

    .guidance-content h1,
    .guidance-content h2,
    .guidance-content h3,
    .guidance-content h4 {
      color: var(--accent-strong);
      font-family: var(--display);
      line-height: 1.3;
    }

    .guidance-content h1,
    .guidance-content h2 {
      padding-bottom: 0.4rem;
      margin-top: 2.6rem;
      margin-bottom: 1rem;
      font-size: 1.35rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      border-bottom: 1px solid var(--line-strong);
    }

    .guidance-content h3 {
      margin-top: 2rem;
      margin-bottom: 0.75rem;
      font-size: 1.18rem;
    }

    .guidance-content h4 {
      margin-top: 1.5rem;
      margin-bottom: 0.6rem;
      font-size: 1rem;
    }

    .guidance-content p { text-align: justify; }

    .guidance-content ul,
    .guidance-content ol {
      display: grid;
      gap: 0.45rem;
      padding-left: 1.5rem;
    }

    .guidance-content li::marker { color: var(--accent); }

    .guidance-content a {
      color: var(--accent);
      font-weight: 600;
      text-decoration-line: underline;
      text-decoration-color: rgba(59, 90, 117, 0.35);
      text-underline-offset: 0.16em;
    }

    .guidance-content a:hover {
      color: var(--accent-strong);
      text-decoration-color: var(--accent-strong);
    }

    .guidance-content img {
      display: block;
      width: auto;
      max-width: 100%;
      height: auto;
      margin: 1.5rem auto;
      border: 1px solid var(--line);
      border-radius: 4px;
    }

    .guidance-content figure { margin: 1.5rem 0; }

    .guidance-content figcaption {
      margin-top: 0.55rem;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.5;
      text-align: center;
    }

    .guidance-content blockquote {
      padding: 1rem 1.2rem;
      color: var(--ink-soft);
      background: var(--paper-soft);
      border-left: 4px solid var(--accent);
    }

    .guidance-content table {
      width: 100%;
      margin: 1.5rem 0;
      border-collapse: collapse;
      font-size: 0.9rem;
    }

    .guidance-content th,
    .guidance-content td {
      padding: 0.7rem;
      border: 1px solid var(--line-strong);
      text-align: left;
      vertical-align: top;
    }

    .guidance-content th {
      color: var(--accent-strong);
      background: var(--accent-soft);
    }

    .guidance-content code {
      padding: 0.12rem 0.3rem;
      background: var(--paper-soft);
      border: 1px solid var(--line);
      border-radius: 3px;
      font-family: var(--mono);
      font-size: 0.88em;
    }

    .guidance-content pre {
      max-width: 100%;
      padding: 1rem;
      overflow-x: auto;
      background: var(--paper-soft);
      border: 1px solid var(--line-strong);
      border-radius: 4px;
    }

    .guidance-content pre code {
      padding: 0;
      background: transparent;
      border: none;
    }

    .guidance-update {
      margin-top: 3rem;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.78rem;
      letter-spacing: 0.03em;
      text-align: center;
    }

    @media (max-width: 768px) {
      .guidance-body { padding: 2rem 1.5rem; }
    }

    @media (max-width: 680px) {
      .guidance-toolbar {
        align-items: stretch;
        flex-direction: column;
      }

      .back-link,
      .download-link { justify-content: center; }

      .guidance-title { font-size: 2.15rem; }
    }
    """.strip()


def source_digest(tex_content: str, note: Note, image_digests: dict[str, str]) -> str:
    payload = {
        "template_version": TEMPLATE_VERSION,
        "slug": note.slug,
        "source": tex_content,
        "pdf_url": note.pdf_url,
        "images": image_digests,
    }
    serialized = repr(payload).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def existing_metadata(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None, None

    digest_match = re.search(r'<meta\s+name="guidance-source-digest"\s+content="([0-9a-f]{64})"\s*/?>', content, re.I)
    date_match = re.search(r'<meta\s+name="guidance-updated"\s+content="(\d{4}-\d{2}-\d{2})"\s*/?>', content, re.I)
    return (
        digest_match.group(1) if digest_match else None,
        date_match.group(1) if date_match else None,
    )


def render_page(
    note: Note,
    fragment: str,
    nav: str,
    footer: str,
    template_styles: str,
    digest: str,
    updated: str,
) -> str:
    safe_title = html.escape(note.title)
    safe_description = html.escape(note.description, quote=True)
    safe_pdf = html.escape(note.pdf_url, quote=True)
    safe_digest = html.escape(digest, quote=True)
    safe_updated = html.escape(updated, quote=True)
    formatted_updated = date.fromisoformat(updated).strftime("%d/%m/%Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arthur Galichère — {safe_title}</title>
  <meta name="description" content="{safe_description}" />
  <meta name="guidance-source-digest" content="{safe_digest}" />
  <meta name="guidance-updated" content="{safe_updated}" />

  <link rel="icon" type="image/png" href="../../website/images/favicon_transparant.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bitter:ital,wght@0,400;0,600;0,700;1,400&family=Montserrat:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>

  <style>
{template_styles}

{guidance_styles()}
  </style>
</head>
<body>
  <main class="page">
    <article class="card">
      {nav}

      <section class="guidance-body">
        <div class="guidance-toolbar">
          <a href="../dissertation.html" class="back-link">
            <i class="fas fa-arrow-left" aria-hidden="true"></i>
            Back to Dissertation Supervision and Guidance
          </a>
          <a href="{safe_pdf}" class="download-link">
            <i class="fas fa-download" aria-hidden="true"></i>
            Download PDF
          </a>
        </div>

        <h1 class="guidance-title">{safe_title}</h1>
        <div class="guidance-content">
{fragment}
        </div>
        <p class="guidance-update">Information updated on {formatted_updated}</p>
      </section>

      {footer}
    </article>
  </main>
</body>
</html>
"""


def validate_generated_page(path: Path, note: Note, referenced_images: set[str]) -> None:
    log("PAGE_VALIDATE", f"Validating {path.name}.", note.slug)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuidanceUpdateError("PAGE_VALIDATE", f"Could not read generated page: {exc}.", note.slug) from exc

    required_fragments = (
        "<!DOCTYPE html>",
        note.title,
        'class="index-nav"',
        'href="../dissertation.html"',
        note.pdf_url.replace("&", "&amp;"),
        'class="guidance-content"',
        'class="foot',
        'name="guidance-source-digest"',
        'name="guidance-updated"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in content]
    if missing:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            "Generated page is missing required content: " + ", ".join(repr(item) for item in missing) + ".",
            note.slug,
        )

    content_match = re.search(r'<div class="guidance-content">(.*?)</div>\s*<p class="guidance-update">', content, re.I | re.S)
    if not content_match:
        raise GuidanceUpdateError("PAGE_VALIDATE", "Could not locate the generated guidance-content block.", note.slug)

    text_length = html_text_length(content_match.group(1))
    if text_length < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            f"Generated page contains only {text_length} visible characters; expected at least {MINIMUM_CONVERTED_TEXT_LENGTH}.",
            note.slug,
        )

    suspicious = re.findall(r"\\(?:begin|end|section|subsection|includegraphics|documentclass)\b", content_match.group(1))
    if suspicious:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            "Generated page still contains unresolved LaTeX commands: " + ", ".join(sorted(set(suspicious))) + ".",
            note.slug,
        )

    for image in referenced_images:
        image_path = path.parent / "images" / Path(*PurePosixPath(image).parts)
        if not image_path.is_file():
            raise GuidanceUpdateError(
                "PAGE_VALIDATE",
                f"Generated page references missing staged image: images/{image}.",
                note.slug,
            )


def directory_manifest(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    manifest: dict[str, str] = {}
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        relative = path.relative_to(directory).as_posix()
        manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def files_equal(first: Path, second: Path) -> bool:
    if not first.is_file() or not second.is_file():
        return False
    return hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()


def publish_transactionally(staging: Path, guidance_dir: Path) -> bool:
    guidance_dir.mkdir(parents=True, exist_ok=True)
    staging_images = staging / "images"
    live_images = guidance_dir / "images"

    page_changed = any(
        not files_equal(staging / note.output, guidance_dir / note.output)
        for note in NOTES
    )
    images_changed = directory_manifest(staging_images) != directory_manifest(live_images)

    if not page_changed and not images_changed:
        log("PUBLISH", "Generated guidance bundle is identical to the published bundle; no files were replaced.")
        return False

    transaction_id = uuid.uuid4().hex
    previous_pages: dict[Path, Path] = {}
    next_pages: list[Path] = []
    previous_images = guidance_dir / f".images.previous.{transaction_id}"
    next_images = guidance_dir / f".images.next.{transaction_id}"
    images_had_previous = live_images.exists()

    try:
        log("PUBLISH", "Preparing transactional replacement of all guidance pages and images.")

        for note in NOTES:
            staged_page = staging / note.output
            live_page = guidance_dir / note.output
            previous_page = guidance_dir / f".{note.output}.previous.{transaction_id}"
            next_page = guidance_dir / f".{note.output}.next.{transaction_id}"

            shutil.copy2(staged_page, next_page)
            next_pages.append(next_page)
            if live_page.exists():
                os.replace(live_page, previous_page)
                previous_pages[live_page] = previous_page

        if staging_images.is_dir():
            shutil.copytree(staging_images, next_images)
        else:
            next_images.mkdir()

        if live_images.exists():
            os.replace(live_images, previous_images)

        for note in NOTES:
            next_page = guidance_dir / f".{note.output}.next.{transaction_id}"
            os.replace(next_page, guidance_dir / note.output)

        os.replace(next_images, live_images)

        for previous in previous_pages.values():
            previous.unlink(missing_ok=True)
        if previous_images.exists():
            shutil.rmtree(previous_images)

        log("PUBLISH", "Published all four guidance pages and their images successfully.")
        return True

    except Exception as exc:
        log("ROLLBACK", f"Publication failed; restoring the previous bundle: {exc}.")

        for next_page in next_pages:
            next_page.unlink(missing_ok=True)
        if next_images.exists():
            shutil.rmtree(next_images, ignore_errors=True)

        for note in NOTES:
            live_page = guidance_dir / note.output
            previous_page = previous_pages.get(live_page)
            if previous_page and previous_page.exists():
                live_page.unlink(missing_ok=True)
                os.replace(previous_page, live_page)
            elif not previous_page:
                live_page.unlink(missing_ok=True)

        if previous_images.exists():
            if live_images.exists():
                shutil.rmtree(live_images, ignore_errors=True)
            os.replace(previous_images, live_images)
        elif not images_had_previous and live_images.exists():
            shutil.rmtree(live_images, ignore_errors=True)

        raise GuidanceUpdateError("PUBLISH", f"Transactional publication failed and rollback was attempted: {exc}.") from exc


def main() -> int:
    _, guidance_dir, template_path = repo_paths()

    try:
        pandoc = require_pandoc()

        if not template_path.is_file():
            raise GuidanceUpdateError(
                "TEMPLATE",
                f"Supervision template not found at {template_path}.",
            )

        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GuidanceUpdateError("TEMPLATE", f"Could not read {template_path}: {exc}.") from exc

        nav, footer, template_styles = extract_template_parts(template)
        nav = adapt_template_paths(nav)
        footer = adapt_template_paths(footer)

        with tempfile.TemporaryDirectory(prefix="guidance-update-") as temporary:
            temp_root = Path(temporary)
            archive = temp_root / "dropbox-guidance.zip"
            extracted = temp_root / "extracted"
            work_dir = temp_root / "work"
            staging = temp_root / "staging"
            staging_images = staging / "images"

            extracted.mkdir()
            work_dir.mkdir()
            staging.mkdir()
            staging_images.mkdir()

            download_dropbox_zip(archive)
            safe_extract_zip(archive, extracted)
            source_root = locate_source_root(extracted)

            source_images = source_root / "images"
            if source_images.exists() and not source_images.is_dir():
                raise GuidanceUpdateError(
                    "IMAGE_SOURCE",
                    f"Expected {source_images} to be a directory, but it is not.",
                )

            for note in NOTES:
                source_path = source_root / note.source
                tex_content = decode_tex(source_path, note)
                fragment, source_title = convert_tex_to_fragment(pandoc, source_path, work_dir, note)
                if source_title and source_title.casefold() != note.title.casefold():
                    log(
                        "TITLE_NOTICE",
                        f"The TeX title is {source_title!r}; the configured web title {note.title!r} will be used.",
                        note.slug,
                    )

                fragment, referenced_images = rewrite_and_collect_images(
                    fragment,
                    source_images if source_images.is_dir() else None,
                    staging_images,
                    note,
                )

                image_digests = {
                    relative: hashlib.sha256((staging_images / relative).read_bytes()).hexdigest()
                    for relative in sorted(referenced_images)
                }
                digest = source_digest(tex_content, note, image_digests)
                previous_digest, previous_date = existing_metadata(guidance_dir / note.output)

                if previous_digest == digest and previous_date:
                    updated = previous_date
                else:
                    updated = date.today().isoformat()

                page = render_page(
                    note,
                    fragment,
                    nav,
                    footer,
                    template_styles,
                    digest,
                    updated,
                )
                output_path = staging / note.output
                output_path.write_text(page, encoding="utf-8")
                validate_generated_page(output_path, note, referenced_images)

            changed = publish_transactionally(staging, guidance_dir)
            if changed:
                log("COMPLETE", "Guidance pages were updated successfully.")
            else:
                log("COMPLETE", "No guidance changes were detected.")

        return 0

    except GuidanceUpdateError as exc:
        print(f"ERROR {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(
            f"ERROR [UNEXPECTED] {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
