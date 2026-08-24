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
TEMPLATE_VERSION = "4"


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

                pure_path = PurePosixPath(normalized_name)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Unsafe archive path rejected: {raw_name!r}.",
                    )

                if pure_path.parts and re.match(r"^[A-Za-z]:$", pure_path.parts[0]):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Windows drive path rejected: {raw_name!r}.",
                    )

                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Symbolic link rejected in archive: {raw_name!r}.",
                    )

                target = destination.joinpath(*pure_path.parts).resolve()
                try:
                    target.relative_to(destination_resolved)
                except ValueError as exc:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Archive member escapes the extraction directory: {raw_name!r}.",
                    ) from exc

                validated_members.append(member)

            for member in validated_members:
                normalized_name = member.filename.replace("\\", "/")
                pure_path = PurePosixPath(normalized_name)
                target = destination.joinpath(*pure_path.parts)

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except GuidanceUpdateError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise GuidanceUpdateError(
            "ZIP_EXTRACT",
            f"The archive could not be extracted safely: {exc}.",
        ) from exc

    message = f"Extracted {len(validated_members)} validated archive entries safely."
    if skipped_root_entries:
        message += f" Skipped {skipped_root_entries} harmless Dropbox root entry."
    log("ZIP_EXTRACT", message)


def ignored_path(path: Path) -> bool:
    return any(part.casefold() in IGNORED_DIRECTORY_NAMES for part in path.parts)


def source_candidates(extracted_root: Path, filename: str) -> list[Path]:
    return [
        path
        for path in extracted_root.rglob(filename)
        if path.is_file() and not ignored_path(path.relative_to(extracted_root))
    ]


def locate_source_directory(extracted_root: Path) -> tuple[Path, dict[str, Path]]:
    log("SOURCE_DISCOVERY", "Locating the four allowlisted TeX source files.")
    candidates_by_source = {
        note.source: source_candidates(extracted_root, note.source)
        for note in NOTES
    }

    missing = [source for source, candidates in candidates_by_source.items() if not candidates]
    if missing:
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "Missing required TeX source file(s): " + ", ".join(missing),
        )

    ambiguous = {
        source: candidates
        for source, candidates in candidates_by_source.items()
        if len(candidates) > 1
    }
    if ambiguous:
        details = "; ".join(
            f"{source}: {', '.join(str(path.relative_to(extracted_root)) for path in paths)}"
            for source, paths in ambiguous.items()
        )
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "Multiple copies of an allowlisted source were found. " + details,
        )

    sources = {source: candidates[0] for source, candidates in candidates_by_source.items()}
    parent_directories = {path.parent.resolve() for path in sources.values()}
    if len(parent_directories) != 1:
        locations = ", ".join(str(path.relative_to(extracted_root)) for path in sources.values())
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "The four TeX sources are not in one directory: " + locations,
        )

    source_root = next(iter(parent_directories))
    log("SOURCE_DISCOVERY", f"Using source directory: {source_root}.")
    return source_root, sources


def copy_web_images(source_root: Path, staging_images: Path) -> int:
    source_images = source_root / "images"
    staging_images.mkdir(parents=True, exist_ok=True)

    if not source_images.exists():
        log("IMAGES", "No top-level images directory was found; continuing without local images.")
        return 0
    if not source_images.is_dir():
        raise GuidanceUpdateError(
            "IMAGES",
            f"Expected {source_images} to be a directory.",
        )

    log("IMAGES", f"Copying web-compatible images from {source_images}.")
    copied = 0
    seen_casefolded: dict[str, str] = {}

    for source in sorted(source_images.rglob("*")):
        if source.is_dir():
            continue

        relative = source.relative_to(source_images)
        if ignored_path(relative):
            continue
        if source.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            continue

        key = relative.as_posix().casefold()
        previous = seen_casefolded.get(key)
        if previous and previous != relative.as_posix():
            raise GuidanceUpdateError(
                "IMAGES",
                "Image paths differ only by capitalization and would be ambiguous: "
                f"{previous!r} and {relative.as_posix()!r}.",
            )
        seen_casefolded[key] = relative.as_posix()

        destination = staging_images / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    log("IMAGES", f"Copied {copied} web-compatible image file(s).")
    return copied


