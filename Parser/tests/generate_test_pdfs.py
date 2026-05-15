"""
tests/generate_test_pdfs.py — Generate 5 synthetic lab report PDFs for testing.

  PDF 1: Clean CBC — all values normal
  PDF 2: Multiple abnormals — low Hb, high WBC, low platelets
  PDF 3: Critical value — K+ 6.8 mEq/L (hyperkalaemia), Creatinine 5.8
  PDF 4: Urine Routine & Microscopy — non-blood
  PDF 5: Thyroid Panel + Lipid Profile

Run from task1j/:
  python tests/generate_test_pdfs.py
"""

import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "sample_reports")
os.makedirs(OUTPUT_DIR, exist_ok=True)

styles = getSampleStyleSheet()
title_style = ParagraphStyle("LabTitle", fontSize=14, alignment=TA_CENTER, fontName="Helvetica-Bold")
subtitle_style = ParagraphStyle("LabSubtitle", fontSize=10, alignment=TA_CENTER, fontName="Helvetica")
header_style = ParagraphStyle("SectionHeader", fontSize=11, fontName="Helvetica-Bold", spaceAfter=4)
normal_style = styles["Normal"]


def lab_header(lab_name, address, phone):
    return [
        Paragraph(lab_name, title_style),
        Paragraph(address, subtitle_style),
        Paragraph(f"Phone: {phone}", subtitle_style),
        Spacer(1, 4 * mm),
    ]


def patient_info_table(name, age, gender, dob, patient_id, ref_doctor, report_date, sample_date):
    data = [
        ["Patient Name:", name, "Patient ID:", patient_id],
        ["Age / Gender:", f"{age} / {gender}", "Date of Birth:", dob],
        ["Referring Doctor:", ref_doctor, "Report Date:", report_date],
        ["Sample Collected:", sample_date, "", ""],
    ]
    t = Table(data, colWidths=[40 * mm, 60 * mm, 40 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EBF5FB")),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def results_table(rows, title):
    """
    rows: list of (Parameter, Value, Unit, Reference Range, Flag)
    """
    header = [["Parameter", "Result", "Unit", "Reference Range", "Flag"]]
    data = header + [[r[0], r[1], r[2], r[3], r[4]] for r in rows]
    col_widths = [65 * mm, 25 * mm, 20 * mm, 45 * mm, 20 * mm]
    t = Table(data, colWidths=col_widths)

    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E86C1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]

    # Colour flag column
    for i, row in enumerate(rows, 1):
        flag = row[4]
        if flag == "CRITICAL":
            style.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#E74C3C")))
            style.append(("TEXTCOLOR", (4, i), (4, i), colors.white))
            style.append(("FONTNAME", (4, i), (4, i), "Helvetica-Bold"))
        elif flag in ("HIGH", "LOW"):
            style.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#F39C12")))
            style.append(("TEXTCOLOR", (4, i), (4, i), colors.white))

    t.setStyle(TableStyle(style))
    return [Paragraph(title, header_style), Spacer(1, 2 * mm), t, Spacer(1, 5 * mm)]


def build_pdf(path, title_text, patient_kwargs, sections):
    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    story = []
    story += lab_header(**{
        "lab_name": patient_kwargs.get("lab_name", "Metropolis Healthcare Pvt. Ltd."),
        "address": "Plot 15, Sector 44, Gurugram, Haryana - 122003",
        "phone": "+91-124-4888888",
    })
    story.append(Spacer(1, 2 * mm))
    story.append(patient_info_table(
        name=patient_kwargs["name"],
        age=patient_kwargs["age"],
        gender=patient_kwargs["gender"],
        dob=patient_kwargs["dob"],
        patient_id=patient_kwargs["patient_id"],
        ref_doctor=patient_kwargs["ref_doctor"],
        report_date=patient_kwargs["report_date"],
        sample_date=patient_kwargs["sample_date"],
    ))
    story.append(Spacer(1, 5 * mm))

    for section_title, rows in sections:
        story += results_table(rows, section_title)

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "* This report is generated for evaluation purposes only. "
        "Not for clinical use.",
        ParagraphStyle("Footer", fontSize=7, textColor=colors.grey)
    ))
    doc.build(story)
    print(f"Generated: {path}")


