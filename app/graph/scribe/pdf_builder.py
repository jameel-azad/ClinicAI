"""
app/pdf_builder.py — Builds a clean, professional SOAP note PDF.

Layout:
  - Header: clinic name, doctor name, date
  - Patient info bar
  - Four SOAP sections (colour-coded by confidence)
  - Missing section callouts (flagged in amber)
  - Ungrounded sentence warnings (red)
  - Grounding report appendix
  - Transcript appendix (for reference)
"""

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BRAND_BLUE = colors.HexColor("#1A5276")
LIGHT_BLUE = colors.HexColor("#D6EAF8")
GREEN = colors.HexColor("#1E8449")
LIGHT_GREEN = colors.HexColor("#D5F5E3")
AMBER = colors.HexColor("#D68910")
LIGHT_AMBER = colors.HexColor("#FDEBD0")
RED = colors.HexColor("#C0392B")
LIGHT_RED = colors.HexColor("#FADBD8")
GREY = colors.HexColor("#7F8C8D")
LIGHT_GREY = colors.HexColor("#F2F3F4")
WHITE = colors.white
BLACK = colors.black


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

def _make_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", fontSize=16, fontName="Helvetica-Bold",
        textColor=WHITE, alignment=TA_CENTER, spaceAfter=2,
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle", fontSize=9, fontName="Helvetica",
        textColor=colors.HexColor("#BFC9CA"), alignment=TA_CENTER,
    )
    styles["section_header"] = ParagraphStyle(
        "section_header", fontSize=11, fontName="Helvetica-Bold",
        textColor=WHITE, spaceBefore=0, spaceAfter=0,
    )
    styles["section_body"] = ParagraphStyle(
        "section_body", fontSize=10, fontName="Helvetica",
        textColor=BLACK, leading=15, spaceAfter=4,
        alignment=TA_JUSTIFY,
    )
    styles["missing_label"] = ParagraphStyle(
        "missing_label", fontSize=10, fontName="Helvetica-Bold",
        textColor=AMBER,
    )
    styles["missing_body"] = ParagraphStyle(
        "missing_body", fontSize=10, fontName="Helvetica-Oblique",
        textColor=AMBER, leading=14,
    )
    styles["warning"] = ParagraphStyle(
        "warning", fontSize=9, fontName="Helvetica",
        textColor=RED, leading=13,
    )
    styles["appendix_header"] = ParagraphStyle(
        "appendix_header", fontSize=10, fontName="Helvetica-Bold",
        textColor=GREY, spaceBefore=6, spaceAfter=3,
    )
    styles["appendix_body"] = ParagraphStyle(
        "appendix_body", fontSize=8, fontName="Helvetica",
        textColor=colors.HexColor("#5D6D7E"), leading=12,
    )
    styles["confidence"] = ParagraphStyle(
        "confidence", fontSize=8, fontName="Helvetica",
        textColor=GREY, alignment=TA_LEFT,
    )
    styles["footer"] = ParagraphStyle(
        "footer", fontSize=7, fontName="Helvetica",
        textColor=GREY, alignment=TA_CENTER,
    )

    return styles


def _confidence_colour(confidence: float) -> colors.Color:
    if confidence >= 0.75:
        return GREEN
    if confidence >= 0.5:
        return AMBER
    return RED


def _section_bg(confidence: float) -> colors.Color:
    if confidence >= 0.75:
        return LIGHT_GREEN
    if confidence >= 0.5:
        return LIGHT_AMBER
    return LIGHT_RED


SECTION_LABELS = {
    "subjective": "Chief Complaints & History",
    "objective": "Clinical Findings & Vitals",
    "assessment": "Diagnosis & Assessment",
    "plan": "Treatment Plan & Prescription",
}