def strip_tex_comments(source: str) -> str:
    cleaned_lines = []
    for line in source.splitlines():
        index = 0
        while index < len(line):
            if line[index] == "%":
                backslashes = 0
                cursor = index - 1
                while cursor >= 0 and line[cursor] == "\\":
                    backslashes += 1
                    cursor -= 1
                if backslashes % 2 == 0:
                    line = line[:index]
                    break
            index += 1
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def normalize_image_reference(reference: str) -> str | None:
    decoded = urllib.parse.unquote(reference.strip()).replace("\\", "/")
    parsed = urllib.parse.urlsplit(decoded)
    if parsed.scheme or parsed.netloc or decoded.startswith("data:"):
        return None

    path = parsed.path
    while path.startswith("./"):
        path = path[2:]
    if not path:
        return None

    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None
    return pure_path.as_posix()


def normalize_tex_image_reference(reference: str) -> str | None:
    normalized = normalize_image_reference(reference)
    if not normalized:
        return None

    pure_path = PurePosixPath(normalized)
    if pure_path.parts and pure_path.parts[0].casefold() != "images":
        pure_path = PurePosixPath("images") / pure_path

    if not pure_path.suffix:
        for extension in sorted(WEB_IMAGE_EXTENSIONS):
            candidate = pure_path.with_suffix(extension)
            return candidate.as_posix()

    return pure_path.as_posix()


def referenced_local_images(tex_source: str) -> set[str]:
    without_comments = strip_tex_comments(tex_source)
    references: set[str] = set()
    pattern = re.compile(r"\\includegraphics(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}")
    for match in pattern.finditer(without_comments):
        normalized = normalize_tex_image_reference(match.group(1))
        if normalized:
            references.add(normalized)
    return references


def tex_image_widths(tex_source: str) -> dict[str, float]:
    """Return relative image widths declared with common LaTeX width units."""
    without_comments = strip_tex_comments(tex_source)
    widths: dict[str, float] = {}
    pattern = re.compile(
        r"\\includegraphics\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}",
        re.IGNORECASE,
    )

    for match in pattern.finditer(without_comments):
        options = match.group(1) or ""
        normalized = normalize_tex_image_reference(match.group(2))
        if not normalized:
            continue

        width_match = re.search(
            r"(?:^|,)\s*width\s*=\s*"
            r"(?:(\d*\.?\d+)\s*\\(?:line|text|column)width"
            r"|(\d*\.?\d+)\s*%)",
            options,
            re.IGNORECASE,
        )
        if not width_match:
            continue

        if width_match.group(1) is not None:
            percentage = float(width_match.group(1)) * 100
        else:
            percentage = float(width_match.group(2))

        if 0 < percentage <= 500:
            widths[normalized.casefold()] = percentage
            widths[PurePosixPath(normalized).with_suffix("").as_posix().casefold()] = percentage

    return widths


def image_reference_keys(source: str) -> tuple[str, ...]:
    normalized = normalize_image_reference(source)
    if not normalized:
        return ()

    path = PurePosixPath(normalized)
    return (
        path.as_posix().casefold(),
        path.with_suffix("").as_posix().casefold(),
    )


def set_style_width(attributes: str, percentage: float) -> str:
    width_value = f"{percentage:g}%"
    stripped = attributes.rstrip()
    self_closing = stripped.endswith("/")
    working = stripped[:-1].rstrip() if self_closing else stripped
    style_match = re.search(
        r"\sstyle\s*=\s*([\"'])(.*?)\1",
        working,
        re.IGNORECASE | re.DOTALL,
    )

    if style_match:
        declarations = [
            declaration.strip()
            for declaration in style_match.group(2).split(";")
            if declaration.strip()
            and not re.match(
                r"^(?:width|--tex-image-width)\s*:",
                declaration,
                re.IGNORECASE,
            )
        ]
        declarations.append(f"--tex-image-width: {width_value}")
        replacement = f' style="{html.escape("; ".join(declarations), quote=True)}"'
        working = working[: style_match.start()] + replacement + working[style_match.end() :]
    else:
        working += f' style="--tex-image-width: {width_value};"'

    return working + (" /" if self_closing else "")


