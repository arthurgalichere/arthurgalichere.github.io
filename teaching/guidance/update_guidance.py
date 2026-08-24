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
    validated_members: list[zipfile.ZipInfo] = []
    skipped_root_entries = 0

    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            if not members:
                raise GuidanceUpdateError("ZIP_EXTRACT", "The Dropbox ZIP archive is empty.")

            for member in members:
                raw_name = member.filename
                normalized_name = raw_name.replace("\\", "/")

                if "\x00" in normalized_name:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Archive path contains a null byte: {raw_name!r}.",
                    )

                # Dropbox folder ZIPs can contain a harmless root-directory
                # placeholder named "/" or "./". It has no content to extract.
                if normalized_name.strip("/") in {"", "."}:
                    if member.is_dir():
                        skipped_root_entries += 1
                        continue
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Unsafe root-level file entry rejected: {raw_name!r}.",
                    )

                path = PurePosixPath(normalized_name)
                raw_parts = [part for part in normalized_name.split("/") if part]

                if (
                    path.is_absolute()
                    or ".." in raw_parts
                    or re.match(r"^[A-Za-z]:", normalized_name)
                ):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Unsafe archive path rejected: {raw_name!r}.",
                    )

                unix_mode = member.external_attr >> 16
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Symbolic-link archive entry rejected: {raw_name!r}.",
                    )

                target = destination.joinpath(*path.parts).resolve()
                try:
                    target.relative_to(destination_resolved)
                except ValueError as exc:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Archive path escapes the extraction directory: {raw_name!r}.",
                    ) from exc

                validated_members.append(member)

            for member in validated_members:
                normalized_name = member.filename.replace("\\", "/")
                path = PurePosixPath(normalized_name)
                target = destination.joinpath(*path.parts)

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise GuidanceUpdateError("ZIP_EXTRACT", f"The ZIP archive is corrupt: {exc}.") from exc
    except OSError as exc:
        raise GuidanceUpdateError("ZIP_EXTRACT", f"Could not extract the ZIP archive: {exc}.") from exc

    message = f"Extracted {len(validated_members)} validated archive entries safely."
    if skipped_root_entries:
        message += f" Skipped {skipped_root_entries} harmless Dropbox root entry."
    log("ZIP_EXTRACT", message)


def ignored_path(relative_path: Path) -> bool:
    return any(part.casefold() in IGNORED_DIRECTORY_NAMES for part in relative_path.parts)


def locate_source_root(extracted_root: Path) -> Path:
    log("SOURCE_DISCOVERY", "Locating the four allowlisted TeX source files.")
    expected = {note.source for note in NOTES}
    candidates: list[Path] = []

    for directory in [extracted_root, *sorted(path for path in extracted_root.rglob("*") if path.is_dir())]:
        try:
            relative_directory = directory.relative_to(extracted_root)
        except ValueError:
            continue

        if ignored_path(relative_directory):
            continue

        available = {
            path.name
            for path in directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".tex"
        }
        if expected.issubset(available):
            candidates.append(directory)

    if not candidates:
        discovered = sorted(
            path.relative_to(extracted_root).as_posix()
            for path in extracted_root.rglob("*.tex")
            if not ignored_path(path.relative_to(extracted_root))
        )
        details = ", ".join(discovered) if discovered else "no TeX files were found"
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "Could not find a directory containing all four required TeX files. "
            f"Discovered: {details}.",
        )

    if len(candidates) > 1:
        choices = ", ".join(path.relative_to(extracted_root).as_posix() or "." for path in candidates)
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            f"More than one source directory contains all four required notes: {choices}.",
        )

    source_root = candidates[0]
    log("SOURCE_DISCOVERY", f"Using source directory: {source_root}.")
    return source_root