# ---------------------------------------------------------------------------
# PDF 1: Clean CBC — all normal
# ---------------------------------------------------------------------------
def generate_pdf1():
    patient = dict(
        lab_name="Metropolis Healthcare Pvt. Ltd.",
        name="Arjun Kapoor",
        age="28",
        gender="Male",
        dob="10-Mar-1996",
        patient_id="MET-2026-0081",
        ref_doctor="Dr. Sunita Rao (GP)",
        report_date="13-May-2026",
        sample_date="13-May-2026 07:30 AM",
    )
    cbc = [
        # (Parameter, Value, Unit, Ref Range, Flag)
        ("Haemoglobin (Hb)",         "14.8",    "g/dL",    "13.0 - 17.0",   ""),
        ("Total RBC Count",           "5.1",     "mill/µL", "4.5 - 5.5",     ""),
        ("Packed Cell Volume (PCV)",  "44.2",    "%",       "40.0 - 50.0",   ""),
        ("Mean Corpuscular Volume",   "86.7",    "fL",      "80.0 - 100.0",  ""),
        ("MCH",                       "29.0",    "pg",      "27.0 - 32.0",   ""),
        ("MCHC",                      "33.5",    "g/dL",    "31.5 - 34.5",   ""),
        ("WBC (Total Leucocyte)",     "7200",    "/µL",     "4000 - 11000",  ""),
        ("Neutrophils",               "60",      "%",       "50 - 70",       ""),
        ("Lymphocytes",               "32",      "%",       "20 - 40",       ""),
        ("Monocytes",                 "6",       "%",       "2 - 8",         ""),
        ("Eosinophils",               "2",       "%",       "1 - 6",         ""),
        ("Platelet Count",            "2,40,000","/µL",     "1,50,000 - 4,00,000", ""),
    ]
    build_pdf(
        path=os.path.join(OUTPUT_DIR, "pdf1_clean_cbc.pdf"),
        title_text="Complete Blood Count (CBC)",
        patient_kwargs=patient,
        sections=[("COMPLETE BLOOD COUNT (CBC)", cbc)],
    )


# ---------------------------------------------------------------------------
# PDF 2: Multiple abnormals — low Hb, high WBC, low platelets
# ---------------------------------------------------------------------------
def generate_pdf2():
    patient = dict(
        lab_name="SRL Diagnostics",
        name="Meera Nair",
        age="42",
        gender="Female",
        dob="05-Jun-1983",
        patient_id="SRL-2026-1142",
        ref_doctor="Dr. Amit Joshi (Haematology)",
        report_date="13-May-2026",
        sample_date="13-May-2026 08:00 AM",
    )
    cbc = [
        ("Haemoglobin (Hb)",         "8.1",     "g/dL",    "12.0 - 16.0",   "LOW"),
        ("Total RBC Count",           "3.2",     "mill/µL", "3.8 - 5.2",     "LOW"),
        ("Packed Cell Volume (PCV)",  "27.0",    "%",       "36.0 - 46.0",   "LOW"),
        ("Mean Corpuscular Volume",   "70.2",    "fL",      "80.0 - 100.0",  "LOW"),
        ("MCH",                       "22.1",    "pg",      "27.0 - 32.0",   "LOW"),
        ("MCHC",                      "30.0",    "g/dL",    "31.5 - 34.5",   "LOW"),
        ("WBC (Total Leucocyte)",     "14500",   "/µL",     "4000 - 11000",  "HIGH"),
        ("Neutrophils",               "78",      "%",       "50 - 70",       "HIGH"),
        ("Lymphocytes",               "18",      "%",       "20 - 40",       "LOW"),
        ("Monocytes",                 "4",       "%",       "2 - 8",         ""),
        ("Eosinophils",               "0",       "%",       "1 - 6",         "LOW"),
        ("Platelet Count",            "85,000",  "/µL",     "1,50,000 - 4,00,000", "LOW"),
    ]
    lft = [
        ("Total Bilirubin",          "1.1",     "mg/dL",   "0.3 - 1.2",     ""),
        ("Direct Bilirubin",         "0.4",     "mg/dL",   "0.0 - 0.5",     ""),
        ("SGOT (AST)",               "42",      "U/L",     "10 - 40",       "HIGH"),
        ("SGPT (ALT)",               "38",      "U/L",     "10 - 40",       ""),
        ("Alkaline Phosphatase",     "88",      "U/L",     "44 - 147",      ""),
        ("Total Protein",            "7.2",     "g/dL",    "6.0 - 8.0",     ""),
        ("Albumin",                  "3.8",     "g/dL",    "3.5 - 5.0",     ""),
    ]
    build_pdf(
        path=os.path.join(OUTPUT_DIR, "pdf2_multiple_abnormals.pdf"),
        title_text="CBC + LFT with Abnormals",
        patient_kwargs=patient,
        sections=[
            ("COMPLETE BLOOD COUNT (CBC)", cbc),
            ("LIVER FUNCTION TEST (LFT)", lft),
        ],
    )