def apply_tex_image_widths(fragment: str, tex_source: str, note: Note) -> str:
    """Apply LaTeX image width fractions to the corresponding HTML images."""
    widths = tex_image_widths(tex_source)
    if not widths:
        return fragment

    applied = 0
    image_pattern = re.compile(r"<img\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)

    def replace_image(match: re.Match[str]) -> str:
        nonlocal applied
        attributes = match.group("attrs")
        source_match = re.search(
            r"\bsrc\s*=\s*([\"'])(.*?)\1",
            attributes,
            re.IGNORECASE | re.DOTALL,
        )
        if not source_match:
            return match.group(0)

        percentage = next(
            (
                widths[key]
                for key in image_reference_keys(html.unescape(source_match.group(2)))
                if key in widths
            ),
            None,
        )
        if percentage is None:
            return match.group(0)

        applied += 1
        return f"<img{set_style_width(attributes, percentage)}>"

    adjusted = image_pattern.sub(replace_image, fragment)
    if applied:
        log(
            "IMAGE_SCALE",
            f"Applied LaTeX width settings to {applied} converted image(s).",
            note.slug,
        )
    return adjusted


def case_insensitive_file(root: Path, reference: str) -> Path | None:
    target = PurePosixPath(reference)
    current = root

    for part in target.parts:
        if not current.is_dir():
            return None
        exact = current / part
        if exact.exists():
            current = exact
            continue
        matches = [entry for entry in current.iterdir() if entry.name.casefold() == part.casefold()]
        if len(matches) != 1:
            return None
        current = matches[0]

    return current if current.is_file() else None


def resolve_image_for_digest(reference: str, source_root: Path) -> Path | None:
    exact = source_root.joinpath(*PurePosixPath(reference).parts)
    if exact.is_file():
        return exact

    if not PurePosixPath(reference).suffix:
        for extension in WEB_IMAGE_EXTENSIONS:
            candidate = exact.with_suffix(extension)
            if candidate.is_file():
                return candidate

    return case_insensitive_file(source_root, reference)


def source_digest(source_path: Path, source_root: Path, note: Note) -> str:
    try:
        source_bytes = source_path.read_bytes()
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuidanceUpdateError(
            "SOURCE_READ",
            f"{note.source} is not valid UTF-8: {exc}.",
            note.slug,
        ) from exc
    except OSError as exc:
        raise GuidanceUpdateError(
            "SOURCE_READ",
            f"Could not read {note.source}: {exc}.",
            note.slug,
        ) from exc

    digest = hashlib.sha256()
    digest.update(f"template-version:{TEMPLATE_VERSION}\0".encode())
    digest.update(source_bytes)

    for reference in sorted(referenced_local_images(source_text)):
        image_path = resolve_image_for_digest(reference, source_root)
        digest.update(b"\0image-reference:\0")
        digest.update(reference.encode("utf-8"))
        if image_path:
            digest.update(b"\0image-content:\0")
            digest.update(image_path.read_bytes())
        else:
            digest.update(b"\0missing\0")

    return digest.hexdigest()


def pandoc_version() -> str:
    executable = shutil.which("pandoc")
    if not executable:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            "Pandoc is not installed or is not available on PATH.",
        )

    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            f"Pandoc could not be executed: {exc}.",
        ) from exc

    first_line = result.stdout.splitlines()[0] if result.stdout else "pandoc (version unknown)"
    log("DEPENDENCY", f"Using {first_line}.")
    return executable


def convert_tex_to_html(pandoc: str, source_path: Path, source_root: Path, note: Note) -> str:
    log("CONVERT", f"Converting {note.source} with Pandoc.", note.slug)
    command = [
        pandoc,
        str(source_path),
        "--from=latex",
        "--to=html5",
        "--mathjax",
        "--wrap=none",
        f"--resource-path={source_root}",
    ]

    try:
        result = subprocess.run(
            command,
            cwd=source_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            "Pandoc timed out after 120 seconds.",
            note.slug,
        ) from exc
    except OSError as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc could not be started: {exc}.",
            note.slug,
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip() or "No diagnostic output was provided."
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc exited with status {result.returncode}: {stderr}",
            note.slug,
        )

    fragment = result.stdout.strip()
    if not fragment:
        raise GuidanceUpdateError(
            "CONVERT",
            "Pandoc returned an empty HTML fragment.",
            note.slug,
        )

    if result.stderr.strip():
        log("CONVERT_WARNING", result.stderr.strip(), note.slug)

    return fragment


