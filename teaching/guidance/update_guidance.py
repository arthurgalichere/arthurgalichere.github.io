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
TEMPLATE_VERSION = "3"


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
                        f"Unsafe archive root file rejected: {raw_name!r}.",
                    )

                pure_path = PurePosixPath(normalized_name)
                if pure_path.is_absolute() or ".." in pure_path.parts:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Unsafe archive path rejected: {raw_name!r}.",
                    )

                if pure_path.parts and re.fullmatch(r"[A-Za-z]:", pure_path.parts[0]):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Windows drive path rejected: {raw_name!r}.",
                    )

                unix_mode = member.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Symbolic link rejected: {raw_name!r}.",
                    )

                target = destination.joinpath(*pure_path.parts).resolve()
                try:
                    target.relative_to(destination_resolved)
                except ValueError as exc:
                    raise GuidanceUpdateError(
                        "ZIP_SECURITY",
                        f"Archive entry escapes the extraction directory: {raw_name!r}.",
                    ) from exc

                validated_members.append(member)

            for member in validated_members:
                normalized_name = member.filename.replace("\\", "/")
                target = destination.joinpath(*PurePosixPath(normalized_name).parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except GuidanceUpdateError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise GuidanceUpdateError("ZIP_EXTRACT", f"Could not extract the ZIP archive: {exc}.") from exc

    message = f"Extracted {len(validated_members)} validated archive entries safely."
    if skipped_root_entries:
        message += f" Skipped {skipped_root_entries} harmless Dropbox root entry."
    log("ZIP_EXTRACT", message)


def should_ignore_path(relative_path: Path) -> bool:
    return any(part.casefold() in IGNORED_DIRECTORY_NAMES for part in relative_path.parts)


def locate_source_root(extracted_root: Path) -> Path:
    log("SOURCE_DISCOVERY", "Locating the four allowlisted TeX source files.")
    required = {note.source for note in NOTES}
    candidates: list[Path] = []

    directories = [extracted_root]
    directories.extend(path for path in extracted_root.rglob("*") if path.is_dir())

    for directory in directories:
        try:
            relative = directory.relative_to(extracted_root)
        except ValueError:
            continue
        if should_ignore_path(relative):
            continue
        if all((directory / filename).is_file() for filename in required):
            candidates.append(directory)

    if not candidates:
        found = sorted(
            path.name
            for path in extracted_root.rglob("*.tex")
            if not should_ignore_path(path.relative_to(extracted_root))
        )
        raise GuidanceUpdateError(
            "SOURCE_DISCOVERY",
            "Could not find one directory containing all four required TeX files. "
            f"Visible TeX files: {found or 'none'}.",
        )

    candidates.sort(key=lambda path: (len(path.relative_to(extracted_root).parts), str(path)))
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
        completed = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise GuidanceUpdateError(
            "DEPENDENCY",
            f"Pandoc was found but could not be executed: {exc}.",
        ) from exc

    version_line = completed.stdout.splitlines()[0] if completed.stdout else "pandoc"
    log("DEPENDENCY", f"Using {version_line}.")
    return executable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strip_tex_comments(tex_source: str) -> str:
    lines: list[str] = []
    for line in tex_source.splitlines():
        output: list[str] = []
        index = 0
        while index < len(line):
            if line[index] == "%":
                slash_count = 0
                back = index - 1
                while back >= 0 and line[back] == "\\":
                    slash_count += 1
                    back -= 1
                if slash_count % 2 == 0:
                    break
            output.append(line[index])
            index += 1
        lines.append("".join(output))
    return "\n".join(lines)


def normalize_tex_image_reference(reference: str) -> str | None:
    cleaned = reference.strip().replace("\\", "/")
    parsed = urllib.parse.urlsplit(cleaned)
    if parsed.scheme or parsed.netloc or cleaned.startswith("data:"):
        return None

    cleaned = urllib.parse.unquote(parsed.path).lstrip("./")
    if not cleaned:
        return None

    pure_path = PurePosixPath(cleaned)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None

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
            and not re.match(r"^width\s*:", declaration, re.IGNORECASE)
        ]
        declarations.append(f"width: {width_value}")
        replacement = f' style="{html.escape("; ".join(declarations), quote=True)}"'
        working = working[: style_match.start()] + replacement + working[style_match.end() :]
    else:
        working += f' style="width: {width_value};"'

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


