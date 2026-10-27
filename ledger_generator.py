"""
TKIET Warananagar - Result Ledger Generator (core engine).

Converts a Warana/TKIET semester-results CSV export into the institute-style
A3 landscape PDF ledger. This module is framework-agnostic: it powers the
Streamlit app (app.py) and can also be used from the command line.

Usage (CLI):
    python ledger_generator.py results.csv -o ledger.pdf [-r reference.pdf]

Usage (Python):
    from ledger_generator import generate_ledger
    result = generate_ledger("results.csv")
    open("ledger.pdf", "wb").write(result["pdf"])
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SUBJECT_SHORT_NAMES = {
    "23UGPCCCH305T": "CH305-T",
    "23UGPCCCH304LP": "CH304-LP",
    "23UGPCCCH302LP": "CH302-LP",
    "23UGPCCCH301LP": "CH301-LP",
    "23UGCCPCH309T": "CH309-T",
    "23UGVEC1CH3081T": "VEC-CH308",
    "23UGMDM1ME307L": "MDM-ME307",
    "23UGEEC1CH3071L": "EEC-CH307",
    "23UGMDM1ET306L": "MDM-ET306",
    "25UGMDM1CB306": "MDM-CB306",
    "23UGMDM1CE306T": "MDM-CE306",
    "23UGMDM1CSE306": "MDM-CSE306",
    "25UGMDM1CS305": "MDM-CS305",
    "25UGMDM1EE305": "MDM-EE305",
    "23UGPCCCH305": "CH305",
    "23UGPCCCH304": "CH304",
    "23UGPCCCH303": "CH303",
    "23UGPCCCH302": "CH302",
    "23UGPCCCH301": "CH301",
}

COMPONENTS = [
    ("ESE", "FINAL ESE"),
    ("ISE", "ISE"),
    ("ISA", "ISA"),
    ("POE", "POE"),
    ("TW", "TW"),
    ("ORAL", "ORAL"),
    ("GRADE", "Grade"),
    ("GP", "Grade Points"),
    ("CREDIT", None),
]

TABLE_FONT_SIZE = 6.5

REQUIRED_COLUMNS = [
    "Username",
    "Full Name",
    "Semester Obtained Marks",
    "Semester Out Of Marks",
    "SGPA",
    "Semester Passing State",
]

DEFAULT_SUBTITLE = (
    "(An Autonomous Institute) Bachelors of Technology (Chemical Engg) "
    "(Part I Semester II) ESE HELD IN Summer 2023"
)

# Hard physical limit: the A3 page fits at most 10 student blocks below the
# letterhead (10 * 54pt + header ~253pt + footer margin ~ 842pt page height).
MAX_STUDENTS_PER_PAGE = 10

# --------------------------------------------------------------------------- #
# CSV parsing
# --------------------------------------------------------------------------- #


def _decode_bytes(data):
    """Decode raw CSV bytes, tolerating BOM / non-UTF8 encodings."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8-sig", errors="replace")


def read_source(csv_source):
    """Read student rows + detect populated subject columns.

    ``csv_source`` may be a filesystem path OR any file-like object
    (e.g. io.BytesIO, Streamlit's UploadedFile).
    """
    if hasattr(csv_source, "read"):
        raw = csv_source.read()
        text = raw if isinstance(raw, str) else _decode_bytes(raw)
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(row) for row in reader]
    else:
        with open(csv_source, "r", encoding="utf-8-sig", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]

    if not rows:
        raise ValueError("The CSV contains no student records.")

    headers = list(rows[0].keys())
    subject_pattern = re.compile(r"(.+?) - Subject Info - Total Credits$")
    candidates = []
    for header in headers:
        match = subject_pattern.match(header)
        if match:
            candidates.append(match.group(1))

    result_components = [item[1] for item in COMPONENTS if item[1] is not None]
    subjects = []
    for subject in candidates:
        if any(
            (row.get(f"{subject} - Result - {component}") or "").strip()
            for row in rows
            for component in result_components
        ):
            subjects.append(subject)
    return rows, subjects