def require_pandoc() -> str:
    executable = shutil.which("pandoc")
    if not executable:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            "Pandoc is not installed or is not available on PATH.",
        )

    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuidanceUpdateError("DEPENDENCY", f"Pandoc could not be executed: {exc}.") from exc

    if result.returncode != 0:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            f"Pandoc version check failed: {result.stderr.strip() or 'unknown error'}.",
        )

    version = result.stdout.splitlines()[0] if result.stdout else "pandoc"
    log("DEPENDENCY", f"Using {version}.")
    return executable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def referenced_local_images(tex_source: str) -> set[str]:
    references: set[str] = set()
    pattern = re.compile(
        r"\\includegraphics(?:\s*\[[^]]*\])?\s*\{([^}]+)\}",
        flags=re.IGNORECASE,
    )

    for match in pattern.finditer(tex_source):
        value = match.group(1).strip().replace("\\", "/")
        if not value:
            continue
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme or parsed.netloc:
            continue
        while value.startswith("./"):
            value = value[2:]
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise GuidanceUpdateError(
                "IMAGE_SECURITY",
                f"Unsafe image path appears in TeX source: {value!r}.",
            )
        if path.parts and path.parts[0].casefold() == "images":
            references.add(path.as_posix())
    return references


def resolve_image_for_digest(reference: str, source_root: Path) -> Path | None:
    reference_path = PurePosixPath(reference)
    exact = source_root.joinpath(*reference_path.parts)
    if exact.is_file():
        return exact

    parent = exact.parent
    stem = exact.stem
    suffix = exact.suffix
    if suffix:
        if not parent.is_dir():
            return None
        matches = [path for path in parent.iterdir() if path.is_file() and path.name.casefold() == exact.name.casefold()]
        return matches[0] if len(matches) == 1 else None

    if not parent.is_dir():
        return None
    matches = [
        path
        for path in parent.iterdir()
        if path.is_file()
        and path.stem.casefold() == stem.casefold()
        and path.suffix.casefold() in WEB_IMAGE_EXTENSIONS
    ]
    return matches[0] if len(matches) == 1 else None


def source_digest(source_path: Path, source_root: Path) -> str:
    digest = hashlib.sha256()
    source_bytes = source_path.read_bytes()
    digest.update(f"template-version:{TEMPLATE_VERSION}\n".encode("utf-8"))
    digest.update(source_bytes)

    try:
        tex_source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuidanceUpdateError(
            "SOURCE_ENCODING",
            f"The TeX source is not valid UTF-8: {exc}.",
            source_path.name,
        ) from exc

    for reference in sorted(referenced_local_images(tex_source)):
        image_path = resolve_image_for_digest(reference, source_root)
        digest.update(f"\nimage:{reference}\n".encode("utf-8"))
        if image_path and image_path.is_file():
            digest.update(image_path.read_bytes())
        else:
            digest.update(b"<missing>")

    return digest.hexdigest()


def current_page_metadata(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None

    try:
        content = path.read_text(encoding="utf-8")
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
        digest_match.group(1) if digest_match else None,
        date_match.group(1) if date_match else None,
    )


def choose_update_date(existing_output: Path, new_digest: str) -> str:
    previous_digest, previous_date = current_page_metadata(existing_output)
    if previous_digest == new_digest and previous_date:
        try:
            date.fromisoformat(previous_date)
            return previous_date
        except ValueError:
            pass
    return date.today().isoformat()


def convert_tex_to_html(pandoc: str, source_path: Path, source_root: Path, destination: Path, note: Note) -> str:
    log("CONVERT", f"Converting {source_path.name} with Pandoc.", note.slug)

    command = [
        pandoc,
        str(source_path),
        "--from=latex",
        "--to=html5",
        "--mathjax",
        "--wrap=none",
        f"--resource-path={source_root}",
        "--output",
        str(destination),
    ]

    try:
        result = subprocess.run(
            command,
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            "Pandoc exceeded the 120-second conversion timeout.",
            note.slug,
        ) from exc
    except OSError as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc could not be started: {exc}.",
            note.slug,
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "No error details were returned."
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc exited with status {result.returncode}: {stderr}",
            note.slug,
        )

    try:
        converted = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError(
            "CONVERT_OUTPUT",
            f"Pandoc output could not be read as UTF-8: {exc}.",
            note.slug,
        ) from exc

    validate_converted_fragment(converted, note)
    return converted