def source_digest(source_path: Path, source_root: Path) -> str:
    tex_bytes = source_path.read_bytes()
    digest = hashlib.sha256()
    digest.update(f"template-version:{TEMPLATE_VERSION}\n".encode("utf-8"))
    digest.update(tex_bytes)

    try:
        tex_source = tex_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuidanceUpdateError(
            "SOURCE_READ",
            f"TeX source is not valid UTF-8: {source_path.name}.",
        ) from exc

    for reference in sorted(referenced_local_images(tex_source)):
        image_path = resolve_image_for_digest(reference, source_root)
        digest.update(f"\nimage:{reference}\n".encode("utf-8"))
        if image_path and image_path.is_file():
            digest.update(image_path.read_bytes())
        else:
            digest.update(b"MISSING")

    return digest.hexdigest()


def current_page_metadata(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None, None

    digest_match = re.search(
        r'<meta\s+name="guidance-source-digest"\s+content="([0-9a-f]{64})"',
        content,
        re.IGNORECASE,
    )
    date_match = re.search(
        r'<meta\s+name="guidance-updated"\s+content="(\d{4}-\d{2}-\d{2})"',
        content,
        re.IGNORECASE,
    )

    digest = digest_match.group(1) if digest_match else None
    updated = date_match.group(1) if date_match else None
    return digest, updated


def choose_update_date(existing_page: Path, new_digest: str) -> str:
    previous_digest, previous_date = current_page_metadata(existing_page)
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
        completed = subprocess.run(
            command,
            cwd=source_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            "Pandoc timed out after 180 seconds.",
            note.slug,
        ) from exc
    except OSError as exc:
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc could not be started: {exc}.",
            note.slug,
        ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or "No diagnostic output was produced."
        raise GuidanceUpdateError(
            "CONVERT",
            f"Pandoc exited with status {completed.returncode}: {stderr}",
            note.slug,
        )

    if not destination.is_file():
        raise GuidanceUpdateError(
            "CONVERT",
            "Pandoc reported success but did not create the expected HTML fragment.",
            note.slug,
        )

    try:
        fragment = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError(
            "CONVERT_READ",
            f"Could not read the converted HTML fragment: {exc}.",
            note.slug,
        ) from exc

    try:
        tex_source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError(
            "IMAGE_SCALE",
            f"Could not read the TeX source while applying image widths: {exc}.",
            note.slug,
        ) from exc

    fragment = apply_tex_image_widths(fragment, tex_source, note)
    validate_converted_fragment(fragment, note)
    return fragment.strip()


def visible_text_length(fragment: str) -> int:
    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        fragment,
        flags=re.IGNORECASE | re.DOTALL,
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    decoded = html.unescape(without_tags)
    return len(re.sub(r"\s+", " ", decoded).strip())


def validate_converted_fragment(fragment: str, note: Note) -> None:
    if not fragment.strip():
        raise GuidanceUpdateError("CONTENT_VALIDATE", "Converted HTML is empty.", note.slug)

    length = visible_text_length(fragment)
    if length < MINIMUM_CONVERTED_TEXT_LENGTH:
        raise GuidanceUpdateError(
            "CONTENT_VALIDATE",
            f"Converted content has only {length} visible characters; expected at least {MINIMUM_CONVERTED_TEXT_LENGTH}.",
            note.slug,
        )

    lowered = fragment.casefold()
    failure_markers = (
        "pandoc: error",
        "conversion failed",
        "traceback (most recent call last)",
    )
    for marker in failure_markers:
        if marker in lowered:
            raise GuidanceUpdateError(
                "CONTENT_VALIDATE",
                f"Converted HTML contains an error marker: {marker!r}.",
                note.slug,
            )


def copy_web_images(source_root: Path, staging_root: Path) -> set[str]:
    source_images = source_root / "images"
    destination_images = staging_root / "images"
    copied: set[str] = set()

    if not source_images.exists():
        log("IMAGES", "No top-level images directory was found; continuing without copied images.")
        destination_images.mkdir(parents=True, exist_ok=True)
        return copied

    if not source_images.is_dir():
        raise GuidanceUpdateError(
            "IMAGES",
            f"Expected {source_images} to be a directory.",
        )

    log("IMAGES", f"Copying web-compatible images from {source_images}.")
    destination_images.mkdir(parents=True, exist_ok=True)

    for source in source_images.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(source_root)
        if should_ignore_path(relative):
            continue
        if source.suffix.casefold() not in WEB_IMAGE_EXTENSIONS:
            continue

        destination = staging_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.add(relative.as_posix())

    log("IMAGES", f"Copied {len(copied)} web-compatible image file(s).")
    return copied


def normalize_image_reference(source: str) -> str | None:
    parsed = urllib.parse.urlsplit(source.strip())
    if parsed.scheme or parsed.netloc or source.startswith("data:"):
        return None

    path = urllib.parse.unquote(parsed.path).replace("\\", "/").lstrip("./")
    if not path:
        return None

    pure_path = PurePosixPath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        return None

    return pure_path.as_posix()


def collect_image_references(fragment: str, note: Note) -> set[str]:
    parser = ImageSourceParser()
    try:
        parser.feed(fragment)
    except Exception as exc:
        raise GuidanceUpdateError(
            "HTML_PARSE",
            f"Could not parse converted image references: {exc}.",
            note.slug,
        ) from exc

    references: set[str] = set()
    for source in parser.sources:
        normalized = normalize_image_reference(source)
        if normalized:
            references.add(normalized)
    return references


def create_case_alias(reference: str, staging_root: Path) -> str | None:
    expected = staging_root.joinpath(*PurePosixPath(reference).parts)
    if expected.is_file():
        return reference

    source = case_insensitive_file(staging_root, reference)
    if not source:
        return None

    expected.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, expected)
    log(
        "IMAGE_CASE",
        f"Created case-compatible image path {reference!r} from {source.relative_to(staging_root).as_posix()!r}.",
    )
    return reference