def validate_csv(csv_source):
    """Return the list of required columns missing from the CSV (empty = OK)."""
    rows, _ = read_source(csv_source)
    headers = set(rows[0].keys())
    return [column for column in REQUIRED_COLUMNS if column not in headers]


# --------------------------------------------------------------------------- #
# Reference PDF logos
# --------------------------------------------------------------------------- #


def extract_logos(reference_source):
    """Extract the first two embedded images of the reference PDF.

    ``reference_source`` may be a path or file-like object.
    Returns ``(logos, warning)`` - logos is a list of BytesIO buffers and may
    be empty; warning is a short message or None. Never raises.
    """
    if reference_source is None:
        return [], None
    try:
        if hasattr(reference_source, "read"):
            data = reference_source.read()
            reader = PdfReader(io.BytesIO(data))
        else:
            if not os.path.exists(reference_source):
                return [], None
            reader = PdfReader(reference_source)
        images = list(reader.pages[0].images)
        logos = [io.BytesIO(image.data) for image in images[:2]]
        warning = None
        if not logos:
            warning = "No embedded images found on page 1 of the reference PDF - logos skipped."
        return logos, warning
    except Exception as exc:  # noqa: BLE001 - logos are optional by design
        return [], f"Reference PDF could not be read ({exc}) - logos skipped."


# --------------------------------------------------------------------------- #
# Text / value helpers
# --------------------------------------------------------------------------- #


def split_code(code):
    if len(code) <= 12:
        return [code]
    # Prefer a split before the discipline/course portion.
    options = [i for i in range(8, min(len(code), 13))]
    split_at = min(options, key=lambda i: abs((len(code) / 2) - i)) if options else len(code) // 2
    return [code[:split_at], code[split_at:]]


def fit_text(text, max_width, font="Helvetica", size=6.0, min_size=4.5):
    current = size
    while current > min_size and stringWidth(text, font, current) > max_width:
        current -= 0.2
    return current


def draw_centered(c, text, x, y, width, font="Helvetica", size=6, color=colors.black):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawCentredString(x + width / 2, y, text)


def wrap_words(text, max_width, font="Helvetica", size=6.5, max_lines=3):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if stringWidth(trial, font, size) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        tail = " ".join(lines[max_lines - 1 :])
        while tail and stringWidth(tail + "...", font, size) > max_width:
            tail = tail[:-1]
        kept[-1] = tail.rstrip() + "..."
        return kept
    return lines


def display_result(value):
    mapping = {
        "sem_all_clear": "ALL CLEAR",
        "sem_not_allclear": "NOT ALL CLEAR",
    }
    return mapping.get((value or "").strip(), (value or "").strip() or "--")


def percentage(obtained, out_of):
    try:
        numerator = Decimal((obtained or "").strip())
        denominator = Decimal((out_of or "").strip())
        if denominator == 0:
            return "--"
        value = (numerator * Decimal(100) / denominator).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return f"{value}%"
    except (InvalidOperation, ValueError):
        return "--"


def get_subject_value(row, subject, source_component):
    if source_component is None:
        # The export repeats configured credits for every elective option.
        # Show credits only where this student has actual result data for the subject.
        has_result = any(
            (row.get(f"{subject} - Result - {component}") or "").strip()
            for component in ["ISE", "ISA", "POE", "TW", "ORAL", "FINAL ESE", "Grade", "Grade Points"]
        )
        if not has_result:
            return "--"
        key = f"{subject} - Subject Info - Total Credits"
    else:
        key = f"{subject} - Result - {source_component}"
    value = (row.get(key) or "").strip()
    return value if value else "--"


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #


