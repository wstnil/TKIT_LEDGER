# 🎓 TKIET Result Ledger Studio

A modern **Streamlit** web app that turns Warana/TKIET semester-results **CSV exports**
into the institute-style **A3 landscape PDF ledger** — with **drag & drop**, in-memory
processing, live page previews and a one-click download.

Built for [Tatyasaheb Kore Institute of Engineering & Technology, Warananagar](https://tkietwarana.ac.in/).

---

## ✨ Features

| | |
|---|---|
| 🖱️ **Drag & drop** | Drop the CSV export straight onto the upload zone |
| 📄 **A3 vector PDF** | Institute letterhead, per-student ESE/ISE/ISA/POE/TW/ORAL/grade/credit rows |
| 🎨 **Modern UI/UX** | Glass cards, gradient hero, hover animations, Inter typography |
| 🖼️ **Live previews** | Page thumbnails rendered in-app before you download |
| 🧾 **Smart columns** | Auto-detects populated subjects (incl. 2025-regulation electives); empty electives show `--` |
| 🚨 **At-a-glance status** | Failed grades & `NOT ALL CLEAR` states highlighted in red |
| 🖼️ **Optional logos** | Upload the institute reference PDF — logos are extracted automatically |
| 🔒 **Private** | Everything is processed in memory; no files are stored on the server |
| 🧪 **Sample data** | One checkbox runs the whole flow on a bundled sample export |

---

## 🚀 Run locally

```bash
# 1. (optional) create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. start the app
streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## ☁️ Deploy to Streamlit Community Cloud (free)

1. **Push this folder to a GitHub repository**
   ```bash
   cd tkiet-ledger-app
   git init                       # skip if the repo already ships a .git
   git add .
   git commit -m "TKIET Result Ledger Studio"
   git branch -M main
   git remote add origin https://github.com/<your-username>/tkiet-ledger-app.git
   git push -u origin main
   ```
2. Open **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
3. Click **Create app** (or *New app*).
4. Pick your **repository**, branch **`main`**, main file **`app.py`**.
5. Click **Deploy** — that's it. No environment variables, no secrets, no extra config.

> The repo is deliberately dependency-light (`requirements.txt` only, no system
> packages), so Streamlit Cloud builds cleanly on the default Python image.

---

## 📖 Using the app

1. **Upload** — drag & drop the CSV export (the file downloaded from the results
   portal, e.g. `2026_10_27_..._export_TKIET_..._SEM3_2024.csv`).
   The app immediately validates the required columns and shows a data summary.
2. **Optional logos** — upload the institute reference PDF (e.g. `CHEM_SEM_I&II_S_23.pdf`);
   the first two images on its first page become the letterhead logos.
   Skip it to generate without logos.
3. **Advanced options** — edit the letterhead second line (exam/session description)
   and choose students per page (4–10; the A3 page fits 10 max).
4. **Generate & download** — page previews appear in-app; the download button gives
   you the full vector PDF.

### Required CSV columns

`Username`, `Full Name`, `Semester Obtained Marks`, `Semester Out Of Marks`,
`SGPA`, `Semester Passing State` — plus the standard
`<subject> - Subject Info - Total Credits` / `<subject> - Result - …` column groups.

---

## 🛠️ Command-line interface (no GUI)

```bash
python ledger_generator.py results.csv -o ledger.pdf
python ledger_generator.py results.csv -o ledger.pdf -r reference.pdf --per-page 10
```

---

## 📁 Project structure

```
tkiet-ledger-app/
├── app.py                  # Streamlit UI (drag & drop, previews, download)
├── ledger_generator.py     # Framework-agnostic PDF engine (+ CLI)
├── requirements.txt        # Python dependencies
├── .streamlit/
│   └── config.toml         # App theme (indigo / violet)
├── sample_data/
│   ├── sample_export.csv   # Real-format sample export (20 students)
│   └── sample_output.pdf   # Example ledger generated from it
└── README.md
```

---

## ⚙️ Customisation

| What | Where |
|---|---|
| Subject short names (column headers) | `SUBJECT_SHORT_NAMES` in `ledger_generator.py` |
| Letterhead line 1 (institute name) | `draw_header()` in `ledger_generator.py` |
| Default letterhead line 2 | `DEFAULT_SUBTITLE` in `ledger_generator.py` |
| App colors / theme | `.streamlit/config.toml` and the `CSS` block in `app.py` |

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| "Missing required columns" | Upload the CSV exactly as exported by the results portal |
| Cells show `--` | The student has no marks recorded for that subject/elective — expected |
| No logos in the PDF | Logos need the optional reference-PDF upload |
| Wrong characters | Re-export the CSV as UTF-8 |
| Cloud build issues | Make sure `requirements.txt` is committed at the repo root |

---

## 🔒 Privacy note

`sample_data/` ships with a **real-format sample export** so the deployed app can be
tested instantly. If you plan to make your GitHub repository **public**, replace
`sample_data/sample_export.csv` and `sample_data/sample_output.pdf` with anonymised
copies first.