def validate_referenced_images(
    references_by_note: dict[str, set[str]],
    copied_images: set[str],
    staging_root: Path,
) -> None:
    copied_casefold = {path.casefold(): path for path in copied_images}

    for note_slug, references in references_by_note.items():
        missing: list[str] = []
        for reference in sorted(references):
            exact = staging_root.joinpath(*PurePosixPath(reference).parts)
            if exact.is_file():
                continue

            case_match = copied_casefold.get(reference.casefold())
            if case_match:
                source = staging_root.joinpath(*PurePosixPath(case_match).parts)
                exact.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, exact)
                log(
                    "IMAGE_CASE",
                    f"Created {reference!r} from case-variant {case_match!r}.",
                    note_slug,
                )
                continue

            if create_case_alias(reference, staging_root):
                continue
            missing.append(reference)

        if missing:
            raise GuidanceUpdateError(
                "IMAGE_REFERENCE",
                "Converted content references missing or unsupported image(s): "
                + ", ".join(missing),
                note_slug,
            )


def read_template(path: Path) -> str:
    log("TEMPLATE", f"Reading shared layout from {path}.")
    if not path.is_file():
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"Shared template does not exist: {path}.",
        )

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GuidanceUpdateError(
            "TEMPLATE",
            f"Could not read shared template: {exc}.",
        ) from exc


def extract_style_block(template: str) -> str:
    match = re.search(r"<style>(.*?)</style>", template, re.IGNORECASE | re.DOTALL)
    if not match:
        raise GuidanceUpdateError(
            "TEMPLATE",
            "Shared template does not contain an inline <style> block.",
        )
    return match.group(1).strip()


