"""Convert KT_DOCUMENT.md to KT_DOCUMENT.pdf using ReportLab."""
import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

# ── Colour palette ─────────────────────────────────────────────────────────────
BRAND    = colors.HexColor("#1a56db")   # primary blue
BRAND_LT = colors.HexColor("#e8f0fe")   # light blue bg
CODE_BG  = colors.HexColor("#f4f4f5")   # code block background
GREY     = colors.HexColor("#6b7280")   # secondary text
DARK     = colors.HexColor("#111827")   # body text
BORDER   = colors.HexColor("#d1d5db")   # table/rule border
WARN     = colors.HexColor("#b91c1c")   # red for critical items

PAGE_W, PAGE_H = A4
L_MARGIN = R_MARGIN = 2 * cm
T_MARGIN = B_MARGIN = 2.2 * cm
BODY_W = PAGE_W - L_MARGIN - R_MARGIN


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    s = {}

    s["cover_title"] = ParagraphStyle(
        "cover_title",
        fontSize=28, leading=34, textColor=BRAND,
        fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=8,
    )
    s["cover_sub"] = ParagraphStyle(
        "cover_sub",
        fontSize=13, leading=18, textColor=GREY,
        fontName="Helvetica", alignment=TA_CENTER, spaceAfter=6,
    )
    s["cover_meta"] = ParagraphStyle(
        "cover_meta",
        fontSize=10, leading=14, textColor=GREY,
        fontName="Helvetica", alignment=TA_CENTER,
    )
    s["h1"] = ParagraphStyle(
        "h1",
        fontSize=17, leading=22, textColor=BRAND,
        fontName="Helvetica-Bold", spaceBefore=18, spaceAfter=6,
        leftIndent=0,
    )
    s["h2"] = ParagraphStyle(
        "h2",
        fontSize=13, leading=18, textColor=DARK,
        fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=4,
    )
    s["h3"] = ParagraphStyle(
        "h3",
        fontSize=11, leading=15, textColor=DARK,
        fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=3,
    )
    s["body"] = ParagraphStyle(
        "body",
        fontSize=9.5, leading=14, textColor=DARK,
        fontName="Helvetica", spaceBefore=2, spaceAfter=2,
    )
    s["bullet"] = ParagraphStyle(
        "bullet",
        fontSize=9.5, leading=13, textColor=DARK,
        fontName="Helvetica", leftIndent=14, firstLineIndent=0,
        spaceBefore=1, spaceAfter=1,
        bulletIndent=4,
    )
    s["code_inline"] = ParagraphStyle(
        "code_inline",
        fontSize=8.5, leading=12, textColor=DARK,
        fontName="Courier", backColor=CODE_BG,
        leftIndent=6, rightIndent=6, spaceBefore=2, spaceAfter=2,
        borderPadding=(3, 6, 3, 6),
    )
    s["code_block"] = ParagraphStyle(
        "code_block",
        fontSize=7.5, leading=11, textColor=DARK,
        fontName="Courier", backColor=CODE_BG,
        leftIndent=10, rightIndent=6, spaceBefore=4, spaceAfter=6,
        borderPadding=(5, 8, 5, 8),
    )
    s["note"] = ParagraphStyle(
        "note",
        fontSize=8.5, leading=12, textColor=DARK,
        fontName="Helvetica-Oblique", leftIndent=10, spaceBefore=2, spaceAfter=2,
    )
    return s


# ── Escape helpers ──────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape XML special characters for ReportLab Paragraph."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _inline(text: str) -> str:
    """Convert inline markdown (bold, code, italic) to ReportLab XML.

    Order matters:
    1. Extract backtick spans and replace with placeholders (protect from italic/bold)
    2. Escape XML in remaining text
    3. Apply bold / italic
    4. Restore code spans (already escaped inside)
    """
    # Step 1: extract code spans before escaping
    code_spans = []
    def _stash_code(m):
        idx = len(code_spans)
        inner = _esc(m.group(1))
        code_spans.append(f'<font name="Courier" backColor="#f4f4f5"> {inner} </font>')
        return f"\x00CODE{idx}\x00"

    text = re.sub(r"`([^`]+)`", _stash_code, text)

    # Step 2: escape XML
    text = _esc(text)

    # Step 3: bold then italic (bold first to avoid * clash)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)

    # Step 4: restore code spans
    for idx, span in enumerate(code_spans):
        text = text.replace(f"\x00CODE{idx}\x00", span)

    return text


# ── Table builder ───────────────────────────────────────────────────────────────

