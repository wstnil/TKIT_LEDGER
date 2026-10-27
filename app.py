"""
TKIET Result Ledger Studio - Streamlit front end.

Drag & drop a Warana/TKIET semester-results CSV export and download the
institute-style A3 landscape PDF ledger. All processing happens in memory.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import io
import os
import re
import traceback

import pypdfium2 as pdfium
import streamlit as st
import pandas as pd

from ledger_generator import (
    DEFAULT_SUBTITLE,
    MAX_STUDENTS_PER_PAGE,
    REQUIRED_COLUMNS,
    SUBJECT_SHORT_NAMES,
    generate_ledger,
    read_source,
)

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "sample_data", "sample_export.csv")

st.set_page_config(
    page_title="TKIET Result Ledger Studio",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------------------------------- #
# Custom modern UI (CSS)
# --------------------------------------------------------------------------- #

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp, button, input {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
.stApp {
    background:
        radial-gradient(1100px 520px at 88% -10%, rgba(99,102,241,.16), transparent 60%),
        radial-gradient(900px 520px at -10% 110%, rgba(139,92,246,.13), transparent 55%),
        #f7f8fd;
}
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.4rem !important; max-width: 1220px; }

/* ---------- hero ---------- */
.hero-title {
    font-size: 2.5rem; font-weight: 800; line-height: 1.12; letter-spacing: -0.02em;
    background: linear-gradient(90deg, #4f46e5, #7c3aed 55%, #a855f7);
    -webkit-background-clip: text; background-clip: text; color: transparent;
    margin-bottom: .25rem;
}
.hero-sub { color: #475569; font-size: 1.02rem; }
.chip {
    display: inline-block; padding: .3rem .85rem; margin: .5rem .3rem 0 0;
    border-radius: 999px; font-size: .76rem; font-weight: 600;
    background: #eef2ff; color: #4338ca; border: 1px solid #c7d2fe;
}

/* ---------- cards ---------- */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff;
    border: 1px solid #e2e8f0 !important;
    border-radius: 18px;
    box-shadow: 0 10px 30px rgba(15,23,42,.06);
}
.panel {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 18px;
    padding: 1.15rem 1.35rem; box-shadow: 0 10px 30px rgba(15,23,42,.06);
}
.panel-soft {
    background: linear-gradient(180deg, #fbfcff, #f4f6ff);
    border: 1px solid #e2e8f0; border-radius: 16px;
    padding: .95rem 1.1rem;
}
.card-title { font-weight: 700; font-size: 1.02rem; color: #0f172a; margin-bottom: .35rem; }
.muted { color: #64748b; font-size: .86rem; }

/* ---------- drag & drop zone ---------- */
[data-testid="stFileUploaderDropzone"] {
    border: 1.6px dashed #a5b4fc; border-radius: 16px;
    background: linear-gradient(180deg, #fbfcff, #f3f5ff);
    transition: all .2s ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: #6366f1; background: #eef2ff;
    box-shadow: 0 8px 22px rgba(99,102,241,.16);
}
[data-testid="stFileUploaderDropzone"] [data-testid="stFileUploaderDropzoneMessage"] {
    color: #475569;
}

/* ---------- buttons ---------- */
div.stButton > button, div.stDownloadButton > button {
    border-radius: 12px; font-weight: 600; border: none;
    transition: all .2s ease;
}
div.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: #fff; box-shadow: 0 8px 20px rgba(99,102,241,.32);
}
div.stButton > button:hover, div.stDownloadButton > button:hover {
    transform: translateY(-2px); filter: brightness(1.06);
}
div.stDownloadButton > button {
    background: linear-gradient(135deg, #059669, #10b981);
    color: #fff; box-shadow: 0 8px 20px rgba(16,185,129,.28);
}

/* ---------- metrics & previews ---------- */
div[data-testid="stMetric"] {
    background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: .85rem 1rem; box-shadow: 0 6px 18px rgba(15,23,42,.05);
}
[data-testid="stImage"], [data-testid="stImage"] img {
    border-radius: 12px; overflow: hidden;
    border: 1px solid #e2e8f0; box-shadow: 0 6px 18px rgba(15,23,42,.07);
}
[data-testid="stExpander"] { border-radius: 14px; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { background: #fbfcff; border-right: 1px solid #e2e8f0; }
.step-line { margin: .18rem 0; color: #334155; font-size: .9rem; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# UI helpers
# --------------------------------------------------------------------------- #


def render_hero():
    st.markdown(
        """
        <div class="panel" style="margin-bottom:1.1rem;">
            <div class="hero-title">TKIET Result Ledger Studio</div>
            <div>
                <span class="chip">&#9889; Drag &amp; drop</span>
                <span class="chip">&#128196; A3 vector PDF</span>
                <span class="chip">&#127891; Warana ledger format</span>
                <span class="chip">&#128274; Runs 100% in-app</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def safe_filename_stem(upload_name, fallback="Sample"):
    stem = os.path.splitext(os.path.basename(upload_name or ""))[0]
    stem = re.sub(r"^\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_export_", "", stem)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return stem or fallback