# ---------------------------------------------------------------------------
# PDF 3: Critical value — K+ 6.8, Creatinine 5.8
# ---------------------------------------------------------------------------
def generate_pdf3():
    patient = dict(
        lab_name="Dr. Lal PathLabs",
        name="Rajan Verma",
        age="65",
        gender="Male",
        dob="22-Nov-1960",
        patient_id="DLL-2026-3391",
        ref_doctor="Dr. Priya Mehta (Nephrology)",
        report_date="13-May-2026",
        sample_date="13-May-2026 06:45 AM",
    )
    kft = [
        ("Blood Urea Nitrogen (BUN)", "78",    "mg/dL",   "7 - 25",        "HIGH"),
        ("Serum Creatinine",          "5.8",   "mg/dL",   "0.7 - 1.3",     "CRITICAL"),
        ("Uric Acid",                 "9.1",   "mg/dL",   "3.5 - 7.2",     "HIGH"),
        ("Serum Sodium (Na+)",        "138",   "mEq/L",   "136 - 145",     ""),
        ("Serum Potassium (K+)",      "6.8",   "mEq/L",   "3.5 - 5.1",     "CRITICAL"),
        ("Serum Chloride",            "102",   "mEq/L",   "98 - 107",      ""),
        ("Serum Bicarbonate",         "18",    "mEq/L",   "22 - 29",       "LOW"),
        ("eGFR",                      "9",     "mL/min/1.73m²", "> 60",    "LOW"),
    ]
    cbc = [
        ("Haemoglobin (Hb)",         "9.8",   "g/dL",    "13.0 - 17.0",   "LOW"),
        ("WBC (Total Leucocyte)",    "9800",   "/µL",     "4000 - 11000",  ""),
        ("Platelet Count",           "1,95,000", "/µL",  "1,50,000 - 4,00,000", ""),
    ]
    build_pdf(
        path=os.path.join(OUTPUT_DIR, "pdf3_critical_values.pdf"),
        title_text="KFT + CBC — Critical Values",
        patient_kwargs=patient,
        sections=[
            ("KIDNEY FUNCTION TEST (KFT)", kft),
            ("COMPLETE BLOOD COUNT (CBC)", cbc),
        ],
    )