def rewrite_image_sources(fragment: str) -> str:
    pattern = re.compile(
        r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(.*?)(\2)",
        re.IGNORECASE | re.DOTALL,
    )

    def replacement(match: re.Match[str]) -> str:
        raw_source = html.unescape(match.group(3))
        normalized = normalize_image_reference(raw_source)
        if not normalized:
            return match.group(0)

        pure_path = PurePosixPath(normalized)
        if not pure_path.parts:
            return match.group(0)
        if pure_path.parts[0].casefold() != "images":
            pure_path = PurePosixPath("images") / pure_path

        return f"{match.group(1)}{match.group(2)}{html.escape(pure_path.as_posix(), quote=True)}{match.group(4)}"

    return pattern.sub(replacement, fragment)


def visible_text_length(fragment: str) -> int:
    without_tags = re.sub(r"<[^>]+>", " ", fragment)
    decoded = html.unescape(without_tags)
    normalized = re.sub(r"\s+", " ", decoded).strip()
    return len(normalized)


def ensure_case_correct_image_references(fragment: str, staging_images: Path, note: Note) -> str:
    parser = ImageSourceParser()
    try:
        parser.feed(fragment)
    except Exception as exc:
        raise GuidanceUpdateError(
            "IMAGE_REFERENCE",
            f"Could not inspect converted image references: {exc}.",
            note.slug,
        ) from exc

    reference_map: dict[str, str] = {}
    missing: list[str] = []

    for source in parser.sources:
        normalized = normalize_image_reference(source)
        if not normalized or not normalized.startswith("images/"):
            continue

        relative = normalized.removeprefix("images/")
        relative_path = PurePosixPath(relative)
        exact = staging_images.joinpath(*relative_path.parts)
        if exact.is_file():
            continue

        actual = case_insensitive_file(staging_images, relative)
        if not actual:
            missing.append(source)
            continue

        actual_relative = actual.relative_to(staging_images)
        expected = staging_images.joinpath(*relative_path.parts)

        if expected.exists() and expected.resolve() != actual.resolve():
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                f"Cannot create the case-correct image path {normalized!r} because another file already exists there.",
                note.slug,
            )

        expected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(actual, expected)
        reference_map[source] = "images/" + actual_relative.as_posix()
        log(
            "IMAGE_CASE",
            f"Created case-compatible image path for {source!r}.",
            note.slug,
        )

    if missing:
        raise GuidanceUpdateError(
            "IMAGE_REFERENCE",
            "Converted content references missing or unsupported image(s): " + ", ".join(sorted(set(missing))),
            note.slug,
        )

    if not reference_map:
        return fragment

    pattern = re.compile(
        r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(.*?)(\2)",
        re.IGNORECASE | re.DOTALL,
    )

    def replacement(match: re.Match[str]) -> str:
        source = html.unescape(match.group(3))
        corrected = reference_map.get(source)
        if not corrected:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{html.escape(corrected, quote=True)}{match.group(4)}"

    return pattern.sub(replacement, fragment)