def visible_text_length(fragment: str) -> int:
    without_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    text = html.unescape(without_tags)
    return len(re.sub(r"\s+", " ", text).strip())


def validate_converted_fragment(fragment: str, note: Note) -> None:
    if not fragment.strip():
        raise GuidanceUpdateError("CONTENT_VALIDATE", "Pandoc produced an empty HTML fragment.", note.slug)

    text_length = visible_text_length(fragment)
    if text_length < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "CONTENT_VALIDATE",
            f"Converted content is unexpectedly short ({text_length} visible characters).",
            note.slug,
        )

    suspicious_patterns = (
        r"\\begin\{document\}",
        r"\\end\{document\}",
        r"\\documentclass(?:\[[^]]*\])?\{",
    )
    for pattern in suspicious_patterns:
        if re.search(pattern, fragment):
            raise GuidanceUpdateError(
                "CONTENT_VALIDATE",
                f"Converted HTML still contains unresolved LaTeX matching {pattern!r}.",
                note.slug,
            )


def normalize_image_reference(source: str) -> str | None:
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme or parsed.netloc or source.startswith("data:"):
        return None

    path = urllib.parse.unquote(parsed.path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]

    if not path:
        return None

    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise GuidanceUpdateError("IMAGE_SECURITY", f"Unsafe image reference found in converted HTML: {source!r}.")

    if pure.parts and pure.parts[0].casefold() == "images":
        return PurePosixPath("images", *pure.parts[1:]).as_posix()

    return None


def collect_image_references(fragment: str, note: Note) -> set[str]:
    parser = ImageSourceParser()
    try:
        parser.feed(fragment)
    except Exception as exc:
        raise GuidanceUpdateError(
            "IMAGE_PARSE",
            f"Could not inspect generated image references: {exc}.",
            note.slug,
        ) from exc

    references: set[str] = set()
    for source in parser.sources:
        try:
            normalized = normalize_image_reference(source)
        except GuidanceUpdateError as exc:
            raise GuidanceUpdateError(exc.stage, str(exc).split("] ", 1)[-1], note.slug) from exc
        if normalized:
            references.add(normalized)
    return references


def copy_web_images(source_root: Path, staging_root: Path) -> set[str]:
    source_images = source_root / "images"
    destination_images = staging_root / "images"
    copied: set[str] = set()

    if not source_images.is_dir():
        log("IMAGES", "No top-level images directory was found; continuing without local images.")
        return copied

    log("IMAGES", f"Copying web-compatible images from {source_images}.")

    for source in sorted(path for path in source_images.rglob("*") if path.is_file()):
        relative_inside_images = source.relative_to(source_images)
        relative_source = source.relative_to(source_root)

        if ignored_path(relative_source):
            continue

        if source.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            log("IMAGES", f"Ignoring unsupported image file: {relative_source.as_posix()}.")
            continue

        destination = destination_images / relative_inside_images
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise GuidanceUpdateError(
                "IMAGE_COPY",
                f"Could not copy {relative_source.as_posix()}: {exc}.",
            ) from exc

        copied.add(PurePosixPath("images", *relative_inside_images.parts).as_posix())

    log("IMAGES", f"Copied {len(copied)} web-compatible image file(s).")
    return copied