def result_state(row):
    state = (row.get("Semester Passing State") or "").strip()
    return "NOT ALL CLEAR" if state == "sem_not_allclear" else "ALL CLEAR"


def render_data_preview(rows, subjects):
    col1, col2, col3 = st.columns(3)
    not_clear = sum(1 for row in rows if result_state(row) == "NOT ALL CLEAR")
    col1.metric("Students detected", len(rows))
    col2.metric("Subjects detected", len(subjects))
    col3.metric("Not all clear", not_clear)

    chips = " ".join(
        f'<span class="chip">{SUBJECT_SHORT_NAMES.get(s, s)}</span>' for s in subjects
    )
    st.markdown(chips, unsafe_allow_html=True)

    with st.expander("Preview first 5 students"):
        frame = pd.DataFrame(
            [
                {
                    "Seat No": (row.get("Username") or "").strip(),
                    "Name": (row.get("Full Name") or "").strip(),
                    "Marks": (row.get("Semester Obtained Marks") or "").strip(),
                    "Out of": (row.get("Semester Out Of Marks") or "").strip(),
                    "SGPA": (row.get("SGPA") or "").strip(),
                    "Result": result_state(row),
                }
                for row in rows[:5]
            ]
        )
        st.dataframe(frame, hide_index=True, use_container_width=True)