def extract_previous_metadata(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, None

    digest_match = re.search(
        r'<meta\s+name=["\']guidance-source-digest["\']\s+content=["\']([0-9a-f]{64})["\']',
        content,
        re.IGNORECASE,
    )
    date_match = re.search(
        r'<meta\s+name=["\']guidance-updated["\']\s+content=["\'](\d{4}-\d{2}-\d{2})["\']',
        content,
        re.IGNORECASE,
    )
    return (
        digest_match.group(1) if digest_match else None,
        date_match.group(1) if date_match else None,
    )


def determine_update_date(output_path: Path, digest: str) -> str:
    previous_digest, previous_date = extract_previous_metadata(output_path)
    if previous_digest == digest and previous_date:
        return previous_date
    return date.today().isoformat()


def display_date(iso_date: str) -> str:
    year, month, day = iso_date.split("-")
    return f"{day}/{month}/{year}"


def template_css() -> str:
    return r'''
    :root {
      --paper: #f4f5f7;
      --paper-soft: #fafbfc;
      --sheet: #ffffff;
      --panel-deep: #e2e5e9;
      --line: rgba(28, 28, 30, 0.08);
      --line-strong: rgba(28, 28, 30, 0.15);
      --ink: #1c1c1e;
      --ink-soft: #3a3a3c;
      --muted: #71717a;
      --accent: #3b5a75;
      --accent-strong: #25394b;
      --accent-soft: #edf2f6;
      --display: 'Bitter', Georgia, serif;
      --sans: 'Montserrat', system-ui, sans-serif;
      --mono: 'JetBrains Mono', monospace;
    }

    *, *::before, *::after {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    html { background: var(--paper); }

    body {
      min-height: 100vh;
      color: var(--ink);
      background: linear-gradient(180deg, var(--paper-soft) 0%, var(--paper) 100%);
      font-family: var(--sans);
      -webkit-font-smoothing: antialiased;
    }

    a:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
      border-radius: 2px;
    }

    .page {
      width: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: clamp(0.7rem, 4vh, 2.5rem) 1rem 1rem;
    }

    .card {
      width: min(100%, 1100px);
      overflow: hidden;
      background: var(--sheet);
      border: 1px solid var(--line-strong);
      border-radius: 6px;
      box-shadow: 0 20px 48px rgba(28, 28, 30, 0.08);
    }

    .card::before {
      content: '';
      display: block;
      height: 4px;
      background: var(--accent);
    }

    .index-nav {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      border-bottom: 1px solid var(--line-strong);
    }

    .index-card {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 1rem;
      padding: 1.1rem 1.4rem;
      color: var(--ink);
      text-decoration: none;
      border-left: 1px solid var(--line);
      transition: background-color 0.16s ease, color 0.16s ease;
    }

    .index-card:first-child { border-left: none; }

    .index-nav .idx-label {
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
      font-family: var(--display);
      font-size: 1.15rem;
      font-weight: 600;
    }

    .index-nav .idx-label i {
      width: 1.1rem;
      color: var(--accent);
      font-size: 0.85rem;
      text-align: center;
    }

    .index-card.is-current {
      color: var(--accent-strong);
      background: var(--accent-soft);
    }

    .index-card.is-current .idx-label i { color: var(--accent-strong); }

    .index-card:hover {
      color: #fff;
      background: var(--accent);
    }

    .index-card:hover .idx-label,
    .index-card:hover .idx-label i { color: #fff; }

    .guidance-body { padding: 3rem 2.5rem; }

    .guidance-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 2rem;
    }

    .back-link {
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

    .back-link:hover {
      color: #fff;
      background: var(--accent);
      border-color: var(--accent);
      transform: translateY(-1px);
    }

    .download-link {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      color: var(--accent);
      font-size: 0.9rem;
      font-weight: 600;
      text-decoration: none;
      transition: color 0.16s ease;
    }

    .download-link:hover { color: var(--accent-strong); }
    .download-link i { margin-right: 0.3rem; }

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
      width: auto;
      max-width: 100%;
      height: auto;
      margin: 1.5rem auto;
      border: 1px solid var(--line-strong);
      border-radius: 4px;
    }

    .guidance-content img[style*="--tex-image-width"] {
      width: var(--tex-image-width);
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

    .guidance-content pre code {
      padding: 0;
      background: transparent;
      border: none;
    }

    .guidance-pagination {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
      margin-top: 3rem;
    }

    .guidance-pagination.is-single { grid-template-columns: minmax(0, 1fr); }

    .guidance-page-link {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 0.85rem;
      min-width: 0;
      padding: 1rem 1.1rem;
      color: var(--ink);
      background: var(--paper-soft);
      border: 1px solid var(--line-strong);
      border-radius: 5px;
      text-decoration: none;
      transition: color 0.16s ease, background-color 0.16s ease,
                  border-color 0.16s ease, box-shadow 0.16s ease,
                  transform 0.16s ease;
    }

    .guidance-page-link:hover {
      color: var(--accent-strong);
      background: var(--accent-soft);
      border-color: rgba(59, 90, 117, 0.4);
      box-shadow: 0 7px 18px rgba(28, 28, 30, 0.06);
      transform: translateY(-1px);
    }

    .guidance-page-link.next { text-align: right; }

    .guidance-page-link .direction-icon,
    .guidance-page-link .page-arrow {
      color: var(--accent);
      font-size: 0.8rem;
    }

    .guidance-page-label {
      display: block;
      margin-bottom: 0.2rem;
      color: var(--muted);
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

    .guidance-update {
      margin-top: 2.25rem;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.78rem;
      letter-spacing: 0.03em;
      text-align: center;
    }

    .back-to-top {
      width: 2.55rem;
      height: 2.55rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--ink-soft);
      background: var(--sheet);
      border: 1px solid var(--line-strong);
      border-radius: 50%;
      font-size: 0.85rem;
      text-decoration: none;
      box-shadow: 0 4px 12px rgba(28, 28, 30, 0.05);
      transition: color 0.16s ease, background-color 0.16s ease,
                  border-color 0.16s ease, transform 0.16s ease,
                  box-shadow 0.16s ease;
    }

    .back-to-top:hover {
      color: #fff;
      background: var(--accent);
      border-color: var(--accent);
      box-shadow: 0 6px 16px rgba(28, 28, 30, 0.1);
      transform: translateY(-2px);
    }

    .back-to-top:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
    }

    html { scroll-behavior: smooth; }

    .foot {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
      align-items: center;
      gap: 1rem;
      padding: 0.9rem 1.5rem;
      background: var(--panel-deep);
      border-top: 1px solid var(--line);
    }

    .foot .back-to-top { justify-self: center; }

    .foot-loc {
      justify-self: end;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.68rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .socials {
      display: flex;
      align-items: center;
      justify-self: start;
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
      html { scroll-behavior: auto; }

      .index-card,
      .back-link,
      .download-link,
      .guidance-page-link,
      .back-to-top,
      .socials a { transition: none; }
    }

    @media (max-width: 768px) {
      .index-nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .guidance-body { padding: 2rem 1.5rem; }

      .guidance-content img[style*="--tex-image-width"] {
        width: min(100%, calc(var(--tex-image-width) + 30%));
      }
    }

    @media (max-width: 680px) {
      .index-nav { grid-template-columns: 1fr; }
      .index-card { border-top: 1px solid var(--line); border-left: none; }
      .index-card:first-child { border-top: none; }
      .guidance-toolbar { align-items: stretch; flex-direction: column; }
      .back-link { justify-content: center; }
      .download-link { align-self: center; justify-content: center; }
      .guidance-title { font-size: 2.15rem; }
      .guidance-pagination { grid-template-columns: 1fr; }
      .foot {
        display: flex;
        flex-direction: column;
        text-align: center;
      }
      .foot .back-to-top { order: -1; }
      .foot-loc { justify-self: auto; }
      .socials { justify-self: auto; }
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


def back_to_top_html() -> str:
    return '''        <a href="#top" class="back-to-top" aria-label="Back to the top of the page" title="Back to top">
          <i class="fas fa-arrow-up" aria-hidden="true"></i>
        </a>'''


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
{back_to_top_html()}
        <span class="foot-loc">University of Warwick · Coventry, UK</span>
      </footer>'''


def pagination_html(note: Note) -> str:
    notes = list(NOTES)
    index = notes.index(note)
    links: list[str] = []

    if index > 0:
        previous = notes[index - 1]
        links.append(f'''        <a href="{html.escape(previous.output, quote=True)}" class="guidance-page-link previous">
          <i class="fas fa-arrow-left direction-icon" aria-hidden="true"></i>
          <span>
            <span class="guidance-page-label">Previous guidance note</span>
            <span class="guidance-page-title">{html.escape(previous.title)}</span>
          </span>
          <i class="fas fa-chevron-left page-arrow" aria-hidden="true"></i>
        </a>''')

    if index < len(notes) - 1:
        following = notes[index + 1]
        links.append(f'''        <a href="{html.escape(following.output, quote=True)}" class="guidance-page-link next">
          <i class="fas fa-chevron-right page-arrow" aria-hidden="true"></i>
          <span>
            <span class="guidance-page-label">Next guidance note</span>
            <span class="guidance-page-title">{html.escape(following.title)}</span>
          </span>
          <i class="fas fa-arrow-right direction-icon" aria-hidden="true"></i>
        </a>''')

    single_class = " is-single" if len(links) == 1 else ""
    return f'''      <nav class="guidance-pagination{single_class}" aria-label="Guidance note navigation">
{chr(10).join(links)}
      </nav>'''


def render_page(note: Note, fragment: str, digest: str, updated: str) -> str:
    pdf_url = html.escape(note.pdf_url, quote=True)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Arthur Galichère — {html.escape(note.title)}</title>
  <meta name="description" content="{html.escape(note.description, quote=True)}" />
  <meta name="guidance-source-digest" content="{digest}" />
  <meta name="guidance-updated" content="{updated}" />

  <link rel="icon" type="image/png" href="../../website/images/favicon_transparant.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bitter:ital,wght@0,400;0,600;0,700;1,400&family=Montserrat:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" />
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>

  <style>
{template_css()}
  </style>
</head>
<body id="top">
  <main class="page">
    <article class="card">
{navigation_html()}

      <section class="guidance-body">
        <div class="guidance-toolbar">
          <a href="../dissertation.html" class="back-link">
            <i class="fas fa-arrow-left" aria-hidden="true"></i>
            Dissertation Supervision and Guidance
          </a>
          <a href="{pdf_url}" class="download-link">
            <i class="fas fa-download" aria-hidden="true"></i>
            Download PDF
          </a>
        </div>

        <h1 class="guidance-title">{html.escape(note.title)}</h1>

        <div class="guidance-content">
{fragment}
        </div>

{pagination_html(note)}

        <p class="guidance-update">Information updated on {display_date(updated)}</p>
      </section>

{footer_html()}
    </article>
  </main>
</body>
</html>
'''


def validate_fragment(fragment: str, staging_images: Path, note: Note) -> None:
    text_length = visible_text_length(fragment)
    if text_length < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "CONTENT_VALIDATE",
            f"Converted content contains only {text_length} visible characters; expected at least {MINIMUM_CONVERTED_TEXT_LENGTH}.",
            note.slug,
        )

    parser = ImageSourceParser()
    try:
        parser.feed(fragment)
    except Exception as exc:
        raise GuidanceUpdateError(
            "CONTENT_VALIDATE",
            f"Converted HTML could not be parsed for images: {exc}.",
            note.slug,
        ) from exc

    missing: list[str] = []
    for source in parser.sources:
        normalized = normalize_image_reference(source)
        if not normalized or not normalized.startswith("images/"):
            continue
        relative = normalized.removeprefix("images/")
        candidate = staging_images.joinpath(*PurePosixPath(relative).parts)
        if not candidate.is_file():
            missing.append(source)

    if missing:
        raise GuidanceUpdateError(
            "IMAGE_REFERENCE",
            "Converted content references missing or unsupported image(s): " + ", ".join(sorted(set(missing))),
            note.slug,
        )


def validate_complete_page(content: str, note: Note, digest: str, updated: str) -> None:
    required_fragments = (
        "<!DOCTYPE html>",
        note.title,
        'class="index-nav"',
        'href="../dissertation.html"',
        'class="download-link"',
        note.pdf_url.replace("&", "&amp;"),
        'class="guidance-content"',
        'class="guidance-update"',
        f"Information updated on {display_date(updated)}",
        'class="back-to-top"',
        'href="#top"',
        'class="foot"',
        f'content="{digest}"',
        f'content="{updated}"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in content]
    if missing:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            "Generated page is missing required content: " + ", ".join(repr(value) for value in missing),
            note.slug,
        )

    if content.count("<html") != 1 or content.count("</html>") != 1:
        raise GuidanceUpdateError(
            "PAGE_VALIDATE",
            "Generated page does not contain exactly one complete HTML document.",
            note.slug,
        )


def write_text_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_staged_bundle(
    pandoc: str,
    source_root: Path,
    sources: dict[str, Path],
    guidance_dir: Path,
    staging_dir: Path,
) -> None:
    staging_images = staging_dir / "images"
    copy_web_images(source_root, staging_images)

    for note in NOTES:
        source_path = sources[note.source]
        digest = source_digest(source_path, source_root, note)
        updated = determine_update_date(guidance_dir / note.output, digest)

        try:
            tex_source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise GuidanceUpdateError(
                "SOURCE_READ",
                f"Could not read {note.source}: {exc}.",
                note.slug,
            ) from exc

        fragment = convert_tex_to_html(pandoc, source_path, source_root, note)
        fragment = rewrite_image_sources(fragment)
        fragment = ensure_case_correct_image_references(fragment, staging_images, note)
        fragment = apply_tex_image_widths(fragment, tex_source, note)
        validate_fragment(fragment, staging_images, note)

        page = render_page(note, fragment, digest, updated)
        validate_complete_page(page, note, digest, updated)
        write_text_atomically(staging_dir / note.output, page)
        log("STAGE", f"Prepared {note.output}.", note.slug)


def compare_files(left: Path, right: Path) -> bool:
    if not left.is_file() or not right.is_file():
        return False
    return left.read_bytes() == right.read_bytes()


def directory_manifest(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}

    manifest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def bundle_changed(staging_dir: Path, guidance_dir: Path) -> bool:
    for note in NOTES:
        if not compare_files(staging_dir / note.output, guidance_dir / note.output):
            return True
    return directory_manifest(staging_dir / "images") != directory_manifest(guidance_dir / "images")


def replace_bundle_transactionally(staging_dir: Path, guidance_dir: Path) -> None:
    log("PUBLISH", "Publishing the validated guidance bundle transactionally.")
    transaction_id = uuid.uuid4().hex
    page_backups: dict[Path, Path] = {}
    new_page_paths: list[Path] = []
    image_destination = guidance_dir / "images"
    image_backup = guidance_dir / f".images.previous.{transaction_id}"
    image_next = guidance_dir / f".images.next.{transaction_id}"

    try:
        for note in NOTES:
            destination = guidance_dir / note.output
            staged = staging_dir / note.output
            next_path = guidance_dir / f".{note.output}.next.{transaction_id}"
            backup_path = guidance_dir / f".{note.output}.previous.{transaction_id}"

            shutil.copy2(staged, next_path)
            new_page_paths.append(next_path)
            if destination.exists():
                os.replace(destination, backup_path)
                page_backups[destination] = backup_path
            os.replace(next_path, destination)

        if (staging_dir / "images").is_dir():
            shutil.copytree(staging_dir / "images", image_next)
        else:
            image_next.mkdir(parents=True)

        if image_destination.exists():
            os.replace(image_destination, image_backup)
        os.replace(image_next, image_destination)

    except Exception as exc:
        log("ROLLBACK", f"Publication failed; restoring the previous bundle: {exc}.")

        for note in NOTES:
            destination = guidance_dir / note.output
            backup = page_backups.get(destination)
            if backup and backup.exists():
                if destination.exists():
                    destination.unlink()
                os.replace(backup, destination)
            elif destination.exists() and destination not in page_backups:
                destination.unlink()

        if image_backup.exists():
            if image_destination.exists():
                shutil.rmtree(image_destination)
            os.replace(image_backup, image_destination)
        elif image_destination.exists() and not (guidance_dir / "images").samefile(image_destination):
            shutil.rmtree(image_destination)

        raise GuidanceUpdateError(
            "PUBLISH",
            f"Could not publish the generated bundle; the previous bundle was restored: {exc}.",
        ) from exc
    finally:
        for path in new_page_paths:
            if path.exists():
                path.unlink()
        if image_next.exists():
            shutil.rmtree(image_next)

    for backup in page_backups.values():
        if backup.exists():
            backup.unlink()
    if image_backup.exists():
        shutil.rmtree(image_backup)

    log("PUBLISH", "Published all four guidance pages and images successfully.")


def validate_template_exists(template_path: Path) -> None:
    if not template_path.is_file():
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"Shared template is missing: {template_path}.",
        )
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"Could not read shared template {template_path}: {exc}.",
        ) from exc

    required = ('class="index-nav"', 'class="foot')
    missing = [fragment for fragment in required if fragment not in template_text]
    if missing:
        raise GuidanceUpdateError(
            "TEMPLATE",
            "The shared supervision template is missing expected layout markers: " + ", ".join(missing),
        )
    log("TEMPLATE", f"Reading shared layout from {template_path}.")


def main() -> int:
    _, guidance_dir, supervision_template = repo_paths()

    try:
        validate_template_exists(supervision_template)
        pandoc = pandoc_version()

        with tempfile.TemporaryDirectory(prefix="guidance-update-") as temporary_root_text:
            temporary_root = Path(temporary_root_text)
            archive = temporary_root / "guidance.zip"
            extracted = temporary_root / "extracted"
            staging = temporary_root / "staging"
            extracted.mkdir()
            staging.mkdir()

            download_dropbox_zip(archive)
            safe_extract_zip(archive, extracted)
            source_root, sources = locate_source_directory(extracted)
            build_staged_bundle(pandoc, source_root, sources, guidance_dir, staging)

            if not bundle_changed(staging, guidance_dir):
                log("NO_CHANGE", "The validated guidance bundle matches the published bundle.")
                return 0

            replace_bundle_transactionally(staging, guidance_dir)
            log("COMPLETE", "Guidance publication completed successfully.")
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