def _build_table(header: list[str], rows: list[list[str]]) -> Table:
    col_count = len(header)
    col_width = BODY_W / col_count

    style_h = ParagraphStyle(
        "th", fontSize=8.5, leading=11, textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    style_d = ParagraphStyle(
        "td", fontSize=8, leading=11, textColor=DARK,
        fontName="Helvetica",
    )

    def _cell(text, sty):
        return Paragraph(_inline(text), sty)

    data = [[_cell(h, style_h) for h in header]]
    for row in rows:
        # Pad short rows
        row = list(row) + [""] * (col_count - len(row))
        data.append([_cell(c, style_d) for c in row[:col_count]])

    tbl = Table(data, colWidths=[col_width] * col_count, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, BORDER),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


# ── Page template (header / footer) ────────────────────────────────────────────

def _on_page(canvas, doc):
    canvas.saveState()
    # Header rule
    canvas.setStrokeColor(BRAND)
    canvas.setLineWidth(1)
    canvas.line(L_MARGIN, PAGE_H - T_MARGIN + 4 * mm,
                PAGE_W - R_MARGIN, PAGE_H - T_MARGIN + 4 * mm)
    # Footer
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(L_MARGIN, B_MARGIN - 6 * mm,
                      "ClinicAI — Knowledge Transfer Document  |  Xccelera AI  |  2026-06-16")
    canvas.drawRightString(PAGE_W - R_MARGIN, B_MARGIN - 6 * mm,
                           f"Page {doc.page}")
    canvas.restoreState()


# ── Markdown → flowables ────────────────────────────────────────────────────────

def md_to_flowables(md_text: str, styles: dict) -> list:
    story = []
    lines = md_text.splitlines()
    i = 0
    in_code = False
    code_buf = []
    table_buf = []
    in_table = False

    def flush_table():
        nonlocal table_buf, in_table
        if not table_buf:
            return
        header = [c.strip() for c in table_buf[0].strip("|").split("|")]
        rows = []
        for row_line in table_buf[2:]:   # skip separator row
            row_line = row_line.strip()
            if not row_line or set(row_line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                continue
            rows.append([c.strip() for c in row_line.strip("|").split("|")])
        if rows:
            story.append(Spacer(1, 4))
            story.append(_build_table(header, rows))
            story.append(Spacer(1, 6))
        table_buf = []
        in_table = False

    while i < len(lines):
        line = lines[i]

        # ── Code fence ──────────────────────────────────────────────────────────
        if line.strip().startswith("```"):
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                code_text = "\n".join(code_buf)
                # Split into chunks of ~90 chars per line to avoid overflow
                for chunk_line in code_text.split("\n"):
                    story.append(Paragraph(_esc(chunk_line) or " ", styles["code_block"]))
                story.append(Spacer(1, 4))
                code_buf = []
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # ── Table ───────────────────────────────────────────────────────────────
        if line.strip().startswith("|"):
            if not in_table:
                in_table = True
                table_buf = []
            table_buf.append(line)
            i += 1
            continue
        elif in_table:
            flush_table()

        stripped = line.rstrip()

        # ── Horizontal rule ─────────────────────────────────────────────────────
        if re.match(r"^---+$", stripped):
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER))
            story.append(Spacer(1, 6))
            i += 1
            continue

        # ── Headings ────────────────────────────────────────────────────────────
        if stripped.startswith("# ") and not stripped.startswith("## "):
            flush_table()
            text = stripped[2:].strip()
            # Strip any anchor IDs like {#...}
            text = re.sub(r"\{#[^}]+\}", "", text).strip()
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1.2, color=BRAND))
            story.append(Paragraph(_inline(text), styles["h1"]))
            i += 1
            continue

        if stripped.startswith("## "):
            flush_table()
            text = stripped[3:].strip()
            text = re.sub(r"\{#[^}]+\}", "", text).strip()
            story.append(Paragraph(_inline(text), styles["h2"]))
            i += 1
            continue

        if stripped.startswith("### "):
            flush_table()
            text = stripped[4:].strip()
            story.append(Paragraph(_inline(text), styles["h3"]))
            i += 1
            continue

        if stripped.startswith("#### "):
            flush_table()
            text = stripped[5:].strip()
            story.append(Paragraph(f"<b>{_inline(text)}</b>", styles["body"]))
            i += 1
            continue

        # ── Bullet list ─────────────────────────────────────────────────────────
        m_bullet = re.match(r"^(\s*)([-*+]|\d+\.) (.+)", stripped)
        if m_bullet:
            indent_level = len(m_bullet.group(1)) // 2
            content = m_bullet.group(3)
            sty = ParagraphStyle(
                f"bullet_{indent_level}",
                parent=styles["bullet"],
                leftIndent=14 + indent_level * 12,
                bulletIndent=4 + indent_level * 12,
            )
            story.append(Paragraph(f"• {_inline(content)}", sty))
            i += 1
            continue

        # ── Blank line ──────────────────────────────────────────────────────────
        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # ── Normal paragraph ────────────────────────────────────────────────────
        story.append(Paragraph(_inline(stripped), styles["body"]))
        i += 1

    flush_table()
    return story


# ── Cover page ──────────────────────────────────────────────────────────────────

def cover_page(styles: dict) -> list:
    story = []
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("ClinicAI", styles["cover_title"]))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Knowledge Transfer Document", styles["cover_sub"]))
    story.append(Spacer(1, 1.2 * cm))
    story.append(HRFlowable(width="60%", thickness=1.5, color=BRAND, hAlign="CENTER"))
    story.append(Spacer(1, 1.2 * cm))
    story.append(Paragraph("FellowAI / ClinicAI — Xccelera AI", styles["cover_meta"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Author: Nabil Rizwan", styles["cover_meta"]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Date: 2026-06-16", styles["cover_meta"]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("Contact: dev@xccelera.ai", styles["cover_meta"]))
    story.append(PageBreak())
    return story


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    src  = Path(__file__).parent.parent / "KT_DOCUMENT.md"
    dest = Path(__file__).parent.parent / "KT_DOCUMENT.pdf"

    if not src.exists():
        print(f"ERROR: {src} not found")
        sys.exit(1)

    md_text = src.read_text(encoding="utf-8")
    styles  = _styles()

    doc = SimpleDocTemplate(
        str(dest),
        pagesize=A4,
        leftMargin=L_MARGIN,
        rightMargin=R_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN,
        title="ClinicAI — Knowledge Transfer Document",
        author="Nabil Rizwan",
        subject="ClinicAI KT",
    )

    story = cover_page(styles)
    story += md_to_flowables(md_text, styles)

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    print(f"PDF written to: {dest}")


if __name__ == "__main__":
    main()