# ---------------------------------------------------------------------------
# PDF 4: Urine Routine — generalisation test (non-blood report)
# ---------------------------------------------------------------------------
def generate_pdf4():
    patient = dict(
        lab_name="Thyrocare Technologies Ltd.",
        name="Sneha Gupta",
        age="35",
        gender="Female",
        dob="18-Sep-1990",
        patient_id="TC-2026-7821",
        ref_doctor="Dr. Rakesh Sharma (Internal Medicine)",
        report_date="13-May-2026",
        sample_date="13-May-2026 09:15 AM",
    )
    urine = [
        ("Colour",                    "Dark Yellow","",       "Pale Yellow - Yellow", ""),
        ("Appearance",                "Turbid",    "",        "Clear",                ""),
        ("pH",                        "5.0",       "",        "5.0 - 8.0",            ""),
        ("Specific Gravity",          "1.035",     "",        "1.005 - 1.030",        "HIGH"),
        ("Protein / Albumin",         "3+",        "",        "Nil",                  "HIGH"),
        ("Glucose (Urine)",           "2+",        "",        "Nil",                  "HIGH"),
        ("Ketone Bodies",             "Trace",     "",        "Nil",                  ""),
        ("Bilirubin (Urine)",         "Negative",  "",        "Negative",             ""),
        ("Urobilinogen",              "Normal",    "",        "Normal",               ""),
        ("Nitrite",                   "Positive",  "",        "Negative",             "HIGH"),
        ("WBC / Pus Cells",           "25-30",     "/HPF",    "0 - 5",                "HIGH"),
        ("RBC (Urine)",               "8-10",      "/HPF",    "0 - 2",                "HIGH"),
        ("Epithelial Cells",          "4-6",       "/HPF",    "0 - 5",                ""),
        ("Casts",                     "Granular (few)", "",   "None",                 "HIGH"),
        ("Bacteria",                  "Moderate",  "",        "None",                 "HIGH"),
    ]
    build_pdf(
        path=os.path.join(OUTPUT_DIR, "pdf4_urine_routine.pdf"),
        title_text="Urine Routine & Microscopy",
        patient_kwargs=patient,
        sections=[("URINE ROUTINE & MICROSCOPY", urine)],
    )


# ---------------------------------------------------------------------------
# PDF 5: Thyroid Panel — abnormal TSH + normal T3/T4
# ---------------------------------------------------------------------------
def generate_pdf5():
    patient = dict(
        lab_name="Apollo Diagnostics",
        name="Vikram Singh",
        age="52",
        gender="Male",
        dob="07-Jan-1974",
        patient_id="APL-2026-4410",
        ref_doctor="Dr. Nandini Iyer (Endocrinology)",
        report_date="13-May-2026",
        sample_date="13-May-2026 07:00 AM",
    )
    thyroid = [
        ("TSH (Thyroid Stimulating Hormone)", "18.5",  "µIU/mL",  "0.4 - 4.0",   "HIGH"),
        ("Free T3",                            "2.1",   "pg/mL",   "2.0 - 4.4",   ""),
        ("Free T4",                            "0.7",   "ng/dL",   "0.8 - 1.8",   "LOW"),
        ("Total T3",                           "82",    "ng/dL",   "80 - 200",     ""),
        ("Total T4",                           "4.2",   "µg/dL",   "4.5 - 12.5",  "LOW"),
    ]
    lipid = [
        ("Total Cholesterol",                 "265",   "mg/dL",   "< 200",        "HIGH"),
        ("HDL Cholesterol",                   "34",    "mg/dL",   "40 - 60",      "LOW"),
        ("LDL Cholesterol",                   "185",   "mg/dL",   "< 100",        "HIGH"),
        ("Triglycerides",                     "310",   "mg/dL",   "< 150",        "HIGH"),
        ("VLDL Cholesterol",                  "62",    "mg/dL",   "< 30",         "HIGH"),
        ("Total Chol / HDL Ratio",            "7.8",   "",        "< 5.0",        "HIGH"),
    ]
    build_pdf(
        path=os.path.join(OUTPUT_DIR, "pdf5_thyroid_lipid.pdf"),
        title_text="Thyroid Profile + Lipid Panel",
        patient_kwargs=patient,
        sections=[
            ("THYROID FUNCTION TEST", thyroid),
            ("LIPID PROFILE", lipid),
        ],
    )


if __name__ == "__main__":
    print("Generating test PDFs...")
    generate_pdf1()
    generate_pdf2()
    generate_pdf3()
    generate_pdf4()
    generate_pdf5()
    print(f"\nAll PDFs written to: {OUTPUT_DIR}")
