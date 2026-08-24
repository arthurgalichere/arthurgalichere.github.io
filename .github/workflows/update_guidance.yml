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
                        f"Archive member escapes the extraction directory: {member.filename!r}.",
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
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise GuidanceUpdateError("DEPENDENCY", f"Pandoc could not be executed: {exc}.") from exc

    first_line = result.stdout.splitlines()[0] if result.stdout else "unknown version"
    log("DEPENDENCY", f"Using {first_line}.")
    return pandoc


def read_template(template_path: Path) -> str:
    log("TEMPLATE", f"Reading shared layout from {template_path}.")
    if not template_path.is_file():
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"Template page not found: {template_path}. Expected teaching/supervision.html.",
        )

    try:
        content = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError("TEMPLATE", f"Could not read the supervision template: {exc}.") from exc

    required = ('class="index-nav"', 'class="foot', "</head>", "</body>")
    missing = [fragment for fragment in required if fragment not in content]
    if missing:
        raise GuidanceUpdateError(
            "TEMPLATE",
            "The supervision template is missing required layout fragments: " + ", ".join(missing) + ".",
        )
    return content


def extract_style(template: str) -> str:
    match = re.search(r"<style>(.*?)</style>", template, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise GuidanceUpdateError("TEMPLATE", "No inline <style> block was found in teaching/supervision.html.")
    return match.group(1).strip()


def extract_navigation(template: str) -> str:
    match = re.search(
        r"(<nav\b[^>]*class=[\"'][^\"']*\bindex-nav\b[^\"']*[\"'][^>]*>.*?</nav>)",
        template,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise GuidanceUpdateError("TEMPLATE", "The five-tab navigation block could not be located.")

    navigation = match.group(1)
    navigation = re.sub(r"\s+is-current\b", "", navigation)
    navigation = re.sub(r"\s+aria-current=[\"']page[\"']", "", navigation)

    replacements = {
        "../index.html": "../../index.html",
        "../cv.html": "../../cv.html",
        "../research.html": "../../research.html",
        "../teaching.html": "../../teaching.html",
        "../economics.html": "../../economics.html",
    }
    for source, target in replacements.items():
        navigation = navigation.replace(source, target)

    teaching_pattern = re.compile(
        r'(<a\b[^>]*href=["\']../../teaching\.html["\'][^>]*class=["\'])([^"\']*)(["\'][^>]*>)',
        flags=re.IGNORECASE,
    )

    def activate_teaching(match: re.Match[str]) -> str:
        classes = match.group(2).split()
        if "is-current" not in classes:
            classes.append("is-current")
        opening = f"{match.group(1)}{' '.join(classes)}{match.group(3)}"
        if "aria-current=" not in opening:
            opening = opening[:-1] + ' aria-current="page">'
        return opening

    navigation, count = teaching_pattern.subn(activate_teaching, navigation, count=1)
    if count != 1:
        raise GuidanceUpdateError(
            "TEMPLATE",
            "The Teaching navigation item could not be located and activated after path rebasing.",
        )
    return navigation


def extract_footer(template: str) -> str:
    match = re.search(
        r"(<footer\b[^>]*class=[\"'][^\"']*\bfoot\b[^\"']*[\"'][^>]*>.*?</footer>)",
        template,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise GuidanceUpdateError("TEMPLATE", "The footer block could not be located.")
    return match.group(1)


def convert_note(pandoc: str, source_root: Path, note: Note, work_dir: Path) -> tuple[str, str | None]:
    source_path = source_root / note.source
    tex = decode_tex(source_path, note)
    body_tex, tex_title = strip_document_wrapper(tex)

    if not body_tex:
        raise GuidanceUpdateError("SOURCE_VALIDATE", "No document body remained after preprocessing.", note.slug)

    prepared_source = work_dir / f"{note.slug}.tex"
    prepared_source.write_text(body_tex, encoding="utf-8", newline="\n")

    command = [
        pandoc,
        str(prepared_source),
        "--from=latex",
        "--to=html5",
        "--mathjax",
        "--wrap=none",
        "--shift-heading-level-by=1",
        f"--resource-path={source_root}{os.pathsep}{source_root / 'images'}",
    ]

    log("CONVERT", f"Converting {note.source} with Pandoc.", note.slug)
    try:
        result = subprocess.run(
            command,
            cwd=source_root,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise GuidanceUpdateError("CONVERT", "Pandoc exceeded the 180-second time limit.", note.slug) from exc
    except OSError as exc:
        raise GuidanceUpdateError("CONVERT", f"Pandoc could not be started: {exc}.", note.slug) from exc

    if result.returncode != 0:
        diagnostic = result.stderr.strip() or result.stdout.strip() or "No diagnostic output was returned."
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc exited with status {result.returncode}. Diagnostic: {diagnostic}",
            note.slug,
        )

    if result.stderr.strip():
        log("CONVERT_WARNING", result.stderr.strip(), note.slug)

    fragment = result.stdout.strip()
    visible = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()
    if len(visible) < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "CONVERT_VALIDATE",
            f"Converted content contains only {len(visible)} visible characters.",
            note.slug,
        )

    unresolved = re.search(
        r"\\(?:begin|end|section|subsection|subsubsection|includegraphics|item|textbf|emph)\b",
        fragment,
    )
    if unresolved:
        raise GuidanceUpdateError(
            "CONVERT_VALIDATE",
            f"Unresolved LaTeX command remains in generated HTML: {unresolved.group(0)!r}.",
            note.slug,
        )

    log("CONVERT", f"Conversion produced {len(visible):,} visible characters.", note.slug)
    return fragment, normalize_title(tex_title)


def normalize_image_sources(fragment: str, note: Note) -> str:
    def replace_source(match: re.Match[str]) -> str:
        prefix, quote, raw_source = match.groups()
        decoded = urllib.parse.unquote(raw_source).replace("\\", "/")
        parsed = urllib.parse.urlsplit(decoded)

        if parsed.scheme or decoded.startswith(("/", "#", "data:")):
            return match.group(0)

        while decoded.startswith("./"):
            decoded = decoded[2:]

        if "/images/" in decoded and not decoded.startswith("images/"):
            decoded = "images/" + decoded.split("/images/", 1)[1]

        if not decoded.startswith("images/"):
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                f"Converted HTML references a local image outside images/: {raw_source!r}. "
                "Use a path such as images/example.png in the TeX source.",
                note.slug,
            )

        return f"{prefix}{quote}{html.escape(decoded, quote=True)}{quote}"

    return re.sub(
        r'(<img\b[^>]*\bsrc\s*=\s*)(["\'])(.*?)\2',
        replace_source,
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )


def copy_web_images(source_root: Path, destination: Path) -> int:
    source_images = source_root / "images"
    destination.mkdir(parents=True, exist_ok=True)

    if not source_images.is_dir():
        log("IMAGES", "No top-level images directory was found; continuing because images are optional.")
        return 0

    copied = 0
    for source in source_images.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_images)
        if ignored_path(relative) or any(part.startswith(".") for part in relative.parts):
            continue
        if source.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            log("IMAGES", f"Ignoring unsupported image file: images/{relative.as_posix()}.")
            continue

        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            raise GuidanceUpdateError(
                "IMAGES",
                f"Could not copy images/{relative.as_posix()}: {exc}.",
            ) from exc
        copied += 1

    log("IMAGES", f"Copied {copied} web-compatible image file(s).")
    return copied