def validate_referenced_images(
    references_by_note: dict[str, set[str]],
    copied_images: set[str],
    staging_root: Path,
) -> None:
    """Validate image references and repair harmless filename-case mismatches.

    Dropbox, Windows, and macOS commonly treat filenames case-insensitively,
    while GitHub Pages serves files from a case-sensitive filesystem. Pandoc
    preserves the spelling used in the TeX source, so a reference ending in
    ``.PNG`` can otherwise fail when the actual file is named ``.png``.
    """
    casefolded_images: dict[str, str] = {}
    ambiguous_images: set[str] = set()

    for copied in copied_images:
        key = copied.casefold()
        previous = casefolded_images.get(key)
        if previous is not None and previous != copied:
            ambiguous_images.add(key)
        else:
            casefolded_images[key] = copied

    if ambiguous_images:
        collisions = []
        for key in sorted(ambiguous_images):
            variants = sorted(path for path in copied_images if path.casefold() == key)
            collisions.append(" / ".join(variants))
        raise GuidanceUpdateError(
            "IMAGE_CASE_COLLISION",
            "The images folder contains filenames that differ only by letter case: "
            + "; ".join(collisions)
            + ". Rename the files so each case-insensitive path is unique.",
        )

    for note_slug, references in references_by_note.items():
        missing: list[str] = []

        for reference in sorted(references):
            if reference in copied_images:
                continue

            actual = casefolded_images.get(reference.casefold())
            if actual is None:
                missing.append(reference)
                continue

            source_path = staging_root / Path(*PurePosixPath(actual).parts)
            alias_path = staging_root / Path(*PurePosixPath(reference).parts)
            alias_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.copy2(source_path, alias_path)
            except OSError as exc:
                raise GuidanceUpdateError(
                    "IMAGE_CASE_ALIAS",
                    f"Could not create the case-matching image path {reference!r} "
                    f"from {actual!r}: {exc}.",
                    note_slug,
                ) from exc

            copied_images.add(reference)
            log(
                "IMAGE_REFERENCE",
                f"Resolved filename-case mismatch: {reference} -> {actual}.",
                note_slug,
            )

        if missing:
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                "Converted content references missing or unsupported image(s): " + ", ".join(missing),
                note_slug,
            )