def draw_header(c, page_width, page_height, logos, page_number, page_count, subtitle=DEFAULT_SUBTITLE):
    # Hardcoded vector reconstruction of the supplied header (1575 x 315 reference).
    scale = page_width / 1575.0

    def x(px):
        return px * scale

    def y(px):
        return page_height - px * scale

    def centered(text, center_px, baseline_px, size, font="Helvetica"):
        c.setFillColor(colors.black)
        c.setFont(font, size)
        c.drawCentredString(x(center_px), y(baseline_px), text)

    if logos:
        c.saveState()
        c.setFillAlpha(0.42)
        c.drawImage(ImageReader(logos[0]), x(27), y(229), width=x(220), height=x(215), preserveAspectRatio=True, mask="auto")
        if len(logos) > 1:
            c.setFillAlpha(0.28)
            c.drawImage(ImageReader(logos[1]), x(1330), y(220), width=x(220), height=x(210), preserveAspectRatio=True, mask="auto")
        c.restoreState()

    centered("Tatyasaheb Kore Institute of Engineering & Technology, Warananagar", 790, 49, 21.2)
    centered(subtitle, 790, 85, 11.2)

    c.saveState()
    c.setDash(x(5), x(2))
    c.setLineWidth(0.65)
    for line_px in [104, 110, 171, 177, 314]:
        c.line(0, y(line_px), page_width, y(line_px))
    c.restoreState()

    centered("SEAT", 18, 136, TABLE_FONT_SIZE)
    centered("NO.", 18, 155, TABLE_FONT_SIZE)
    centered("GR NO.", 112, 128, TABLE_FONT_SIZE)
    centered("NAME", 112, 147, TABLE_FONT_SIZE)
    centered("Mother's Name", 112, 165, TABLE_FONT_SIZE)
    centered("PART I SEM I", 514, 146, TABLE_FONT_SIZE)
    centered("PART I SEM II", 1122, 146, TABLE_FONT_SIZE)
    centered("GRAND TOTAL", 1445, 146, TABLE_FONT_SIZE)
    centered("SEAT", 1545, 136, TABLE_FONT_SIZE)
    centered("NO.", 1545, 155, TABLE_FONT_SIZE)

    row_positions = [("ESE", 198), ("ISE", 229), ("ISA", 260), ("POE", 286), ("CREDIT", 309)]
    sem1_label_x = 202
    sem2_label_x = 793
    for label, row_px in row_positions:
        centered(label, sem1_label_x, row_px, TABLE_FONT_SIZE)
        centered(label, sem2_label_x, row_px, TABLE_FONT_SIZE)

    sem1_centers = [260, 314, 368, 422, 476, 530, 584, 630]
    sem2_centers = [833, 890, 947, 1004, 1061, 1118, 1175, 1232]
    sem1_values = {
        "ESE": ["60/24", "60/24", "--", "60/24", "60/24", "60/24", "--", "--"],
        "ISE": ["40/16", "40/16", "50/20", "40/16", "40/16", "40/16", "--", "--"],
        "ISA": ["25/10", "25/10", "25/10", "25/10", "25/10", "25/10", "50/20", "--"],
        "POE": ["--", "--", "25/10", "--", "--", "25/10", "--", "--"],
        "CREDIT": ["4", "4", "2", "3", "3", "3", "1", "0"],
    }
    sem2_values = {
        "ESE": ["60/24", "60/24", "60/24", "60/24", "--", "60/24", "--", "--"],
        "ISE": ["40/16", "40/16", "40/16", "40/16", "--", "40/16", "50/20", "--"],
        "ISA": ["25/10", "25/10", "25/10", "25/10", "50/20", "25/10", "25/10", "--"],
        "POE": ["--", "25/10", "--", "--", "--", "--", "25/10", "--"],
        "CREDIT": ["4", "3", "3", "3", "1", "4", "2", "0"],
    }
    for label, row_px in row_positions:
        for center_px, value in zip(sem1_centers, sem1_values[label]):
            centered(value, center_px, row_px, TABLE_FONT_SIZE)
        for center_px, value in zip(sem2_centers, sem2_values[label]):
            centered(value, center_px, row_px, TABLE_FONT_SIZE)

    summary_rows = [("TOTAL - 800", 217), ("PERCENTAGE", 240), ("RESULT", 263), ("SGPA", 286)]
    for text_value, baseline_px in summary_rows:
        centered(text_value, 705, baseline_px, TABLE_FONT_SIZE)
        centered(text_value, 1334, baseline_px, TABLE_FONT_SIZE)
    centered("1600", 1450, 218, TABLE_FONT_SIZE)
    centered("PERCENTAGE", 1450, 241, TABLE_FONT_SIZE)
    centered("RESULT", 1450, 264, TABLE_FONT_SIZE)
    centered("CGPA", 1450, 287, TABLE_FONT_SIZE)

    return y(315)