# ---------------------------------------------------------------------------
# Public builder function
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
) -> None:
    """Build and save the SOAP note PDF to output_path."""

    styles = _make_styles()
    page_w, page_h = A4
    margin = 18 * mm

    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
    )

    frame = Frame(
        margin, margin,
        page_w - 2 * margin, page_h - 2 * margin,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="main_page", frames=[frame])])

    story = []

    # -----------------------------------------------------------------------
    # Header block
    # -----------------------------------------------------------------------
    header_data = [[
        Paragraph(clinic_name or "FellowAI Clinic", styles["title"]),
        Paragraph(
            f"Dr. {doctor_name}" if doctor_name else "Doctor",
            styles["subtitle"],
        ),
        Paragraph(
            f"Date: {soap_note.get('date') or datetime.now().strftime('%d %B %Y')}",
            styles["subtitle"],
        ),
    ]]
    header_table = Table(header_data, colWidths=[page_w - 2 * margin])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_BLUE),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    # Patient bar
    pt_name = patient_name or soap_note.get("patient_name", "") or "—"
    pt_data = [[
        Paragraph(f"<b>Patient:</b> {pt_name}", styles["section_body"]),
        Paragraph(
            f"<b>Generated:</b> {datetime.now().strftime('%d %b %Y, %H:%M')}",
            ParagraphStyle("pt_right", fontSize=10, fontName="Helvetica",
                           alignment=TA_LEFT),
        ),
    ]]
    pt_table = Table(pt_data, colWidths=[(page_w - 2 * margin) / 2] * 2)
    pt_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BLUE),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BLUE),
    ]))
    story.append(pt_table)
    story.append(Spacer(1, 5 * mm))

    # -----------------------------------------------------------------------
    # SOAP sections
    # -----------------------------------------------------------------------
    for section_key in ["subjective", "objective", "assessment", "plan"]:
        sec = soap_note.get(section_key, {})
        content = sec.get("content", "")
        confidence = sec.get("confidence", 0.0)
        is_missing = sec.get("is_missing", not bool(content))
        cq = sec.get("clarifying_question", "")
        label = SECTION_LABELS[section_key]
        cc = _confidence_colour(confidence)
        bg = _section_bg(confidence)

        block = []

        # Section header row
        header_row = [[
            Paragraph(label, styles["section_header"]),
            Paragraph(
                f"Confidence: {int(confidence * 100)}%",
                ParagraphStyle("conf_right", fontSize=9, fontName="Helvetica",
                               textColor=WHITE, alignment=TA_LEFT),
            ),
        ]]
        header_t = Table(header_row, colWidths=[
            (page_w - 2 * margin) * 0.7,
            (page_w - 2 * margin) * 0.3,
        ])
        header_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cc),
            ("PADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        block.append(header_t)

        # Content
        if is_missing or not content:
            body_data = [[
                Paragraph("⚠ SECTION INCOMPLETE", styles["missing_label"]),
            ]]
            if cq:
                body_data.append([
                    Paragraph(f"Clarifying question for doctor: {cq}", styles["missing_body"]),
                ])
        else:
            # Check for ungrounded sentences in this section
            safe_content = content
            for ug_sentence in ungrounded_flags:
                if ug_sentence in safe_content:
                    safe_content = safe_content.replace(
                        ug_sentence,
                        f'<font color="#C0392B"><b>[⚠ UNVERIFIED]</b></font> {ug_sentence}',
                    )

            body_data = [[Paragraph(safe_content, styles["section_body"])]]

        body_t = Table(body_data, colWidths=[page_w - 2 * margin])
        body_t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("PADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, cc),
        ]))
        block.append(body_t)
        block.append(Spacer(1, 3 * mm))

        story.append(KeepTogether(block))

    # -----------------------------------------------------------------------
    # Ungrounded flags summary
    # -----------------------------------------------------------------------
    if ungrounded_flags:
        story.append(Spacer(1, 3 * mm))
        story.append(HRFlowable(width="100%", thickness=1, color=RED))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph("⚠ HALLUCINATION / GROUNDING WARNINGS", styles["appendix_header"]))
        story.append(Paragraph(
            "The following sentences could not be verified against the original transcript. "
            "Review before signing.",
            styles["appendix_body"],
        ))
        for flag in ungrounded_flags:
            story.append(Paragraph(f"• {flag}", styles["warning"]))
        story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------------------------
    # Missing sections summary
    # -----------------------------------------------------------------------
    if missing_sections:
        story.append(Paragraph("📋 INCOMPLETE SECTIONS — DOCTOR ACTION REQUIRED", styles["appendix_header"]))
        for sec_key in missing_sections:
            sec = soap_note.get(sec_key, {})
            cq = sec.get("clarifying_question", "")
            story.append(Paragraph(
                f"• <b>{SECTION_LABELS.get(sec_key, sec_key).upper()}</b>: {cq or 'No information found in voice note.'}",
                styles["appendix_body"],
            ))
        story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------------------------
    # Grounding report appendix
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("GROUNDING REPORT (for audit)", styles["appendix_header"]))

    if grounding_report:
        gr_data = [["Sentence", "Transcript Segment", "Grounded?"]]
        for entry in grounding_report:
            grounded = entry.get("is_grounded", False)
            status_text = "✓" if grounded else "✗"
            seg = entry.get("transcript_segment", "") or "—"
            gr_data.append([
                entry.get("sentence", "")[:80],
                seg[:60],
                status_text,
            ])

        gr_table = Table(gr_data, colWidths=[
            (page_w - 2 * margin) * 0.50,
            (page_w - 2 * margin) * 0.38,
            (page_w - 2 * margin) * 0.12,
        ])
        gr_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("BACKGROUND", (0, 0), (-1, 0), GREY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("BOX", (0, 0), (-1, -1), 0.4, GREY),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, LIGHT_GREY),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("WORDWRAP", (0, 0), (-1, -1), True),
        ]))
        story.append(gr_table)
    else:
        story.append(Paragraph("No grounding data available.", styles["appendix_body"]))

    story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------------------------
    # Transcript appendix
    # -----------------------------------------------------------------------
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("ORIGINAL TRANSCRIPT (for reference)", styles["appendix_header"]))
    transcript_display = transcript[:2000] + ("..." if len(transcript) > 2000 else "")
    story.append(Paragraph(transcript_display or "(No transcript available)", styles["appendix_body"]))

    story.append(Spacer(1, 4 * mm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=GREY))
    story.append(Spacer(1, 1 * mm))
    story.append(Paragraph(
        "Generated by FellowAI Clinical Scribe · For clinical review only · "
        "Verify all details before use · DPDP Act 2023 Compliant",
        styles["footer"],
    ))

    doc.build(story)