def extract_style_block(template: str) -> str:
    match = re.search(r"<style>(.*?)</style>", template, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise GuidanceUpdateError("TEMPLATE", "The supervision template contains no <style> block.")
    return match.group(1).strip()


def guidance_css(template_css: str) -> str:
    shared_prefix_match = re.search(
        r"^(.*?)(?=\n\s*\.supervision-body\s*\{)",
        template_css,
        flags=re.DOTALL,
    )
    if not shared_prefix_match:
        raise GuidanceUpdateError(
            "TEMPLATE",
            "Could not isolate the shared layout styles before .supervision-body.",
        )

    shared = shared_prefix_match.group(1).rstrip()
    return shared + r'''

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
      display: block;
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

    .guidance-update {
      margin-top: 3rem;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.78rem;
      letter-spacing: 0.03em;
      text-align: center;
    }

    .guidance-pagination {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      margin-top: 2.5rem;
    }

    .guidance-pagination.is-single { grid-template-columns: minmax(0, 1fr); }

    .guidance-page-link {
      display: flex;
      align-items: center;
      gap: 0.8rem;
      min-width: 0;
      padding: 1rem 1.1rem;
      color: var(--accent-strong);
      background: var(--paper-soft);
      border: 1px solid var(--line-strong);
      border-radius: 5px;
      text-decoration: none;
      transition: color 0.16s ease, background-color 0.16s ease,
                  border-color 0.16s ease, transform 0.16s ease;
    }

    .guidance-page-link.is-next { justify-content: flex-end; text-align: right; }

    .guidance-page-link:hover {
      color: #fff;
      background: var(--accent);
      border-color: var(--accent);
      transform: translateY(-1px);
    }

    .guidance-page-link i { flex: 0 0 auto; }

    .guidance-page-copy { min-width: 0; }

    .guidance-page-direction {
      display: block;
      margin-bottom: 0.15rem;
      font-family: var(--mono);
      font-size: 0.68rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      opacity: 0.72;
    }

    .guidance-page-title {
      display: block;
      font-family: var(--display);
      font-size: 0.96rem;
      font-weight: 700;
      line-height: 1.35;
    }

    .foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding: 0.9rem 1.5rem;
      background: var(--panel-deep);
      border-top: 1px solid var(--line);
    }

    .foot-loc {
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .socials {
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    .socials a {
      width: 2rem;
      height: 2rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--ink-soft);
      background: var(--sheet);
      border: 1px solid var(--line-strong);
      border-radius: 4px;
      font-size: 0.85rem;
      text-decoration: none;
      transition: color 0.16s ease, background-color 0.16s ease,
                  border-color 0.16s ease, transform 0.16s ease;
    }

    .socials a:hover {
      color: #fff;
      background: var(--accent);
      border-color: var(--accent);
      transform: translateY(-1px);
    }

    @media (prefers-reduced-motion: reduce) {
      .index-card,
      .back-link,
      .download-link,
      .guidance-page-link,
      .socials a { transition: none; }
    }

    @media (max-width: 768px) {
      .index-nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .guidance-body { padding: 2rem 1.5rem; }
    }

    @media (max-width: 680px) {
      .index-nav { grid-template-columns: 1fr; }
      .index-card { border-top: 1px solid var(--line); border-left: none; }
      .index-card:first-child { border-top: none; }
      .guidance-toolbar { align-items: stretch; flex-direction: column; }
      .back-link, .download-link { justify-content: center; }
      .guidance-title { font-size: 2.15rem; }
      .guidance-pagination { grid-template-columns: 1fr; }
      .foot { flex-direction: column; text-align: center; }
    }
'''.rstrip()


def navigation_html() -> str:
    return '''      <nav class="index-nav" aria-label="Academic Directory">
        <a href="../../index.html" class="index-card">
          <span class="idx-label"><i class="fas fa-user" aria-hidden="true"></i> Profile</span>
        </a>
        <a href="../../cv.html" class="index-card">
          <span class="idx-label"><i class="fas fa-file" aria-hidden="true"></i> CV</span>
        </a>
        <a href="../../research.html" class="index-card">
          <span class="idx-label"><i class="fas fa-chart-line" aria-hidden="true"></i> Research</span>
        </a>
        <a href="../../teaching.html" class="index-card is-current" aria-current="page">
          <span class="idx-label"><i class="fas fa-graduation-cap" aria-hidden="true"></i> Teaching</span>
        </a>
        <a href="../../economics.html" class="index-card">
          <span class="idx-label"><i class="fas fa-chart-pie" aria-hidden="true"></i> Economics</span>
        </a>
      </nav>'''


def footer_html() -> str:
    cv_url = html.escape(
        "https://www.dropbox.com/scl/fi/6gfp5hvfgt76ic6liye70/"
        "CV_Arthur_Galichere.pdf"
        "?rlkey=g47ostrw9cvmxjdm8t6j2sgbq&st=hik4skpl&dl=1",
        quote=True,
    )
    return f'''      <footer class="foot">
        <div class="socials">
          <a href="mailto:arthur.galichere@warwick.ac.uk" aria-label="Email Arthur">
            <i class="fas fa-envelope" aria-hidden="true"></i>
          </a>
          <a href="{cv_url}" aria-label="Download Arthur Galichère's CV">
            <i class="fas fa-file-pdf" aria-hidden="true"></i>
          </a>
          <a href="https://warwick.ac.uk/fac/soc/economics/staff/agalichere/" target="_blank" rel="noreferrer" aria-label="University profile">
            <i class="fas fa-university" aria-hidden="true"></i>
          </a>
          <a href="https://www.linkedin.com/in/arthurgalichere/" target="_blank" rel="noreferrer" aria-label="LinkedIn profile">
            <i class="fab fa-linkedin" aria-hidden="true"></i>
          </a>
        </div>
        <span class="foot-loc">University of Warwick · Coventry, UK</span>
      </footer>'''


def pagination_html(note: Note) -> str:
    notes = list(NOTES)
    index = notes.index(note)
    previous_note = notes[index - 1] if index > 0 else None
    next_note = notes[index + 1] if index < len(notes) - 1 else None

    links: list[str] = []
    if previous_note:
        links.append(
            f'''        <a class="guidance-page-link is-previous" href="{html.escape(previous_note.output, quote=True)}">
          <i class="fas fa-arrow-left" aria-hidden="true"></i>
          <span class="guidance-page-copy">
            <span class="guidance-page-direction">Previous note</span>
            <span class="guidance-page-title">{html.escape(previous_note.title)}</span>
          </span>
        </a>'''
        )
    if next_note:
        links.append(
            f'''        <a class="guidance-page-link is-next" href="{html.escape(next_note.output, quote=True)}">
          <span class="guidance-page-copy">
            <span class="guidance-page-direction">Next note</span>
            <span class="guidance-page-title">{html.escape(next_note.title)}</span>
          </span>
          <i class="fas fa-arrow-right" aria-hidden="true"></i>
        </a>'''
        )

    modifier = " is-single" if len(links) == 1 else ""
    return f'''      <nav class="guidance-pagination{modifier}" aria-label="Guidance note navigation">
{os.linesep.join(links)}
      </nav>'''


def format_display_date(iso_date: str) -> str:
    try:
        parsed = date.fromisoformat(iso_date)
    except ValueError as exc:
        raise GuidanceUpdateError("DATE", f"Invalid ISO update date: {iso_date!r}.") from exc
    return parsed.strftime("%d/%m/%Y")


def build_page(note: Note, fragment: str, digest: str, updated: str, template_css: str) -> str:
    escaped_title = html.escape(note.title)
    escaped_description = html.escape(note.description, quote=True)
    escaped_pdf_url = html.escape(note.pdf_url, quote=True)
    display_date = format_display_date(updated)
    css = guidance_css(template_css)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arthur Galichère — {escaped_title}</title>
  <meta name="description" content="{escaped_description}" />
  <meta name="guidance-source-digest" content="{digest}" />
  <meta name="guidance-updated" content="{updated}" />

  <link rel="icon" type="image/png" href="../../website/images/favicon_transparant.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bitter:ital,wght@0,400;0,600;0,700;1,400&family=Montserrat:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />

  <style>
{css}
  </style>

  <script>
    window.MathJax = {{
      tex: {{ inlineMath: [['\\\\(', '\\\\)']], displayMath: [['\\\\[', '\\\\]']] }},
      options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'] }}
    }};
  </script>
  <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
  <main class="page">
    <article class="card">
{navigation_html()}

      <section class="guidance-body">
        <div class="guidance-toolbar">
          <a href="../dissertation.html" class="back-link">
            <i class="fas fa-arrow-left" aria-hidden="true"></i>
            Dissertation Supervision and Guidance
          </a>
          <a href="{escaped_pdf_url}" class="download-link">
            <i class="fas fa-download" aria-hidden="true"></i>
            Download PDF
          </a>
        </div>

        <h1 class="guidance-title">{escaped_title}</h1>

        <div class="guidance-content">{fragment}</div>
        <p class="guidance-update">Information updated on {display_date}</p>

{pagination_html(note)}
      </section>

{footer_html()}
    </article>
  </main>
</body>
</html>
'''


def validate_full_page(page: str, note: Note, digest: str, updated: str) -> None:
    required = (
        "<!DOCTYPE html>",
        note.title,
        'class="index-nav"',
        'href="../dissertation.html"',
        'class="guidance-content"',
        note.pdf_url.replace("&", "&amp;"),
        f'content="{digest}"',
        f'content="{updated}"',
        f"Information updated on {format_display_date(updated)}",
        'class="foot"',
    )
    for fragment in required:
        if fragment not in page:
            raise GuidanceUpdateError(
                "PAGE_VALIDATE",
                f"Generated page is missing required fragment: {fragment!r}.",
                note.slug,
            )

    match = re.search(
        r'<div class="guidance-content">(.*?)</div>\s*<p class="guidance-update">',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            "Could not isolate the generated guidance body in the completed page.",
            note.slug,
        )
    validate_converted_fragment(match.group(1), note)


def write_text(path: Path, content: str, stage: str, note: str | None = None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise GuidanceUpdateError(stage, f"Could not write {path}: {exc}.", note) from exc


def stage_bundle(
    pandoc: str,
    source_root: Path,
    guidance_dir: Path,
    staging_root: Path,
    template_css: str,
) -> None:
    copied_images = copy_web_images(source_root, staging_root)
    references_by_note: dict[str, set[str]] = {}

    for note in NOTES:
        source_path = source_root / note.source
        if not source_path.is_file():
            raise GuidanceUpdateError(
                "SOURCE_VALIDATE",
                f"Required source file is missing: {note.source}.",
                note.slug,
            )

        try:
            digest = source_digest(source_path, source_root)
        except (OSError, UnicodeError) as exc:
            raise GuidanceUpdateError(
                "HASH",
                f"Could not calculate the source digest: {exc}.",
                note.slug,
            ) from exc

        updated = choose_update_date(guidance_dir / note.output, digest)
        converted_path = staging_root / f".{note.slug}.fragment.html"
        fragment = convert_tex_to_html(pandoc, source_path, source_root, converted_path, note)
        converted_path.unlink(missing_ok=True)

        references_by_note[note.slug] = collect_image_references(fragment, note)
        page = build_page(note, fragment, digest, updated, template_css)
        validate_full_page(page, note, digest, updated)
        write_text(staging_root / note.output, page, "STAGE_WRITE", note.slug)
        log("STAGE", f"Prepared {note.output}.", note.slug)

    validate_referenced_images(references_by_note, copied_images, staging_root)


def validate_staged_bundle(staging_root: Path) -> None:
    log("BUNDLE_VALIDATE", "Validating the complete staged guidance bundle.")

    for note in NOTES:
        page_path = staging_root / note.output
        if not page_path.is_file():
            raise GuidanceUpdateError(
                "BUNDLE_VALIDATE",
                f"Staged page is missing: {note.output}.",
                note.slug,
            )
        if page_path.stat().st_size < 2_000:
            raise GuidanceUpdateError(
                "BUNDLE_VALIDATE",
                f"Staged page is unexpectedly small ({page_path.stat().st_size} bytes).",
                note.slug,
            )

        try:
            content = page_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise GuidanceUpdateError(
                "BUNDLE_VALIDATE",
                f"Staged page could not be read as UTF-8: {exc}.",
                note.slug,
            ) from exc

        digest, updated = current_page_metadata(page_path)
        if not digest or not updated:
            raise GuidanceUpdateError(
                "BUNDLE_VALIDATE",
                "Staged page has missing or invalid guidance metadata.",
                note.slug,
            )
        validate_full_page(content, note, digest, updated)

        parser = ImageSourceParser()
        parser.feed(content)
        for source in parser.sources:
            normalized = normalize_image_reference(source)
            if normalized and not (staging_root / Path(*PurePosixPath(normalized).parts)).is_file():
                raise GuidanceUpdateError(
                    "BUNDLE_VALIDATE",
                    f"Staged page references an absent image: {source}.",
                    note.slug,
                )

    log("BUNDLE_VALIDATE", "All four staged pages and their local image references are valid.")


def same_file(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and sha256_file(left) == sha256_file(right)


def directories_equal(left: Path, right: Path) -> bool:
    def manifest(root: Path) -> dict[str, str]:
        if not root.is_dir():
            return {}
        return {
            path.relative_to(root).as_posix(): sha256_file(path)
            for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
        }

    return manifest(left) == manifest(right)


def bundle_changed(staging_root: Path, guidance_dir: Path) -> bool:
    for note in NOTES:
        if not same_file(staging_root / note.output, guidance_dir / note.output):
            return True
    return not directories_equal(staging_root / "images", guidance_dir / "images")


def unique_sibling(path: Path, label: str) -> Path:
    return path.with_name(f".{path.name}.{label}.{uuid.uuid4().hex}")


def publish_bundle(staging_root: Path, guidance_dir: Path) -> None:
    targets = [guidance_dir / note.output for note in NOTES]
    targets.append(guidance_dir / "images")

    prepared: dict[Path, Path] = {}
    previous: dict[Path, Path] = {}
    installed: list[Path] = []

    try:
        for target in targets:
            source = staging_root / target.name
            prepared_path = unique_sibling(target, "next")

            if source.is_dir():
                shutil.copytree(source, prepared_path)
            elif source.is_file():
                shutil.copy2(source, prepared_path)
            elif target.name == "images":
                prepared_path.mkdir(parents=True)
            else:
                raise GuidanceUpdateError(
                    "PUBLISH_PREPARE",
                    f"The staged source is missing: {source}.",
                )

            prepared[target] = prepared_path

        for target in targets:
            if target.exists() or target.is_symlink():
                previous_path = unique_sibling(target, "previous")
                os.replace(target, previous_path)
                previous[target] = previous_path

        try:
            for target in targets:
                os.replace(prepared[target], target)
                installed.append(target)
        except OSError as exc:
            raise GuidanceUpdateError(
                "PUBLISH_INSTALL",
                f"Could not install the staged guidance bundle: {exc}.",
            ) from exc

        for backup in previous.values():
            if backup.is_dir():
                shutil.rmtree(backup)
            elif backup.exists():
                backup.unlink()

    except Exception:
        for target in reversed(installed):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists() or target.is_symlink():
                target.unlink(missing_ok=True)

        for target, backup in previous.items():
            if backup.exists() or backup.is_symlink():
                os.replace(backup, target)

        for temporary in prepared.values():
            if temporary.is_dir():
                shutil.rmtree(temporary, ignore_errors=True)
            elif temporary.exists():
                temporary.unlink(missing_ok=True)
        raise

    finally:
        for temporary in [*prepared.values(), *previous.values()]:
            if temporary.is_dir():
                shutil.rmtree(temporary, ignore_errors=True)
            elif temporary.exists():
                temporary.unlink(missing_ok=True)


def read_template(path: Path) -> str:
    log("TEMPLATE", f"Reading shared layout from {path}.")
    if not path.is_file():
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"The supervision template does not exist: {path}.",
        )
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError("TEMPLATE", f"Could not read {path}: {exc}.") from exc

    required_fragments = ('class="index-nav"', 'class="foot"', ".supervision-body")
    for fragment in required_fragments:
        if fragment not in content:
            raise GuidanceUpdateError(
                "TEMPLATE",
                f"The supervision template is missing required fragment: {fragment!r}.",
            )
    return content


def main() -> int:
    repo_root, guidance_dir, supervision_template = repo_paths()

    try:
        pandoc = require_pandoc()
        template = read_template(supervision_template)
        template_css = extract_style_block(template)

        with tempfile.TemporaryDirectory(prefix="guidance-update-") as temporary:
            workspace = Path(temporary)
            archive = workspace / "dropbox-guidance.zip"
            extracted = workspace / "extracted"
            staged = workspace / "staged"
            extracted.mkdir()
            staged.mkdir()

            download_dropbox_zip(archive)
            safe_extract_zip(archive, extracted)
            source_root = locate_source_root(extracted)
            stage_bundle(pandoc, source_root, guidance_dir, staged, template_css)
            validate_staged_bundle(staged)

            if not bundle_changed(staged, guidance_dir):
                log("NO_CHANGE", "The generated guidance bundle is identical to the published bundle.")
                return 0

            log("PUBLISH", "Installing all four validated pages and their image bundle transactionally.")
            publish_bundle(staged, guidance_dir)

        log("COMPLETE", f"Published dissertation guidance successfully in {guidance_dir}.")
        log("COMPLETE", f"Repository root resolved as {repo_root}.")
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