def validate_image_references(fragment: str, staged_images: Path, note: Note) -> list[Path]:
    parser = ImageSourceParser()
    parser.feed(fragment)
    referenced: list[Path] = []

    for source in parser.sources:
        parsed = urllib.parse.urlsplit(source)
        if parsed.scheme or source.startswith(("data:", "/", "#")):
            continue

        decoded = urllib.parse.unquote(parsed.path)
        path = PurePosixPath(decoded)
        if path.is_absolute() or ".." in path.parts:
            raise GuidanceUpdateError("IMAGE_REFERENCE", f"Unsafe image path: {source!r}.", note.slug)
        if not path.parts or path.parts[0] != "images":
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                f"Local image path must begin with images/: {source!r}.",
                note.slug,
            )

        relative = Path(*path.parts[1:])
        target = staged_images / relative
        if not target.is_file():
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                f"Referenced image is missing: {source!r}. Expected {target}.",
                note.slug,
            )
        if target.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                f"Referenced image is not in a supported web format: {source!r}.",
                note.slug,
            )
        referenced.append(relative)

    log("IMAGE_REFERENCE", f"Validated {len(referenced)} local image reference(s).", note.slug)
    return referenced


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_digest(note: Note, source_root: Path, referenced_images: list[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(f"template-version:{TEMPLATE_VERSION}\n".encode())
    digest.update(f"slug:{note.slug}\n".encode())
    digest.update((source_root / note.source).read_bytes())

    for relative in sorted(set(referenced_images), key=lambda path: path.as_posix().casefold()):
        image_path = source_root / "images" / relative
        digest.update(f"\nimage:{relative.as_posix()}\n".encode())
        digest.update(image_path.read_bytes())

    return digest.hexdigest()


def existing_metadata(page_path: Path) -> tuple[str | None, str | None]:
    if not page_path.is_file():
        return None, None
    try:
        content = page_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, None

    digest_match = re.search(
        r'<meta\s+name=["\']guidance-source-digest["\']\s+content=["\']([0-9a-f]{64})["\']',
        content,
        flags=re.IGNORECASE,
    )
    date_match = re.search(
        r'<meta\s+name=["\']guidance-updated["\']\s+content=["\'](\d{4}-\d{2}-\d{2})["\']',
        content,
        flags=re.IGNORECASE,
    )
    return (
        digest_match.group(1).lower() if digest_match else None,
        date_match.group(1) if date_match else None,
    )


def navigation_html(note: Note) -> str:
    items = [
        ("getting-started", "getting-started.html", "fa-play", "Getting Started"),
        ("writing-dissertation", "writing-dissertation.html", "fa-pen", "Writing"),
        ("literature-review", "literature-review.html", "fa-book-open", "Literature Review"),
        ("dissertation-structure", "dissertation-structure.html", "fa-sitemap", "Structure"),
    ]
    links = []
    for slug, href, icon, label in items:
        current = ' class="guide-step is-current" aria-current="page"' if slug == note.slug else ' class="guide-step"'
        links.append(
            f'<a href="{href}"{current}><i class="fas {icon}" aria-hidden="true"></i><span>{html.escape(label)}</span></a>'
        )
    return '<nav class="guidance-sequence" aria-label="Dissertation guidance notes">' + "".join(links) + "</nav>"


def previous_next_html(note: Note) -> str:
    index = NOTES.index(note)
    links: list[str] = []
    if index > 0:
        previous = NOTES[index - 1]
        links.append(
            '<a class="guidance-route guidance-route-previous" '
            f'href="{previous.output}"><i class="fas fa-arrow-left" aria-hidden="true"></i>'
            f'<span><small>Previous note</small>{html.escape(previous.title)}</span></a>'
        )
    if index < len(NOTES) - 1:
        following = NOTES[index + 1]
        links.append(
            '<a class="guidance-route guidance-route-next" '
            f'href="{following.output}"><span><small>Next note</small>{html.escape(following.title)}</span>'
            '<i class="fas fa-arrow-right" aria-hidden="true"></i></a>'
        )
    class_name = "guidance-routes has-single-route" if len(links) == 1 else "guidance-routes"
    return f'<nav class="{class_name}" aria-label="Previous and next guidance notes">' + "".join(links) + "</nav>"


GUIDANCE_CSS = r"""
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
      transition: color 0.16s ease, background-color 0.16s ease,
                  border-color 0.16s ease, transform 0.16s ease;
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

    .guidance-sequence {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 2rem;
      overflow: hidden;
      border: 1px solid var(--line-strong);
      border-radius: 5px;
    }

    .guide-step {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.45rem;
      min-height: 3.2rem;
      padding: 0.7rem;
      color: var(--muted);
      background: var(--paper-soft);
      border-left: 1px solid var(--line);
      font-size: 0.78rem;
      font-weight: 600;
      line-height: 1.35;
      text-align: center;
      text-decoration: none;
    }

    .guide-step:first-child { border-left: none; }
    .guide-step:hover { color: var(--accent-strong); background: var(--accent-soft); }
    .guide-step.is-current { color: #fff; background: var(--accent); }

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

    .guidance-content blockquote {
      padding: 1rem 1.2rem;
      color: var(--ink-soft);
      background: var(--accent-soft);
      border-left: 4px solid var(--accent);
      border-radius: 3px;
    }

    .guidance-content img {
      max-width: 100%;
      height: auto;
      margin: 1.5rem auto;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
    }

    .guidance-content figure { margin: 1.5rem 0; }
    .guidance-content figure img { margin: 0 auto; }

    .guidance-content figcaption {
      margin-top: 0.55rem;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.5;
      text-align: center;
    }

    .guidance-content table {
      width: 100%;
      margin: 1.4rem 0;
      border-collapse: collapse;
      font-size: 0.9rem;
    }

    .guidance-content th,
    .guidance-content td {
      padding: 0.7rem 0.8rem;
      text-align: left;
      vertical-align: top;
      border: 1px solid var(--line-strong);
    }

    .guidance-content th {
      color: var(--accent-strong);
      background: var(--accent-soft);
      font-weight: 700;
    }

    .guidance-content .math.display {
      max-width: 100%;
      margin: 1.4rem 0;
      overflow-x: auto;
      overflow-y: hidden;
      text-align: center;
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

    .guidance-content pre code { padding: 0; border: none; }

    .guidance-routes {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      margin-top: 3rem;
    }

    .guidance-routes.has-single-route { grid-template-columns: minmax(0, 1fr); }

    .guidance-route {
      display: flex;
      align-items: center;
      gap: 0.8rem;
      padding: 1rem 1.1rem;
      color: var(--accent-strong);
      background: var(--paper-soft);
      border: 1px solid var(--line-strong);
      border-radius: 5px;
      line-height: 1.35;
      text-decoration: none;
      transition: background-color 0.16s ease, border-color 0.16s ease, transform 0.16s ease;
    }

    .guidance-route:hover {
      background: var(--accent-soft);
      border-color: rgba(59, 90, 117, 0.4);
      transform: translateY(-1px);
    }

    .guidance-route-next { justify-content: flex-end; text-align: right; }
    .guidance-routes.has-single-route .guidance-route-previous { max-width: 32rem; }
    .guidance-routes.has-single-route .guidance-route-next { width: min(100%, 32rem); margin-left: auto; }

    .guidance-route small {
      display: block;
      margin-bottom: 0.18rem;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.66rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .guidance-update {
      margin-top: 2rem;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.78rem;
      letter-spacing: 0.03em;
      text-align: center;
    }

    @media (max-width: 768px) {
      .guidance-body { padding: 2rem 1.5rem; }
      .guidance-toolbar { align-items: stretch; }
      .guidance-sequence { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .guide-step:nth-child(3) { border-left: none; border-top: 1px solid var(--line); }
      .guide-step:nth-child(4) { border-top: 1px solid var(--line); }
    }

    @media (max-width: 680px) {
      .guidance-toolbar { flex-direction: column; }
      .back-link, .download-link { justify-content: center; }
      .guidance-title { font-size: 2.1rem; }
      .guidance-routes { grid-template-columns: 1fr; }
      .guidance-route-next { justify-content: space-between; }
    }
"""


def render_page(
    note: Note,
    fragment: str,
    digest: str,
    updated_date: str,
    shared_css: str,
    navigation: str,
    footer: str,
) -> str:
    display_date = date.fromisoformat(updated_date).strftime("%d/%m/%Y")
    title = html.escape(note.title)
    description = html.escape(note.description, quote=True)
    pdf_url = html.escape(note.pdf_url, quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arthur Galichère — {title}</title>
  <meta name="description" content="{description}" />
  <meta name="guidance-source-digest" content="{digest}" />
  <meta name="guidance-updated" content="{updated_date}" />

  <link rel="icon" type="image/png" href="../../website/images/favicon_transparant.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bitter:ital,wght@0,400;0,600;0,700;1,400&family=Montserrat:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>

  <style>
{shared_css}
{GUIDANCE_CSS}
  </style>
</head>
<body>
  <main class="page">
    <article class="card">
      {navigation}

      <section class="guidance-body">
        <div class="guidance-toolbar">
          <a href="../dissertation.html" class="back-link">
            <i class="fas fa-arrow-left" aria-hidden="true"></i>
            Back to Dissertation Supervision and Guidance
          </a>
          <a href="{pdf_url}" class="download-link">
            <i class="fas fa-download" aria-hidden="true"></i>
            Download PDF
          </a>
        </div>

        <h1 class="guidance-title">{title}</h1>
        {navigation_html(note)}

        <div class="guidance-content">
{fragment}
        </div>

        {previous_next_html(note)}
        <p class="guidance-update">Information updated on {display_date}</p>
      </section>

      {footer}
    </article>
  </main>
</body>
</html>
"""


def validate_page(page: str, note: Note, digest: str) -> None:
    checks = {
        "document type": "<!DOCTYPE html>" in page,
        "page title": f'<h1 class="guidance-title">{html.escape(note.title)}</h1>' in page,
        "source digest": digest in page,
        "five-tab navigation": len(re.findall(r'class="[^"]*\bindex-card\b', page)) == 5,
        "Teaching active tab": '../../teaching.html' in page and 'aria-current="page"' in page,
        "back button": 'href="../dissertation.html"' in page,
        "PDF link": html.escape(note.pdf_url, quote=True) in page,
        "guidance content": '<div class="guidance-content">' in page,
        "footer": 'class="foot' in page,
        "update date": "Information updated on" in page,
        "digest metadata": 'name="guidance-source-digest"' in page,
        "date metadata": 'name="guidance-updated"' in page,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            f"Generated page failed checks: {', '.join(failed)}.",
            note.slug,
        )


def files_equal(first: Path, second: Path) -> bool:
    if not first.is_file() or not second.is_file():
        return False
    return first.stat().st_size == second.stat().st_size and hash_file(first) == hash_file(second)


def directories_equal(first: Path, second: Path) -> bool:
    if not first.is_dir() or not second.is_dir():
        return first.is_dir() == second.is_dir()

    first_files = sorted(path.relative_to(first) for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second) for path in second.rglob("*") if path.is_file())
    if first_files != second_files:
        return False
    return all(files_equal(first / relative, second / relative) for relative in first_files)


def publish_transactionally(staging: Path, guidance_dir: Path) -> bool:
    guidance_dir.mkdir(parents=True, exist_ok=True)
    staged_images = staging / "images"
    live_images = guidance_dir / "images"

    pages_changed = any(not files_equal(staging / note.output, guidance_dir / note.output) for note in NOTES)
    images_changed = not directories_equal(staged_images, live_images)

    if not pages_changed and not images_changed:
        log("PUBLISH", "Generated guidance pages and images are unchanged; nothing to publish.")
        return False

    transaction_id = uuid.uuid4().hex
    next_paths: list[Path] = []
    previous_images = guidance_dir / f".images.previous.{transaction_id}"
    next_images = guidance_dir / f".images.next.{transaction_id}"

    with tempfile.TemporaryDirectory(prefix="guidance-publish-backup-") as backup_name:
        backup = Path(backup_name)
        backup_pages = backup / "pages"
        backup_pages.mkdir()
        backup_images = backup / "images"

        for note in NOTES:
            live_page = guidance_dir / note.output
            if live_page.is_file():
                shutil.copy2(live_page, backup_pages / note.output)

        if live_images.is_dir():
            shutil.copytree(live_images, backup_images)

        try:
            shutil.copytree(staged_images, next_images)
            for note in NOTES:
                next_page = guidance_dir / f".{note.output}.next.{transaction_id}"
                shutil.copy2(staging / note.output, next_page)
                next_paths.append(next_page)

            if live_images.exists():
                os.replace(live_images, previous_images)
            os.replace(next_images, live_images)

            for note, next_page in zip(NOTES, next_paths):
                os.replace(next_page, guidance_dir / note.output)

            if previous_images.exists():
                shutil.rmtree(previous_images)

        except Exception as exc:
            log("ROLLBACK", f"Publication failed; restoring the previous live bundle: {exc}.")
            rollback_errors: list[str] = []

            for path in next_paths:
                path.unlink(missing_ok=True)
            if next_images.exists():
                shutil.rmtree(next_images, ignore_errors=True)

            try:
                if live_images.exists():
                    shutil.rmtree(live_images)
                if previous_images.exists():
                    os.replace(previous_images, live_images)
                elif backup_images.is_dir():
                    shutil.copytree(backup_images, live_images)
            except Exception as rollback_exc:
                rollback_errors.append(f"images: {rollback_exc}")

            for note in NOTES:
                backup_page = backup_pages / note.output
                live_page = guidance_dir / note.output
                try:
                    if backup_page.is_file():
                        shutil.copy2(backup_page, live_page)
                    else:
                        live_page.unlink(missing_ok=True)
                except Exception as rollback_exc:
                    rollback_errors.append(f"{note.output}: {rollback_exc}")

            if rollback_errors:
                raise GuidanceUpdateError(
                    "ROLLBACK",
                    "Publication failed and rollback was incomplete: " + "; ".join(rollback_errors),
                ) from exc

            raise GuidanceUpdateError(
                "PUBLISH",
                f"Publication failed, but the previous live bundle was restored successfully: {exc}.",
            ) from exc

    log("PUBLISH", "Published all four guidance pages and the images directory successfully.")
    return True


def main() -> int:
    _, guidance_dir, template_path = repo_paths()
    today = date.today().isoformat()

    try:
        pandoc = require_pandoc()
        template = read_template(template_path)
        shared_css = extract_style(template)
        navigation = extract_navigation(template)
        footer = extract_footer(template)

        with tempfile.TemporaryDirectory(prefix="guidance-update-") as temporary_name:
            temporary = Path(temporary_name)
            archive = temporary / "dropbox-guidance.zip"
            extracted = temporary / "extracted"
            staging = temporary / "staging"
            staged_images = staging / "images"
            conversion_work = temporary / "conversion"
            extracted.mkdir()
            staging.mkdir()
            conversion_work.mkdir()

            download_dropbox_zip(archive)
            safe_extract_zip(archive, extracted)
            source_root = locate_source_root(extracted)
            copy_web_images(source_root, staged_images)

            for note in NOTES:
                fragment, source_title = convert_note(pandoc, source_root, note, conversion_work)
                if source_title and source_title.casefold() != note.title.casefold():
                    log(
                        "SOURCE_TITLE",
                        f"TeX title {source_title!r} differs from configured page title {note.title!r}; using configured title.",
                        note.slug,
                    )
                fragment = normalize_image_sources(fragment, note)
                referenced_images = validate_image_references(fragment, staged_images, note)

                digest = source_digest(note, source_root, referenced_images)
                previous_digest, previous_date = existing_metadata(guidance_dir / note.output)
                updated_date = previous_date if previous_digest == digest and previous_date else today

                page = render_page(
                    note=note,
                    fragment=fragment,
                    digest=digest,
                    updated_date=updated_date,
                    shared_css=shared_css,
                    navigation=navigation,
                    footer=footer,
                )
                validate_page(page, note, digest)
                (staging / note.output).write_text(page, encoding="utf-8", newline="\n")
                log("STAGE", f"Staged {note.output}.", note.slug)

            publish_transactionally(staging, guidance_dir)

        log("COMPLETE", "All four guidance pages were downloaded, converted, validated, and published safely.")
        return 0

    except GuidanceUpdateError as exc:
        print(f"ERROR {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"ERROR [UNEXPECTED] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