def draw_table_header(c, subjects, x0, y_top, widths, header_height):
    if header_height == 0:
        return y_top
    number_w, student_w, component_w, subject_w, summary_w, right_number_w = widths
    total_width = number_w + student_w + component_w + subject_w * len(subjects) + summary_w + right_number_w
    c.saveState()
    c.setDash(3, 1.4)
    c.setLineWidth(0.65)
    c.line(x0, y_top, x0 + total_width, y_top)
    c.line(x0, y_top - 4, x0 + total_width, y_top - 4)
    c.restoreState()

    subject_start = x0 + number_w + student_w + component_w
    subject_end = subject_start + subject_w * len(subjects)
    draw_centered(c, "SEMESTER III", subject_start, y_top - 17, subject_end - subject_start, "Helvetica", 7.2)
    draw_centered(c, "NO.", x0, y_top - 31, number_w, "Helvetica", 6.1)
    draw_centered(c, "STUDENT ID", x0 + number_w, y_top - 24, student_w, "Helvetica", 6.1)
    draw_centered(c, "NAME", x0 + number_w, y_top - 34, student_w, "Helvetica", 6.1)
    draw_centered(c, "ITEM", x0 + number_w + student_w, y_top - 31, component_w, "Helvetica", 5.8)

    x = subject_start
    for subject in subjects:
        lines = split_code(subject)
        line_y = y_top - 30
        for line in lines:
            size = fit_text(line, subject_w - 2, "Helvetica", 5.2, 4.0)
            draw_centered(c, line, x, line_y, subject_w, "Helvetica", size)
            line_y -= 6.2
        x += subject_w

    summary_lines = ["TOTAL - 800", "PERCENTAGE", "RESULT", "SGPA"]
    sy = y_top - 18
    for line in summary_lines:
        draw_centered(c, line, subject_end, sy, summary_w, "Helvetica", 5.7)
        sy -= 8.2
    draw_centered(c, "NO.", subject_end + summary_w, y_top - 31, right_number_w, "Helvetica", 6.1)

    bottom = y_top - header_height
    c.saveState()
    c.setDash(3, 1.4)
    c.setLineWidth(0.65)
    c.line(x0, bottom + 4, x0 + total_width, bottom + 4)
    c.line(x0, bottom, x0 + total_width, bottom)
    c.restoreState()
    return bottom


def draw_subject_shortnames(c, subjects, x0, y_top, widths):
    number_w, student_w, component_w, subject_w, summary_w, right_number_w = widths
    subject_start = x0 + number_w + student_w + component_w
    row_height = 15
    c.setFillColor(colors.black)
    x_pos = subject_start
    for subject in subjects:
        short_name = SUBJECT_SHORT_NAMES.get(subject, subject)
        size = fit_text(short_name, subject_w - 2, "Helvetica-Bold", TABLE_FONT_SIZE, 5.5)
        draw_centered(c, short_name, x_pos, y_top - 10.5, subject_w, "Helvetica-Bold", size)
        x_pos += subject_w

    total_width = number_w + student_w + component_w + subject_w * len(subjects) + summary_w + right_number_w
    c.saveState()
    c.setDash(3, 1.5)
    c.setLineWidth(0.55)
    c.line(0, y_top - row_height, c._pagesize[0], y_top - row_height)
    c.restoreState()
    return y_top - row_height