def render_pdf_previews(pdf_bytes, max_pages=2):
    try:
        document = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
        count = min(max_pages, len(document))
        if count == 0:
            return
        cols = st.columns(count)
        for index in range(count):
            bitmap = document[index].render(scale=1.15)
            with cols[index]:
                st.image(bitmap.to_pil(), caption=f"Page {index + 1} preview", use_container_width=True)
        if len(document) > max_pages:
            st.caption(f"Showing first {max_pages} of {len(document)} pages - the download contains all pages.")
    except Exception:  # noqa: BLE001 - preview is best-effort, download still works
        st.caption("Preview unavailable, but the PDF download below is complete.")


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown("### 🧭 How to use")
    st.markdown(
        """
        <div class="step-line"><b>1.</b> Drag &amp; drop the results <b>CSV</b> export</div>
        <div class="step-line"><b>2.</b> Optionally add the institute <b>reference PDF</b> (logos)</div>
        <div class="step-line"><b>3.</b> Tune the header text in <i>Advanced options</i></div>
        <div class="step-line"><b>4.</b> Hit <b>Generate</b> and download the A3 ledger</div>
        """,
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------- #
# Main layout
# --------------------------------------------------------------------------- #

render_hero()

main_col, side_col = st.columns([1.65, 1], gap="large")

with main_col:
    with st.container(border=True):
        st.markdown('<div class="card-title">📄 1 &middot; Upload the results export</div>', unsafe_allow_html=True)
        csv_file = st.file_uploader(
            "Drag & drop the CSV export here (or click to browse)",
            type=["csv"],
            help="Warana/TKIET semester-results CSV export (UTF-8).",
        )
        use_sample = st.checkbox("No file handy? Use the bundled sample export")

        csv_bytes = None
        csv_name = None
        if csv_file is not None:
            csv_bytes = csv_file.getvalue()
            csv_name = csv_file.name
        elif use_sample:
            if os.path.exists(SAMPLE_CSV):
                with open(SAMPLE_CSV, "rb") as handle:
                    csv_bytes = handle.read()
                csv_name = "sample_export.csv"
            else:
                st.error("Sample file missing from the repo (sample_data/sample_export.csv).")

        rows, subjects, missing = [], [], []
        if csv_bytes is not None:
            try:
                rows, subjects = read_source(io.BytesIO(csv_bytes))
                missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read this CSV: {exc}")
                rows, subjects = [], []

        if missing:
            st.error("CSV is missing required columns: " + ", ".join(f"`{c}`" for c in missing))
        elif rows:
            render_data_preview(rows, subjects)

        st.markdown('<div class="card-title" style="margin-top:.6rem;">📌 2 &middot; Optional logos</div>', unsafe_allow_html=True)
        ref_file = st.file_uploader(
            "Reference institute PDF (logos are pulled from its first page)",
            type=["pdf"],
            help="e.g. CHEM_SEM_I&II_S_23.pdf. Skip it to generate without logos.",
        )

        with st.expander("🔧 Advanced options"):
            subtitle = st.text_input(
                "Letterhead second line",
                value=DEFAULT_SUBTITLE,
                help="Shown under the institute name on every page.",
            )
            per_page = st.slider(
                "Students per page", min_value=4, max_value=MAX_STUDENTS_PER_PAGE,
                value=MAX_STUDENTS_PER_PAGE, step=1,
                help="The A3 page fits at most 10 student blocks below the letterhead.",
            )

        generate_clicked = st.button(
            "⚙️ Generate ledger PDF", type="primary", use_container_width=True
        )

        if generate_clicked:
            if csv_bytes is None:
                st.warning("Upload a CSV first - or tick the sample checkbox.")
            elif missing:
                st.error("Fix the missing columns above, then generate again.")
            else:
                with st.spinner("Composing the A3 ledger..."):
                    try:
                        ref_bytes = ref_file.getvalue() if ref_file is not None else None
                        result = generate_ledger(
                            io.BytesIO(csv_bytes),
                            reference_pdf_source=io.BytesIO(ref_bytes) if ref_bytes else None,
                            subtitle=subtitle,
                            students_per_page=per_page,
                        )
                        stem = safe_filename_stem(csv_name)
                        st.session_state["ledger"] = result
                        st.session_state["ledger_name"] = f"TKIET_Ledger_{stem}.pdf"
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.pop("ledger", None)
                        st.error(f"Generation failed: {exc}")
                        with st.expander("Technical details"):
                            st.code(traceback.format_exc())

with side_col:
    with st.container(border=True):
        st.markdown('<div class="card-title">📨 What you get</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="muted">
            One print-ready <b>A3 landscape</b> PDF in the Warana ledger format:
            institute letterhead, one block per student with ESE / ISE / ISA / POE /
            TW / ORAL / grade / credit rows, plus totals, percentage, result state
            and SGPA. Failed subjects and <i>NOT ALL CLEAR</i> states are red.
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        st.markdown('<div class="card-title">🩹 Troubleshooting</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="muted">
            &bull; <b>Missing columns error?</b> Use the CSV exactly as exported by the result portal.<br>
            &bull; <b>Cells show “--”?</b> The student has no marks recorded for that subject/elective.<br>
            &bull; <b>No logos?</b> Logos need the optional reference PDF upload.<br>
            &bull; <b>Weird characters?</b> Re-export the CSV as UTF-8.
            </div>
            """,
            unsafe_allow_html=True,
        )

# --------------------------------------------------------------------------- #
# Result card
# --------------------------------------------------------------------------- #

ledger = st.session_state.get("ledger")
if ledger:
    with st.container(border=True):
        st.markdown(
            '<div class="card-title">✅ Ledger ready &mdash; 3 &middot; Preview &amp; download</div>',
            unsafe_allow_html=True,
        )
        for warning in ledger.get("warnings", []):
            st.warning(warning)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Students", ledger["students"])
        m2.metric("Subjects", len(ledger["subjects"]))
        m3.metric("Pages", ledger["pages"])
        m4.metric("File size", f"{len(ledger['pdf']) / 1024:.0f} KB")

        render_pdf_previews(ledger["pdf"])

        st.download_button(
            "⬇️ Download ledger PDF",
            data=ledger["pdf"],
            file_name=st.session_state.get("ledger_name", "TKIET_Ledger.pdf"),
            mime="application/pdf",
            use_container_width=True,
        )
else:
    with st.container(border=True):
        st.markdown(
            """
            <div class="panel-soft" style="text-align:center;">
                <div style="font-size:1.6rem;">&#128581;</div>
                <div class="card-title">Drop a CSV above to get started</div>
                <div class="muted">
                    The generated ledger preview will appear here &mdash;
                    along with page thumbnails and a one-click download.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
