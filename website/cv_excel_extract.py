import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl


DEFAULT_EXCEL_URL = (
    "https://www.dropbox.com/scl/fi/z0dbe74ywv0ws3yw4l8gt/"
    "CV_Arthur_Galichere_excel.xlsx"
    "?rlkey=l736567qyln1ql0s7ws2nz21q&st=vx9y8fjx&dl=1"
)

EXPECTED_SECTIONS = {
    "Employment",
    "Professional Development",
    "Conference Paper Reviewer",
    "Teaching Awards and Qualifications",
    "Teaching Experience",
    "Additional Teaching and Supervisory Experience",
    "Academic Leadership and Development",
    "Administrative and Collegial Experience",
    "Research Presentations",
}

FIELDS = ("role", "institution", "date", "details", "category", "other_details")


def cell_text(value):
    return "" if value is None else str(value).strip()


def download_workbook(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Arthur-Galichere-CV-Updater/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download the Excel workbook: {exc}") from exc

    if len(content) < 1_000:
        raise RuntimeError("The downloaded Excel workbook is unexpectedly small.")

    try:
        return openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise RuntimeError(f"The downloaded file is not a readable Excel workbook: {exc}") from exc


def read_sheet(sheet):
    section_title = cell_text(sheet.cell(row=1, column=1).value) or sheet.title

    header_map = {
        cell_text(sheet.cell(row=2, column=column).value).lower(): column
        for column in range(1, sheet.max_column + 1)
        if cell_text(sheet.cell(row=2, column=column).value)
    }
    column_map = {field: header_map.get(field) for field in FIELDS}

    if not column_map["role"]:
        raise ValueError(f"Worksheet '{sheet.title}' has no 'role' column.")

    items = []
    for row in range(3, sheet.max_row + 1):
        values = {
            field: cell_text(sheet.cell(row=row, column=column).value) if column else ""
            for field, column in column_map.items()
        }

        if not any(values.values()):
            continue

        details = values["details"]
        if values["other_details"]:
            details = "\n".join(filter(None, (details, values["other_details"])))

        items.append(
            {
                "role": values["role"],
                "institution": values["institution"],
                "date": values["date"],
                "details": details,
                "category": values["category"],
            }
        )

    return section_title, items


def group_teaching_experience(section_title, items):
    institutions = {}

    for item in items:
        institution = item.get("institution") or "Other"
        category = item.get("category") or "General"
        institutions.setdefault(institution, {}).setdefault(category, []).append(item)

    subsections = []
    for institution, categories in institutions.items():
        institution_items = []
        for category, category_items in categories.items():
            institution_items.append({"isFormatHeader": True, "role": category})
            institution_items.extend(category_items)
        subsections.append({"title": institution, "items": institution_items})

    return {"title": section_title, "subsections": subsections}


def group_additional_teaching(section_title, items):
    categories = {}

    for item in items:
        category = item.get("category") or "General"
        categories.setdefault(category, []).append(item)

    return {
        "title": section_title,
        "subsections": [
            {"title": category, "items": category_items}
            for category, category_items in categories.items()
        ],
    }


def build_sections(workbook):
    sections = []

    for sheet in workbook.worksheets:
        section_title, items = read_sheet(sheet)
        if not items:
            raise ValueError(f"Worksheet '{sheet.title}' contains no CV records.")

        section_lower = section_title.casefold()
        if section_lower == "teaching experience":
            section = group_teaching_experience(section_title, items)
        elif section_lower == "additional teaching and supervisory experience":
            section = group_additional_teaching(section_title, items)
        else:
            section = {"title": section_title, "items": items}

        sections.append(section)

    found_sections = {section["title"] for section in sections}
    missing_sections = EXPECTED_SECTIONS - found_sections
    if missing_sections:
        missing = ", ".join(sorted(missing_sections))
        raise ValueError(f"The workbook is missing expected sections: {missing}")

    return sections


def read_previous_data(output_path):
    if not output_path.is_file():
        return None

    try:
        with output_path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return data if isinstance(data, dict) else None


def choose_update_date(new_sections, previous_data):
    if previous_data and previous_data.get("sections") == new_sections:
        previous_date = previous_data.get("last_updated")
        try:
            date.fromisoformat(previous_date)
            return previous_date
        except (TypeError, ValueError):
            pass

    return date.today().isoformat()


def validate_cv_data(data):
    try:
        date.fromisoformat(data.get("last_updated", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("CV data must contain a valid ISO 'last_updated' date.") from exc

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("CV data must contain a non-empty 'sections' list.")

    for section in sections:
        if not isinstance(section, dict) or not section.get("title"):
            raise ValueError("Every CV section must have a title.")

        entries = section.get("items", section.get("subsections"))
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Section '{section['title']}' contains no entries.")


def write_json_atomically(data, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(data, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)

        with temporary_path.open(encoding="utf-8") as file:
            validate_cv_data(json.load(file))

        os.replace(temporary_path, output_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main():
    base_dir = Path(__file__).resolve().parent
    output_path = base_dir / "cv.json"
    excel_url = os.environ.get("CV_EXCEL_URL", DEFAULT_EXCEL_URL).strip()

    if not excel_url:
        raise RuntimeError("CV_EXCEL_URL is empty.")

    previous_data = read_previous_data(output_path)
    workbook = download_workbook(excel_url)
    try:
        sections = build_sections(workbook)
    finally:
        workbook.close()

    cv_data = {
        "last_updated": choose_update_date(sections, previous_data),
        "sections": sections,
    }

    validate_cv_data(cv_data)
    write_json_atomically(cv_data, output_path)
    print(
        f"Updated {output_path} with {len(cv_data['sections'])} sections. "
        f"Information date: {cv_data['last_updated']}."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CV update failed: {exc}", file=sys.stderr)
        raise