def draw_student_block(c, row, number, subjects, x0, y_top, widths, component_height):
    number_w, student_w, component_w, subject_w, summary_w, right_number_w = widths
    block_height = component_height * len(COMPONENTS)
    total_width = number_w + student_w + component_w + subject_w * len(subjects) + summary_w + right_number_w
    y_bottom = y_top - block_height

    c.saveState()
    c.setDash(3, 1.5)
    c.setLineWidth(0.55)
    c.line(0, y_bottom, c._pagesize[0], y_bottom)
    c.restoreState()

    x_number_end = x0 + number_w
    x_student_end = x_number_end + student_w
    x_component_end = x_student_end + component_w
    x_subjects_end = x_component_end + subject_w * len(subjects)
    x_summary_end = x_subjects_end + summary_w
    # Align the left serial/seat number directly below the hardcoded "SEAT NO." heading.
    left_seat_center = c._pagesize[0] * (18.0 / 1575.0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", TABLE_FONT_SIZE)
    c.drawCentredString(left_seat_center, y_top - block_height / 2 - 2, str(number))
    draw_centered(c, str(number), x_summary_end, y_top - block_height / 2 - 2, right_number_w, "Helvetica", TABLE_FONT_SIZE)

    seat_number = (row.get("Username") or "--").strip() or "--"
    name = (row.get("Full Name") or "").strip() or "--"
    name_lines = wrap_words(name, student_w - 4, "Helvetica", TABLE_FONT_SIZE, 4)
    student_lines = [(seat_number, "Helvetica-Bold", TABLE_FONT_SIZE)] + [
        (line, "Helvetica", TABLE_FONT_SIZE) for line in name_lines
    ]
    line_gap = 8.0
    middle_y = y_top - block_height / 2
    first_baseline = middle_y + ((len(student_lines) - 1) * line_gap) / 2 - 2
    student_center_x = x_number_end + student_w / 2
    for line_index, (line, font, size) in enumerate(student_lines):
        c.setFont(font, size)
        c.drawCentredString(student_center_x, first_baseline - line_index * line_gap, line)

    for component_index, (label, source_component) in enumerate(COMPONENTS):
        cell_top = y_top - component_index * component_height
        cell_bottom = cell_top - component_height
        if label == "ESE":
            label_baseline = cell_bottom + 0.3
        elif label == "ISE":
            label_baseline = cell_bottom + 1.3
        else:
            label_baseline = cell_bottom + 1.7
        draw_centered(c, label, x_student_end, label_baseline, component_w, "Helvetica", TABLE_FONT_SIZE)

        x = x_component_end
        for subject in subjects:
            value = get_subject_value(row, subject, source_component)
            value_color = colors.HexColor("#B00020") if label == "GRADE" and value.upper() == "F" else colors.black
            size = fit_text(value, subject_w - 2.2, "Helvetica", TABLE_FONT_SIZE, 5.5)
            draw_centered(c, value, x, cell_bottom + 1.6, subject_w, "Helvetica", size, value_color)
            x += subject_w

    result = display_result(row.get("Semester Passing State"))
    result_color = colors.HexColor("#B00020") if result == "NOT ALL CLEAR" else colors.black
    summary_lines = [
        ((row.get("Semester Obtained Marks") or "").strip() or "--", colors.black),
        (percentage(row.get("Semester Obtained Marks"), row.get("Semester Out Of Marks")), colors.black),
        (result, result_color),
        ((row.get("SGPA") or "").strip() or "--", colors.black),
    ]
    summary_x = x_subjects_end
    summary_y = y_top - 10
    for value, color in summary_lines:
        size = fit_text(value, summary_w - 6, "Helvetica", TABLE_FONT_SIZE, 5.5)
        c.setFillColor(color)
        c.setFont("Helvetica", size)
        c.drawCentredString(summary_x + summary_w / 2, summary_y, value)
        summary_y -= 10
    c.setFillColor(colors.black)
    return y_bottom


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def generate_ledger(
    csv_source,
    reference_pdf_source=None,
    subtitle=DEFAULT_SUBTITLE,
    students_per_page=MAX_STUDENTS_PER_PAGE,
):
    """Build the A3 ledger from a CSV export.

    Parameters
    ----------
    csv_source : str | file-like
        Path to (or file object with) the Warana results CSV export.
    reference_pdf_source : str | file-like | None
        Optional institute reference PDF; the first two images on its page 1
        are used as letterhead logos.
    subtitle : str
        Second line of the letterhead (exam/session description).
    students_per_page : int
        Student blocks per page (4..10).

    Returns
    -------
    dict with keys: ``pdf`` (bytes), ``students``, ``subjects`` (list),
    ``pages`` (int), ``warnings`` (list of str).
    """
    rows, subjects = read_source(csv_source)
    if not subjects:
        raise ValueError("No populated subject result columns were found in the CSV.")

    try:
        students_per_page = int(students_per_page)
    except (TypeError, ValueError):
        students_per_page = MAX_STUDENTS_PER_PAGE
    students_per_page = max(4, min(students_per_page, MAX_STUDENTS_PER_PAGE))

    logos, logo_warning = extract_logos(reference_pdf_source)

    page_width, page_height = landscape(A3)
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height), pageCompression=1)
    c.setTitle("TKIET Result Ledger - ESE Clearance Corrected")
    c.setAuthor("Tatyasaheb Kore Institute of Engineering & Technology")
    c.setSubject("Result ledger generated from supplied CSV data")

    page_count = (len(rows) + students_per_page - 1) // students_per_page
    left_margin = 23
    right_margin = 23
    table_width = page_width - left_margin - right_margin
    number_w = 22
    student_w = 110
    component_w = 31
    summary_w = 118
    right_number_w = 22
    subject_w = (
        table_width - number_w - student_w - component_w - summary_w - right_number_w
    ) / len(subjects)
    widths = (number_w, student_w, component_w, subject_w, summary_w, right_number_w)
    header_height = 0
    component_height = 6.0

    for page_index in range(page_count):
        table_top = draw_header(
            c, page_width, page_height, logos, page_index + 1, page_count, subtitle
        )
        current_y = draw_table_header(c, subjects, left_margin, table_top, widths, header_height)
        current_y = draw_subject_shortnames(c, subjects, left_margin, current_y, widths)
        start = page_index * students_per_page
        end = min(start + students_per_page, len(rows))
        for row_number in range(start, end):
            current_y = draw_student_block(
                c,
                rows[row_number],
                row_number + 1,
                subjects,
                left_margin,
                current_y,
                widths,
                component_height,
            )

        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.black)
        c.drawRightString(page_width - right_margin - right_number_w, 31, f"Page {page_index + 1} of {page_count}")
        c.setFillColor(colors.black)
        c.showPage()

    c.save()
    buffer.seek(0)

    warnings = []
    if logo_warning:
        warnings.append(logo_warning)

    return {
        "pdf": buffer.getvalue(),
        "students": len(rows),
        "subjects": subjects,
        "pages": page_count,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Command-line interface
# --------------------------------------------------------------------------- #


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate the TKIET A3 result ledger PDF from a Warana CSV export."
    )
    parser.add_argument("csv_path", help="Path to the results CSV export")
    parser.add_argument("-o", "--output", default="TKIET_Result_Ledger.pdf", help="Output PDF path")
    parser.add_argument(
        "-r", "--reference-pdf", default=None,
        help="Optional institute reference PDF (logos extracted from page 1)",
    )
    parser.add_argument("--subtitle", default=DEFAULT_SUBTITLE, help="Letterhead second line")
    parser.add_argument("--per-page", type=int, default=MAX_STUDENTS_PER_PAGE, help="Students per page (4-10)")
    args = parser.parse_args(argv)

    result = generate_ledger(
        args.csv_path,
        reference_pdf_source=args.reference_pdf,
        subtitle=args.subtitle,
        students_per_page=args.per_page,
    )
    with open(args.output, "wb") as handle:
        handle.write(result["pdf"])

    print(f"OUTPUT={args.output}")
    print(f"STUDENTS={result['students']}")
    print(f"SUBJECTS={len(result['subjects'])}")
    print(f"PAGES={result['pages']}")


if __name__ == "__main__":
    main()
