"""
app/graph/scribe/pdf_builder.py — Hospital-grade OPD prescription PDF.

Layout:
  - Header: doctor info (left) | clinic name (right)
  - "Outpatient Summary and Prescription" subtitle
  - Patient information bar
  - Clinical sections: Chief Complaints, History, Examination, Diagnosis
  - Investigations
  - Medicines table with Morning / Afternoon / Evening / Night columns
  - Advice
  - Signature / stamp footer
  - Audit appendix: grounding report + transcript (new page)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, PageBreak,
)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
DARK_BLUE   = colors.HexColor("#1B3A6B")
MID_BLUE    = colors.HexColor("#2C5F9E")
LIGHT_BLUE  = colors.HexColor("#E8F0FB")
PALE_BLUE   = colors.HexColor("#F5F8FD")
SECTION_BG  = colors.HexColor("#F7F9FC")
BORDER      = colors.HexColor("#C5CAD1")
GREY        = colors.HexColor("#5D6D7E")
LIGHT_GREY  = colors.HexColor("#EFEFEF")
TEXT_DARK   = colors.HexColor("#1A1A2E")
WHITE       = colors.white
BLACK       = colors.black
RED         = colors.HexColor("#C0392B")
AMBER       = colors.HexColor("#D68910")
GREEN       = colors.HexColor("#1E8449")

# ---------------------------------------------------------------------------
# Investigation keywords — used to pull test orders from plan text
# ---------------------------------------------------------------------------
_INVESTIGATION_KW = re.compile(
    r"\b(mri|ct\b|x[\-\s]?ray|xray|ultrasound|usg|cbc|complete blood|hba1c|ecg|echo"
    r"|eeg|ncv|emg|biopsy|endoscopy|colonoscopy|lft|kft|rft|tsh|thyroid|lipid"
    r"|fasting|post prandial|pp glucose|creatinine|serum|urine|culture|spirometry"
    r"|audiometry|fundoscopy|bone density|dexa|pet scan|angiography|stress test"
    r"|blood test|liver function|kidney function|nerve conduction|cardiac)\b",
    re.IGNORECASE,
)

_ADVICE_KW = re.compile(
    r"\b(walk|exercise|diet|avoid|rest|sleep|reduce|limit|increase|follow.?up"
    r"|return|come back|review|physiotherapy|physio|lifestyle|weight|fluids"
    r"|yoga|meditation|salt|sugar|oil|fried|alcohol|smoking|tobacco|stress)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> dict:
    s = {}

    def ps(name, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, **kw)

    s["clinic_name"] = ps("clinic_name", fontSize=18, fontName="Helvetica-Bold",
                          textColor=DARK_BLUE, alignment=TA_RIGHT, spaceAfter=0)
    s["doc_name"]    = ps("doc_name", fontSize=13, fontName="Helvetica-Bold",
                          textColor=DARK_BLUE, spaceAfter=1)
    s["doc_sub"]     = ps("doc_sub", fontSize=8.5, fontName="Helvetica",
                          textColor=GREY, leading=12, spaceAfter=1)
    s["page_title"]  = ps("page_title", fontSize=9, fontName="Helvetica-Bold",
                          textColor=GREY, alignment=TA_CENTER)
    s["pt_label"]    = ps("pt_label", fontSize=7.5, fontName="Helvetica-Bold",
                          textColor=GREY)
    s["pt_value"]    = ps("pt_value", fontSize=9, fontName="Helvetica",
                          textColor=TEXT_DARK)
    s["pt_name"]     = ps("pt_name", fontSize=11, fontName="Helvetica-Bold",
                          textColor=TEXT_DARK)
    s["sec_head"]    = ps("sec_head", fontSize=8.5, fontName="Helvetica-Bold",
                          textColor=DARK_BLUE, spaceBefore=4, spaceAfter=1)
    s["sec_body"]    = ps("sec_body", fontSize=9, fontName="Helvetica",
                          textColor=TEXT_DARK, leading=14, spaceAfter=2,
                          alignment=TA_JUSTIFY)
    s["bullet"]      = ps("bullet", fontSize=9, fontName="Helvetica",
                          textColor=TEXT_DARK, leading=13, leftIndent=8)
    s["med_name"]    = ps("med_name", fontSize=9, fontName="Helvetica-Bold",
                          textColor=TEXT_DARK, leading=12)
    s["med_detail"]  = ps("med_detail", fontSize=7.5, fontName="Helvetica",
                          textColor=GREY, leading=11)
    s["med_note"]    = ps("med_note", fontSize=7.5, fontName="Helvetica-Oblique",
                          textColor=GREY, alignment=TA_LEFT)
    s["col_head"]    = ps("col_head", fontSize=8, fontName="Helvetica-Bold",
                          textColor=WHITE, alignment=TA_CENTER)
    s["col_icon"]    = ps("col_icon", fontSize=10, fontName="Helvetica",
                          textColor=WHITE, alignment=TA_CENTER)
    s["timing_val"]  = ps("timing_val", fontSize=10, fontName="Helvetica-Bold",
                          textColor=TEXT_DARK, alignment=TA_CENTER)
    s["footer"]      = ps("footer", fontSize=7, fontName="Helvetica",
                          textColor=GREY, alignment=TA_CENTER)
    s["sig_label"]   = ps("sig_label", fontSize=7.5, fontName="Helvetica",
                          textColor=GREY, alignment=TA_CENTER)
    s["audit_head"]  = ps("audit_head", fontSize=9, fontName="Helvetica-Bold",
                          textColor=GREY, spaceBefore=4, spaceAfter=2)
    s["audit_body"]  = ps("audit_body", fontSize=7.5, fontName="Helvetica",
                          textColor=GREY, leading=11)
    s["warn"]        = ps("warn", fontSize=8, fontName="Helvetica",
                          textColor=RED, leading=12)
    s["missing"]     = ps("missing", fontSize=8, fontName="Helvetica-Oblique",
                          textColor=AMBER, leading=12)

    return s


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

_TIMING_MATRIX: dict[str, tuple[bool, bool, bool, bool]] = {
    # (morning, afternoon, evening, night)
    "qd":              (True,  False, False, False),
    "od":              (True,  False, False, False),
    "once daily":      (True,  False, False, False),
    "bid":             (True,  False, True,  False),
    "bd":              (True,  False, True,  False),
    "twice daily":     (True,  False, True,  False),
    "tid":             (True,  True,  False, True),
    "tds":             (True,  True,  False, True),
    "three times daily": (True, True, False, True),
    "thrice daily":    (True,  True,  False, True),
    "qid":             (True,  True,  True,  True),
    "four times daily":(True,  True,  True,  True),
    "hs":              (False, False, False, True),
    "bedtime":         (False, False, False, True),
    "night":           (False, False, False, True),
    "morning":         (True,  False, False, False),
    "sos":             (False, False, False, False),
    "prn":             (False, False, False, False),
    "as needed":       (False, False, False, False),
}


def _get_timing(frequency: str, fhir_timing: Optional[dict] = None
                ) -> tuple[bool, bool, bool, bool]:
    """Return (morning, afternoon, evening, night) for a frequency string."""
    # Try FHIR timing code first
    if fhir_timing:
        code = (
            fhir_timing.get("code", {})
            .get("coding", [{}])[0]
            .get("code", "")
            .upper()
        )
        _fhir_map = {
            "QD":  (True,  False, False, False),
            "BID": (True,  False, True,  False),
            "TID": (True,  True,  False, True),
            "QID": (True,  True,  True,  True),
            "PRN": (False, False, False, False),
        }
        if code in _fhir_map:
            return _fhir_map[code]

    key = (frequency or "").lower().strip()
    return _TIMING_MATRIX.get(key, (False, False, False, False))


def _timing_cell(active: bool) -> str:
    return "1" if active else "–"   # "1" or "–"


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

def _split_plan_content(plan_text: str) -> tuple[list[str], list[str]]:
    """
    Heuristically split plan free-text into (investigation_lines, advice_lines).
    Lines that mention test names → investigations; lifestyle/diet lines → advice.
    """
    investigations: list[str] = []
    advice: list[str] = []
    for raw_line in plan_text.splitlines():
        line = raw_line.strip().lstrip("•-*123456789. ")
        if not line:
            continue
        if _INVESTIGATION_KW.search(line):
            investigations.append(line)
        elif _ADVICE_KW.search(line):
            advice.append(line)
    return investigations, advice


def _format_symptom_list(symptoms: list[dict]) -> str:
    """Format structured symptom list into a readable string."""
    parts = []
    for s in symptoms:
        name = s.get("name", "")
        if not name:
            continue
        detail = []
        if s.get("severity"):
            detail.append(s["severity"])
        if s.get("duration"):
            detail.append(s["duration"])
        parts.append(f"{name} ({', '.join(detail)})" if detail else name)
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Section builders — each returns a list of flowables
# ---------------------------------------------------------------------------

def _header_block(
    page_w: float, margin: float, styles: dict,
    doctor_name: str, clinic_name: str, doctor_profile: dict,
) -> list:
    """Two-column header: doctor info left | clinic name right."""
    qual = doctor_profile.get("qualifications", "") or ""
    specialty = (
        doctor_profile.get("specialty") or
        doctor_profile.get("department") or ""
    )
    reg = doctor_profile.get("registration_number", "") or ""

    left_parts = []
    if doctor_name:
        left_parts.append(Paragraph(doctor_name, styles["doc_name"]))
    if qual:
        left_parts.append(Paragraph(qual, styles["doc_sub"]))
    if specialty:
        left_parts.append(Paragraph(specialty, styles["doc_sub"]))
    if reg:
        left_parts.append(Paragraph(f"Reg. No: {reg}", styles["doc_sub"]))
    if not left_parts:
        left_parts.append(Paragraph("", styles["doc_sub"]))

    right_parts = [
        Paragraph(clinic_name or "ClinicAI", styles["clinic_name"]),
        Paragraph("Outpatient Summary and Prescription",
                  ParagraphStyle("rx_tag", fontSize=7.5, fontName="Helvetica",
                                 textColor=GREY, alignment=TA_RIGHT)),
    ]

    col_w = (page_w - 2 * margin) / 2
    data = [[left_parts, right_parts]]
    tbl = Table(data, colWidths=[col_w, col_w])
    tbl.setStyle(TableStyle([
        ("VALIGN",   (0, 0), (-1, -1), "TOP"),
        ("PADDING",  (0, 0), (-1, -1), 0),
        ("ALIGN",    (1, 0), (1, 0),   "RIGHT"),
    ]))
    return [tbl, Spacer(1, 1.5 * mm),
            HRFlowable(width="100%", thickness=1.2, color=DARK_BLUE),
            Spacer(1, 1 * mm)]


def _patient_bar(
    page_w: float, margin: float, styles: dict,
    patient_name: str, patient_info: dict, visit_date: str,
) -> list:
    """Compact patient info block with labelled fields."""
    full_w = page_w - 2 * margin

    def lv(label: str, value: str) -> Paragraph:
        if not value:
            return Paragraph("", styles["pt_value"])
        return Paragraph(
            f'<font name="Helvetica-Bold" color="{GREY.hexval()}">'
            f'{label}:</font> {value}',
            styles["pt_value"],
        )

    name = patient_name or patient_info.get("name", "")
    age   = patient_info.get("age", "")
    gender = patient_info.get("gender", "")
    phone  = patient_info.get("phone", "")
    address = patient_info.get("address", "")
    visit_id = patient_info.get("visit_id", "")
    allergy  = patient_info.get("allergy", "")

    age_gender_parts = [p for p in [gender, age] if p]
    age_gender_str = ", ".join(age_gender_parts)

    row1_left  = [Paragraph(name, styles["pt_name"])] if name else []
    row1_right = []
    if visit_id:
        row1_right.append(lv("Visit ID", visit_id))
    if visit_date:
        row1_right.append(lv("Visit Date", visit_date))

    row2 = []
    if age_gender_str:
        row2.append(lv("", age_gender_str))
    if address:
        row2.append(lv("Address", address))
    if phone:
        row2.append(lv("Phone", phone))

    content_rows: list[list] = []

    # Row 1: name (left), visit info (right)
    col_w = full_w / 2
    if row1_left or row1_right:
        data1 = [[row1_left or [""], row1_right or [""]]]
        t1 = Table(data1, colWidths=[col_w, col_w])
        t1.setStyle(TableStyle([
            ("VALIGN",  (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 2),
            ("ALIGN",   (1, 0), (1, -1),  "RIGHT"),
        ]))
        content_rows.append([t1])

    # Row 2: age/gender, address, phone
    for item in row2:
        content_rows.append([item])

    if not content_rows:
        return []

    outer = Table(content_rows, colWidths=[full_w])
    outer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
        ("BOX",        (0, 0), (-1, -1), 0.8, DARK_BLUE),
        ("PADDING",    (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, 0),  6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    result = [outer]

    if allergy:
        result += [
            Spacer(1, 1.5 * mm),
            Paragraph(
                f'<font name="Helvetica-Bold">Allergy:</font> {allergy}',
                styles["sec_body"],
            ),
        ]

    result.append(Spacer(1, 2.5 * mm))
    return result


def _clinical_section(title: str, content: str, styles: dict,
                       full_w: float, numbered: bool = False) -> list:
    """Generic labelled clinical section with bold title."""
    if not content or not content.strip():
        return []
    items = [Paragraph(title, styles["sec_head"])]
    if numbered:
        for i, line in enumerate(content.strip().splitlines(), 1):
            line = line.strip()
            if line:
                items.append(Paragraph(f"{i}. {line}", styles["sec_body"]))
    else:
        items.append(Paragraph(content.strip(), styles["sec_body"]))
    items.append(Spacer(1, 1.5 * mm))
    return items


def _diagnosis_block(
    diagnoses: list[str], assessment_text: str, styles: dict
) -> list:
    """Numbered diagnosis list with Provisional type label."""
    items: list[str] = []
    if diagnoses:
        items = diagnoses
    elif assessment_text:
        items = [l.strip() for l in assessment_text.splitlines() if l.strip()]

    if not items:
        return []

    result = [Paragraph("DIAGNOSIS:", styles["sec_head"])]
    for i, dx in enumerate(items, 1):
        row = Table(
            [[Paragraph(f"{i}.  {dx}", styles["sec_body"]),
              Paragraph("Type: &nbsp; Provisional",
                        ParagraphStyle("dx_type", fontSize=8, fontName="Helvetica",
                                       textColor=GREY, alignment=TA_RIGHT))]],
            colWidths=None,
        )
        row.setStyle(TableStyle([
            ("VALIGN",  (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 1),
        ]))
        result.append(row)
    result.append(Spacer(1, 2 * mm))
    return result


def _investigations_block(items: list[str], styles: dict) -> list:
    if not items:
        return []
    result = [Paragraph("OTHER TESTS", styles["sec_head"])]
    for item in items:
        result.append(Paragraph(f"•{item}", styles["bullet"]))
    result.append(Spacer(1, 2 * mm))
    return result


def _medicines_block(
    medications: list[dict],
    fhir_bundle: dict,
    plan_text: str,
    full_w: float,
    styles: dict,
) -> list:
    """
    Medicines table with numbered entries and Morning/Afternoon/Evening/Night columns.
    Falls back to plan_text if medications list is empty.
    """
    if not medications and not plan_text.strip():
        return []

    # Build a freq→timing lookup from FHIR bundle
    fhir_timing_by_name: dict[str, dict] = {}
    for entry in (fhir_bundle or {}).get("entry", []):
        res = entry.get("resource", {})
        if res.get("resourceType") != "MedicationRequest":
            continue
        name_text = (
            res.get("medicationCodeableConcept", {}).get("text") or
            res.get("medicationCodeableConcept", {}).get("coding", [{}])[0].get("display", "")
        ).lower().strip()
        timing = (res.get("dosageInstruction") or [{}])[0].get("timing")
        if name_text and timing:
            fhir_timing_by_name[name_text] = timing

    # Column widths
    name_col = full_w * 0.56
    time_col = (full_w - name_col) / 4

    # Header row
    icon_style = ParagraphStyle("icon_s", fontSize=12, fontName="Helvetica",
                                textColor=WHITE, alignment=TA_CENTER)
    head = [
        Paragraph("MEDICINES:", styles["col_head"]),
        Paragraph("☀",  icon_style),   # ☀ morning
        Paragraph("☀",  icon_style),   # ☀ afternoon
        Paragraph("☆",  icon_style),   # ☆ evening (sunset-ish)
        Paragraph("☽",  icon_style),   # ☽ night
    ]
    sub = [
        Paragraph("", styles["col_head"]),
        Paragraph("Morning",   styles["col_head"]),
        Paragraph("Afternoon", styles["col_head"]),
        Paragraph("Evening",   styles["col_head"]),
        Paragraph("Night",     styles["col_head"]),
    ]

    table_data = [head, sub]
    row_styles: list = [
        ("BACKGROUND",  (0, 0), (-1, 0),  DARK_BLUE),
        ("BACKGROUND",  (0, 1), (-1, 1),  MID_BLUE),
        ("TEXTCOLOR",   (0, 0), (-1, 1),  WHITE),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("PADDING",     (0, 0), (-1, -1), 4),
        ("BOX",         (0, 0), (-1, -1), 0.6, DARK_BLUE),
        ("INNERGRID",   (0, 0), (-1, -1), 0.3, BORDER),
    ]

    if not medications:
        # Fallback: show plan text in a single merged cell
        table_data.append([
            Paragraph(plan_text.strip(), styles["med_detail"]), "", "", "", "",
        ])
        row_styles.append(("SPAN", (0, 2), (-1, 2)))
        row_styles.append(("BACKGROUND", (0, 2), (-1, 2), WHITE))
    else:
        for i, med in enumerate(medications, 1):
            name = med.get("name", "")
            dose = med.get("dose", "")
            freq = med.get("frequency", "")

            fhir_t = fhir_timing_by_name.get(name.lower().strip())
            morn, aft, eve, night = _get_timing(freq, fhir_t)

            # Build detail line
            detail_parts = [p for p in [dose, freq] if p]
            detail = ", ".join(detail_parts) if detail_parts else ""

            name_cell = [Paragraph(f"{i}.  {name}", styles["med_name"])]
            if detail:
                name_cell.append(Paragraph(detail, styles["med_detail"]))

            row_idx = len(table_data)
            table_data.append([
                name_cell,
                Paragraph(_timing_cell(morn),  styles["timing_val"]),
                Paragraph(_timing_cell(aft),   styles["timing_val"]),
                Paragraph(_timing_cell(eve),   styles["timing_val"]),
                Paragraph(_timing_cell(night), styles["timing_val"]),
            ])
            bg = WHITE if i % 2 == 1 else PALE_BLUE
            row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
            row_styles.append(("TOPPADDING",    (0, row_idx), (-1, row_idx), 5))
            row_styles.append(("BOTTOMPADDING", (0, row_idx), (-1, row_idx), 5))

    tbl = Table(
        table_data,
        colWidths=[name_col, time_col, time_col, time_col, time_col],
    )
    tbl.setStyle(TableStyle(row_styles))

    note = Paragraph(
        "(There may be more medicines on the next page; please go through the entire prescription.)",
        styles["med_note"],
    ) if len(medications) > 4 else None

    result: list = [Paragraph("", styles["sec_head"])]  # spacer label
    if note:
        result.append(note)
        result.append(Spacer(1, 1 * mm))
    result.append(tbl)
    result.append(Spacer(1, 3 * mm))
    return result


def _advice_block(advice_lines: list[str], follow_up_days: Optional[int],
                  styles: dict) -> list:
    all_lines = list(advice_lines)
    if follow_up_days:
        all_lines.append(f"Follow up after {follow_up_days} day(s)")

    if not all_lines:
        return []

    result = [Paragraph("ADVICE", styles["sec_head"])]
    for line in all_lines:
        result.append(Paragraph(f"• {line}", styles["bullet"]))
    result.append(Spacer(1, 3 * mm))
    return result


def _signature_footer(full_w: float, styles: dict) -> list:
    """Two-column signature / stamp area."""
    sig_style = ParagraphStyle("sig_box", fontSize=7.5, fontName="Helvetica",
                               textColor=GREY, alignment=TA_CENTER)
    col_w = full_w / 2
    sig_box = Table(
        [[Paragraph("Doctor's Signature", sig_style),
          Paragraph("Clinic Stamp", sig_style)]],
        colWidths=[col_w, col_w],
        rowHeights=[20 * mm],
    )
    sig_box.setStyle(TableStyle([
        ("BOX",     (0, 0), (0, 0), 0.5, BORDER),
        ("BOX",     (1, 0), (1, 0), 0.5, BORDER),
        ("ALIGN",   (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",  (0, 0), (-1, -1), "BOTTOM"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    return [
        HRFlowable(width="100%", thickness=0.5, color=BORDER),
        Spacer(1, 2 * mm),
        sig_box,
        Spacer(1, 2 * mm),
        Paragraph(
            f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M')}  |  "
            "For clinical use only  |  Verify all details before signing",
            styles["footer"],
        ),
    ]


def _audit_appendix(
    story: list,
    grounding_report: list,
    transcript: str,
    ungrounded_flags: list[str],
    missing_sections: list[str],
    soap_note: dict,
    styles: dict,
    full_w: float,
) -> None:
    """Append grounding + transcript audit pages (for internal use)."""
    SECTION_LABELS = {
        "subjective": "Chief Complaints & History",
        "objective":  "Clinical Findings & Vitals",
        "assessment": "Diagnosis & Assessment",
        "plan":       "Treatment Plan",
    }

    story.append(PageBreak())
    story.append(Paragraph("CLINICAL AUDIT APPENDIX", styles["audit_head"]))
    story.append(Paragraph(
        "This page is for clinical review only and is not part of the patient prescription.",
        styles["audit_body"],
    ))
    story.append(Spacer(1, 3 * mm))

    if ungrounded_flags:
        story.append(HRFlowable(width="100%", thickness=0.5, color=RED))
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph("HALLUCINATION / GROUNDING WARNINGS", styles["audit_head"]))
        story.append(Paragraph(
            "The following sentences could not be verified against the transcript. "
            "Review before signing.",
            styles["audit_body"],
        ))
        for flag in ungrounded_flags:
            story.append(Paragraph(f"• {flag}", styles["warn"]))
        story.append(Spacer(1, 3 * mm))

    if missing_sections:
        story.append(Paragraph("INCOMPLETE SECTIONS — DOCTOR ACTION REQUIRED", styles["audit_head"]))
        for sk in missing_sections:
            cq = soap_note.get(sk, {}).get("clarifying_question", "")
            label = SECTION_LABELS.get(sk, sk).upper()
            story.append(Paragraph(
                f"• <b>{label}</b>: {cq or 'No information found in voice note.'}",
                styles["missing"],
            ))
        story.append(Spacer(1, 3 * mm))

    if grounding_report:
        story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
        story.append(Spacer(1, 1 * mm))
        story.append(Paragraph("GROUNDING REPORT", styles["audit_head"]))
        gr_data = [["Sentence", "Transcript Segment", "OK?"]]
        for entry in grounding_report:
            gr_data.append([
                str(entry.get("sentence", ""))[:80],
                str(entry.get("transcript_segment", "") or "—")[:60],
                "✓" if entry.get("is_grounded") else "✗",
            ])
        gr_tbl = Table(gr_data, colWidths=[full_w * 0.50, full_w * 0.38, full_w * 0.12])
        gr_tbl.setStyle(TableStyle([
            ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 7),
            ("BACKGROUND",   (0, 0), (-1, 0),  GREY),
            ("TEXTCOLOR",    (0, 0), (-1, 0),  WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("BOX",          (0, 0), (-1, -1), 0.4, GREY),
            ("INNERGRID",    (0, 0), (-1, -1), 0.2, LIGHT_GREY),
            ("PADDING",      (0, 0), (-1, -1), 4),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(gr_tbl)
        story.append(Spacer(1, 3 * mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 1 * mm))
    story.append(Paragraph("ORIGINAL TRANSCRIPT", styles["audit_head"]))
    display = transcript[:2000] + ("…" if len(transcript) > 2000 else "")
    story.append(Paragraph(display or "(No transcript available)", styles["audit_body"]))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_soap_pdf(
    output_path: str,
    soap_note: dict,
    transcript: str,
    grounding_report: list,
    ungrounded_flags: list[str],
    missing_sections: list[str],
    doctor_name: str = "",
    patient_name: str = "",
    clinic_name: str = "",
    snomed_mappings: Optional[list] = None,
    fhir_bundle: Optional[dict] = None,
    # New optional fields
    doctor_profile: Optional[dict] = None,
    clinical_entities: Optional[dict] = None,
    patient_info: Optional[dict] = None,
) -> None:
    """Build and save a hospital-grade OPD prescription PDF."""

    sty = _styles()
    page_w, page_h = A4
    margin = 16 * mm
    full_w = page_w - 2 * margin

    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=14 * mm, bottomMargin=14 * mm,
    )
    frame = Frame(margin, 14 * mm, full_w, page_h - 28 * mm, id="main")
    doc.addPageTemplates([PageTemplate(id="main_page", frames=[frame])])

    story: list = []

    # ── Resolve data from arguments ─────────────────────────────────────────
    dp = doctor_profile or {}
    ce = clinical_entities or {}
    pi = patient_info or {}

    # Doctor name — prefer explicit arg over profile key
    dr_name = (
        doctor_name or
        dp.get("name") or
        soap_note.get("doctor_name", "")
    )
    if dr_name and not dr_name.lower().startswith("dr"):
        dr_name = f"Dr. {dr_name}"

    # Clinic name
    cl_name = clinic_name or dp.get("clinic_name", "") or "ClinicAI"

    # Patient name
    pt_name = patient_name or soap_note.get("patient_name", "")

    # Visit date
    visit_date = soap_note.get("date", "") or datetime.now().strftime("%d-%b-%Y")

    # SOAP sections
    subj = soap_note.get("subjective", {})
    obj  = soap_note.get("objective",  {})
    asmnt = soap_note.get("assessment", {})
    plan  = soap_note.get("plan",       {})

    subj_text  = subj.get("content",  "") or ""
    obj_text   = obj.get("content",   "") or ""
    asmnt_text = asmnt.get("content", "") or ""
    plan_text  = plan.get("content",  "") or ""

    # Structured entities
    medications: list[dict] = ce.get("medications") or []
    diagnoses:   list[str]  = ce.get("diagnoses")   or []
    symptoms:    list[dict] = ce.get("symptoms")     or []

    # Parse investigations and advice from plan text
    investigations, advice_lines = _split_plan_content(plan_text)

    # Follow-up days (may not be in soap_note — comes from state)
    follow_up_days: Optional[int] = soap_note.get("follow_up_days")

    # Chief Complaints text — prefer structured symptoms, fall back to subjective
    if symptoms:
        chief_complaints = _format_symptom_list(symptoms)
    else:
        chief_complaints = subj_text

    # ── Build story ─────────────────────────────────────────────────────────

    # Header
    story += _header_block(page_w, margin, sty, dr_name, cl_name, dp)

    # Patient bar
    story += _patient_bar(page_w, margin, sty, pt_name, pi, visit_date)

    # Chief Complaints
    story += _clinical_section("CHIEF COMPLAINTS", chief_complaints, sty, full_w)

    # History of Present Illness — show only when it differs from chief complaints
    if subj_text and subj_text != chief_complaints:
        story += _clinical_section("HISTORY OF PRESENT ILLNESS", subj_text, sty, full_w)

    # Physical Examination
    story += _clinical_section("PHYSICAL EXAMINATION", obj_text, sty, full_w)

    # Diagnosis
    story += _diagnosis_block(diagnoses, asmnt_text, sty)

    # Separator
    if investigations or medications:
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
        story.append(Spacer(1, 2 * mm))

    # Investigations
    story += _investigations_block(investigations, sty)

    # Medicines
    story += _medicines_block(medications, fhir_bundle or {}, plan_text, full_w, sty)

    # Advice
    story += _advice_block(advice_lines, follow_up_days, sty)

    # Signature / footer
    story += _signature_footer(full_w, sty)

    # Audit appendix (separate page)
    _audit_appendix(
        story, grounding_report, transcript,
        ungrounded_flags, missing_sections, soap_note,
        sty, full_w,
    )

    doc.build(story)