def guidance_css(_template_css: str) -> str:
    return '''    :root {
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

    .back-to-top {
      width: 2.55rem;
      height: 2.55rem;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      background: var(--accent-soft);
      border: 1px solid rgba(59, 90, 117, 0.25);
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


def back_to_top_html() -> str:
    return '''        <a href="#top" class="back-to-top" aria-label="Back to the top of the page" title="Back to top">
          <i class="fas fa-arrow-up" aria-hidden="true"></i>
        </a>'''


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
        '<body id="top">',
        note.title,
        'class="index-nav"',
        'href="../dissertation.html"',
        'class="guidance-content"',
        note.pdf_url.replace("&", "&amp;"),
        f'content="{digest}"',
        f'content="{updated}"',
        f"Information updated on {format_display_date(updated)}",
        'class="back-to-top"',
        'href="#top"',
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
        path.write_text(content, encoding="utf-8")
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


def file_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def directory_manifest(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}

    manifest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            manifest[path.relative_to(directory).as_posix()] = sha256_file(path)
    return manifest


def bundle_changed(staging_root: Path, guidance_dir: Path) -> bool:
    for note in NOTES:
        if file_bytes(staging_root / note.output) != file_bytes(guidance_dir / note.output):
            return True

    return directory_manifest(staging_root / "images") != directory_manifest(guidance_dir / "images")


def remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def publish_bundle(staging_root: Path, guidance_dir: Path) -> None:
    log("PUBLISH", "Publishing the complete guidance bundle transactionally.")
    guidance_dir.mkdir(parents=True, exist_ok=True)

    targets = [guidance_dir / note.output for note in NOTES]
    targets.append(guidance_dir / "images")

    incoming: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    token = uuid.uuid4().hex

    try:
        for target in targets:
            source = staging_root / target.name
            temporary = guidance_dir / f".{target.name}.next.{token}"
            remove_path(temporary)

            if source.is_dir():
                shutil.copytree(source, temporary)
            elif source.is_file():
                shutil.copy2(source, temporary)
            else:
                raise GuidanceUpdateError(
                    "PUBLISH_PREPARE",
                    f"Staged bundle is missing required target: {source}.",
                )
            incoming[target] = temporary

        for target in targets:
            if target.exists() or target.is_symlink():
                backup = guidance_dir / f".{target.name}.previous.{token}"
                remove_path(backup)
                os.replace(target, backup)
                backups[target] = backup

        for target in targets:
            os.replace(incoming[target], target)

    except Exception as exc:
        log("ROLLBACK", f"Publication failed; restoring previous guidance bundle: {exc}.")

        for target in reversed(targets):
            if target in backups:
                remove_path(target)
                backup = backups[target]
                if backup.exists() or backup.is_symlink():
                    os.replace(backup, target)
            else:
                remove_path(target)

        for temporary in incoming.values():
            remove_path(temporary)
        for backup in backups.values():
            remove_path(backup)

        if isinstance(exc, GuidanceUpdateError):
            raise
        raise GuidanceUpdateError(
            "PUBLISH",
            f"Could not publish the staged guidance bundle: {exc}.",
        ) from exc

    for backup in backups.values():
        remove_path(backup)
    for temporary in incoming.values():
        remove_path(temporary)

    log("PUBLISH", "Published all four pages and the image directory successfully.")


def main() -> int:
    repo_root, guidance_dir, supervision_template = repo_paths()

    try:
        pandoc = require_pandoc()
        template = read_template(supervision_template)
        template_css = extract_style_block(template)

        with tempfile.TemporaryDirectory(prefix="guidance-update-") as temporary_directory:
            workspace = Path(temporary_directory)
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
                log("NO_CHANGE", "The generated guidance bundle matches the published bundle.")
                return 0

            publish_bundle(staged, guidance_dir)

        log("COMPLETE", f"Guidance update completed successfully in {repo_root}.")
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
