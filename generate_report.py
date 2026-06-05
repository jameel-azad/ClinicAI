"""
Generate ClinicAI Product Status Report PDF using ReportLab.
Run: python generate_report.py
Output: ClinicAI_Status_Report.pdf
"""

from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import PageBreak

# ── Palette ─────────────────────────────────────────────────────────────────
C_BLACK      = colors.HexColor("#111827")
C_GRAY_DARK  = colors.HexColor("#374151")
C_GRAY       = colors.HexColor("#6B7280")
C_GRAY_LIGHT = colors.HexColor("#F3F4F6")
C_BORDER     = colors.HexColor("#E5E7EB")
C_GREEN      = colors.HexColor("#16A34A")
C_GREEN_BG   = colors.HexColor("#F0FDF4")
C_BLUE       = colors.HexColor("#2563EB")
C_BLUE_BG    = colors.HexColor("#EFF6FF")
C_AMBER_BG   = colors.HexColor("#FFFBEB")
C_AMBER      = colors.HexColor("#92400E")
C_RED        = colors.HexColor("#DC2626")
C_HEADER_BG  = colors.HexColor("#1F2937")
C_WHITE      = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

# ── Styles ───────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def s(name, **kw):
    return ParagraphStyle(name, parent=styles["Normal"], **kw)

ST = {
    "cover_title":   s("cover_title",   fontSize=26, textColor=C_BLACK,     leading=32, fontName="Helvetica-Bold"),
    "cover_sub":     s("cover_sub",     fontSize=11, textColor=C_GRAY,      leading=16),
    "cover_meta":    s("cover_meta",    fontSize=8,  textColor=C_GRAY,      leading=12, alignment=TA_RIGHT),
    "section":       s("section",       fontSize=13, textColor=C_BLACK,     leading=18, fontName="Helvetica-Bold",
                                        spaceBefore=14, spaceAfter=4),
    "subsection":    s("subsection",    fontSize=10, textColor=C_GRAY_DARK, leading=14, fontName="Helvetica-Bold",
                                        spaceBefore=8, spaceAfter=2),
    "body":          s("body",          fontSize=9,  textColor=C_GRAY_DARK, leading=14),
    "body_sm":       s("body_sm",       fontSize=8,  textColor=C_GRAY,      leading=12),
    "label":         s("label",         fontSize=8,  textColor=C_BLACK,     leading=11, fontName="Helvetica-Bold"),
    "detail":        s("detail",        fontSize=8,  textColor=C_GRAY,      leading=11),
    "table_head":    s("table_head",    fontSize=8,  textColor=C_WHITE,     leading=11, fontName="Helvetica-Bold", alignment=TA_CENTER),
    "table_cell":    s("table_cell",    fontSize=8,  textColor=C_GRAY_DARK, leading=11),
    "table_cell_c":  s("table_cell_c",  fontSize=8,  textColor=C_GRAY_DARK, leading=11, alignment=TA_CENTER),
    "cost_total":    s("cost_total",    fontSize=9,  textColor=C_GREEN,     leading=12, fontName="Helvetica-Bold", alignment=TA_CENTER),
    "note":          s("note",          fontSize=8,  textColor=C_AMBER,     leading=12),
    "footer":        s("footer",        fontSize=7,  textColor=C_GRAY,      leading=10, alignment=TA_CENTER),
    "badge_done":    s("badge_done",    fontSize=7,  textColor=C_GREEN,     leading=9,  fontName="Helvetica-Bold"),
    "badge_active":  s("badge_active",  fontSize=7,  textColor=C_BLUE,      leading=9,  fontName="Helvetica-Bold"),
    "badge_planned": s("badge_planned", fontSize=7,  textColor=C_GRAY,      leading=9,  fontName="Helvetica-Bold"),
    "stat_num":      s("stat_num",      fontSize=20, textColor=C_BLACK,     leading=24, fontName="Helvetica-Bold", alignment=TA_CENTER),
    "stat_lbl":      s("stat_lbl",      fontSize=7,  textColor=C_GRAY,      leading=9,  alignment=TA_CENTER),
    "exec_body":     s("exec_body",     fontSize=9,  textColor=C_GRAY_DARK, leading=15),
}

# ── Data ─────────────────────────────────────────────────────────────────────

TODAY = datetime.now().strftime("%d %B %Y").lstrip("0")

FEATURES = [
    ("Patient Experience (WhatsApp)", [
        ("Appointment booking",          "Multi-turn conversational flow, 10-state machine, Hinglish support"),
        ("Doctor approval workflow",     "Interactive WhatsApp buttons — Approve / Reject / Suggest Time"),
        ("Consultation flow",            "Real-time session buffering with 14-phrase close detection and 30-min timeout"),
        ("Lab report submission",        "Patient sends PDF → AI extraction → abnormal flagging → doctor summary"),
        ("After-hours queue",            "Messages outside clinic hours queued and re-delivered at opening"),
        ("Emergency response",           "Instant 112 referral + broadcast alert to all configured doctors"),
        ("Appointment reminders",        "Configurable pre-appointment SMS via APScheduler"),
    ]),
    ("Clinical Intelligence", [
        ("Clinical scribe pipeline",     "Voice note → Whisper STT → SOAP generation → entity extraction → PDF"),
        ("SOAP note generation",         "4-section notes with per-section confidence scoring and missing-section alerts"),
        ("Clinical entity extraction",   "Structured symptoms, diagnoses, and medications extracted from every consultation"),
        ("HL7 FHIR R4 bundles",          "Condition + MedicationRequest resources generated per consultation"),
        ("SNOMED CT coding",             "Diagnoses and symptoms coded via local table + NLM Clinical Tables API fallback"),
        ("RxNorm coding",                "Medications coded via local table + NLM RxNav API fallback"),
        ("Lab report parsing",           "CBC / LFT / KFT / Lipid / Thyroid panel detection with abnormal/critical flagging"),
    ]),
    ("Multi-Agent Architecture", [
        ("10-intent classifier",         "6-node LangGraph pipeline; Groq LLaMA 3.3 70B primary, Gemini 2.5 Flash fallback"),
        ("RouterAgent",                  "Top-level orchestrator dispatching to 6 specialist sub-agents"),
        ("BookingAgent",                 "Full appointment lifecycle including reschedule, cancel, and status flows"),
        ("ConsultationAgent",            "Message buffering, close detection, scribe pipeline trigger"),
        ("LabAgent / FollowUpAgent",     "Lab report intake and post-consultation follow-up flows"),
        ("AfterHoursAgent / EmergencyAgent", "Out-of-hours queuing and emergency routing"),
        ("Multi-doctor support",         "14-specialty directory with symptom-based doctor matching"),
    ]),
    ("Clinic Management Dashboard", [
        ("Clinic onboarding wizard",     "5-step setup: clinic details → doctors → AI model → WhatsApp config → go-live"),
        ("Doctor management",            "Add / edit / deactivate doctors with specialty, hours, and appointment duration"),
        ("Per-clinic AI model selection","Choose LLM vendor and model per clinic; API key stored AES-128 encrypted"),
        ("Patient list",                 "Searchable patient directory with last visit date and record count"),
        ("Patient medical history",      "Full visit timeline: SOAP tabs, diagnosis chips (SNOMED), lab values"),
        ("Editable patient profile",     "Doctor-editable allergies, chronic conditions, medications, and notes"),
        ("Super-admin panel",            "Multi-tenant clinic oversight and activation management"),
    ]),
    ("Infrastructure & Data", [
        ("JWT authentication",           "7-day HS256 tokens, bcrypt passwords, role-based access control"),
        ("PostgreSQL persistence",       "6 tables: clinics, users, doctors, model_configs, patients, medical_records"),
        ("Automatic medical records",    "Every consultation close writes a structured MedicalRecord row automatically"),
        ("Redis session store",          "Active booking/consultation state with TTL management and in-memory fallback"),
        ("Weekly practice insights",     "Monday 8 AM IST report: appointment volume, no-show rate, top complaints"),
        ("Docker Compose deployment",    "PostgreSQL + Redis + FastAPI + Next.js as four containerised services"),
    ]),
]

ROADMAP = [
    ("active",  "WhatsApp Business API migration",
                "Replace Twilio with Meta WhatsApp Cloud API directly. Eliminates $0.005/msg Twilio "
                "markup — 60% messaging cost reduction. Core migration complete on whatsappmigration "
                "branch; pending Meta Developer Portal configuration and live testing.",
                "HIGH — Cost Reduction"),
    ("active",  "Meta webhook signature verification",
                "Validate X-Hub-Signature-256 on every inbound webhook to prevent message injection. "
                "Required before production go-live.",
                "HIGH — Security"),
]

# Rows shared by both scenarios
COST_ROWS_COMMON = [
    ("Groq LLaMA 3.3 70B",       "$0.59/M input · $0.79/M output",      "$0.40", "$2.00", "$8.00"),
    ("Groq Whisper Turbo (STT)", "$0.04/hr audio (10-sec minimum)",      "$0.20", "$1.00", "$4.00"),
    ("PostgreSQL — Neon",        "Free: 100 CU-hrs · Launch: $0.106/CU-hr", "$0",  "$5",   "$19"),
    ("Redis — Upstash",          "Free 500K cmds/mo · $0.20/100K after", "$0",    "$0",    "$10"),
    ("API Hosting — Railway",    "$5/mo Hobby · $20/mo Pro",             "$5",    "$10",   "$25"),
    ("Dashboard — Vercel",       "Hobby free · Pro $20/user/mo",         "$0",    "$0",    "$20"),
]

# Twilio scenario
COST_ROWS_TWILIO = COST_ROWS_COMMON[:2] + [
    ("Twilio — WhatsApp msgs",   "$0.005/msg Twilio + $0.0034/msg Meta = $0.0084/msg", "$17", "$84", "$336"),
    ("Twilio Phone Number",      "$1/number/mo",                         "$1",    "$1",    "$3"),
] + COST_ROWS_COMMON[2:]
TOTAL_TWILIO  = ("$24",  "$102", "$392")
PER_PT_TWILIO = ("$0.24","$0.20","$0.20")

# Meta direct scenario (current)
COST_ROWS_META = COST_ROWS_COMMON[:2] + [
    ("Meta WhatsApp (India)",    "Utility ~$0.0014 · Service FREE · Mktg ~$0.0107", "$3", "$12", "$45"),
] + COST_ROWS_COMMON[2:]
TOTAL_META  = ("$9",   "$30",  "$131")
PER_PT_META = ("$0.09","$0.06","$0.07")

# ── Builder helpers ───────────────────────────────────────────────────────────

def hr(color=C_BORDER, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=4, spaceBefore=4)

def vspace(n=6):
    return Spacer(1, n)

def feature_table(items):
    data = []
    for label, detail in items:
        data.append([
            Paragraph("✓", s("tick", fontSize=8, textColor=C_GREEN, fontName="Helvetica-Bold")),
            Paragraph(label, ST["label"]),
            Paragraph(detail, ST["detail"]),
        ])
    t = Table(data, colWidths=[8*mm, 52*mm, 110*mm])
    t.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [C_WHITE, C_GRAY_LIGHT]),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, C_BORDER),
        ("ROUNDEDCORNERS", [3]),
    ]))
    return t

def roadmap_table(items):
    data = [
        [
            Paragraph("Status", ST["table_head"]),
            Paragraph("Item", ST["table_head"]),
            Paragraph("Detail", ST["table_head"]),
            Paragraph("Priority", ST["table_head"]),
        ]
    ]
    for status, label, detail, priority in items:
        if status == "active":
            badge = Paragraph("● IN PROGRESS", ST["badge_active"])
        else:
            badge = Paragraph("○ PLANNED", ST["badge_planned"])
        data.append([
            badge,
            Paragraph(label, ST["label"]),
            Paragraph(detail, ST["detail"]),
            Paragraph(priority, ST["body_sm"]),
        ])
    t = Table(data, colWidths=[22*mm, 42*mm, 86*mm, 20*mm])
    style = [
        ("BACKGROUND",   (0, 0), (-1, 0),  C_HEADER_BG),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  C_WHITE),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, C_BORDER),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_GRAY_LIGHT]),
    ]
    for i, (status, *_) in enumerate(items, 1):
        if status == "active":
            style.append(("BACKGROUND", (0, i), (-1, i), C_BLUE_BG))
    t.setStyle(TableStyle(style))
    return t

def cost_table(rows, totals, per_patient, total_color=C_GREEN):
    header = [
        Paragraph("Service", ST["table_head"]),
        Paragraph("Starter\n100 patients", ST["table_head"]),
        Paragraph("Growth\n500 patients", ST["table_head"]),
        Paragraph("Scale\n2,000 patients", ST["table_head"]),
        Paragraph("Pricing Basis", ST["table_head"]),
    ]
    data = [header]
    for svc, basis, s_, g, sc in rows:
        data.append([
            Paragraph(svc, ST["label"]),
            Paragraph(s_, ST["table_cell_c"]),
            Paragraph(g,  ST["table_cell_c"]),
            Paragraph(sc, ST["table_cell_c"]),
            Paragraph(basis, ST["detail"]),
        ])
    total_style = s("tot_c", fontSize=9, textColor=total_color, leading=12, fontName="Helvetica-Bold", alignment=TA_CENTER)
    data.append([
        Paragraph("Total / month", s("tot_lbl", fontSize=9, textColor=C_BLACK, fontName="Helvetica-Bold")),
        Paragraph(totals[0], total_style),
        Paragraph(totals[1], total_style),
        Paragraph(totals[2], total_style),
        Paragraph("excl. domain, SSL & GST", ST["detail"]),
    ])
    data.append([
        Paragraph("Cost per patient", ST["body_sm"]),
        Paragraph(per_patient[0], ST["table_cell_c"]),
        Paragraph(per_patient[1], ST["table_cell_c"]),
        Paragraph(per_patient[2], ST["table_cell_c"]),
        Paragraph("flat across tiers", ST["detail"]),
    ])
    t = Table(data, colWidths=[46*mm, 20*mm, 20*mm, 22*mm, 62*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  C_HEADER_BG),
        ("BACKGROUND",    (0, -2), (-1, -2), C_GREEN_BG),
        ("BACKGROUND",    (0, -1), (-1, -1), C_GRAY_LIGHT),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0),  (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 4),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 5),
        ("BOX",           (0, 0),  (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0),  (-1, -1), 0.3, C_BORDER),
        ("ROWBACKGROUNDS",(0, 1),  (-1, -3), [C_WHITE, C_GRAY_LIGHT]),
        ("LINEABOVE",     (0, -2), (-1, -2), 1.5, C_GREEN),
    ]))
    return t


def savings_table():
    """Side-by-side savings comparison."""
    header = [
        Paragraph("Tier", ST["table_head"]),
        Paragraph("With Twilio", ST["table_head"]),
        Paragraph("Meta Direct\n(current)", ST["table_head"]),
        Paragraph("Monthly Saving", ST["table_head"]),
        Paragraph("Annual Saving", ST["table_head"]),
    ]
    rows = [
        ("Starter (100 patients)",  "$24",  "$9",   "$15",   "$180"),
        ("Growth  (500 patients)",  "$102", "$30",  "$72",   "$864"),
        ("Scale (2,000 patients)",  "$392", "$131", "$261",  "$3,132"),
    ]
    saving_style = s("sav", fontSize=9, textColor=C_GREEN, leading=12,
                     fontName="Helvetica-Bold", alignment=TA_CENTER)
    data = [header]
    for tier, twilio, meta, mo, yr in rows:
        data.append([
            Paragraph(tier,   ST["table_cell"]),
            Paragraph(twilio, ST["table_cell_c"]),
            Paragraph(meta,   ST["table_cell_c"]),
            Paragraph(mo,     saving_style),
            Paragraph(yr,     saving_style),
        ])
    t = Table(data, colWidths=[52*mm, 24*mm, 28*mm, 28*mm, 28*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  C_HEADER_BG),
        ("BACKGROUND",    (3, 1),  (-1, -1), C_GREEN_BG),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 5),
        ("BOX",           (0, 0),  (-1, -1), 0.5, C_BORDER),
        ("INNERGRID",     (0, 0),  (-1, -1), 0.3, C_BORDER),
        ("ROWBACKGROUNDS",(0, 1),  (2, -1),  [C_WHITE, C_GRAY_LIGHT]),
    ]))
    return t

def stat_box(num, label):
    data = [[Paragraph(num, ST["stat_num"])], [Paragraph(label, ST["stat_lbl"])]]
    t = Table(data, colWidths=[38*mm])
    t.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5, C_BORDER),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("BACKGROUND",   (0, 0), (-1, -1), C_WHITE),
    ]))
    return t

# ── Page template (header/footer on each page) ────────────────────────────────

def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(C_GRAY)
    canvas.drawString(MARGIN, 12*mm, f"ClinicAI · Product Status Report · {TODAY} · Confidential")
    canvas.drawRightString(w - MARGIN, 12*mm, f"Page {doc.page}")
    # Top rule on non-first pages
    if doc.page > 1:
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, h - 14*mm, w - MARGIN, h - 14*mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(C_GRAY)
        canvas.drawString(MARGIN, h - 11*mm, "ClinicAI — Product Status Report")
    canvas.restoreState()

# ── Build ─────────────────────────────────────────────────────────────────────

def build():
    out = "ClinicAI_Status_Report_v2.pdf"
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20*mm, bottomMargin=20*mm,
        title="ClinicAI Product Status Report",
        author="ClinicAI Engineering",
        subject="Product Status Report",
    )

    story = []

    # ── Cover ──────────────────────────────────────────────────────────────
    story.append(vspace(8))
    story.append(Paragraph("PRODUCT STATUS REPORT", s("label_upper", fontSize=8, textColor=C_GRAY,
                                                        fontName="Helvetica-Bold",
                                                        letterSpacing=2)))
    story.append(vspace(4))
    story.append(Paragraph("ClinicAI", ST["cover_title"]))
    story.append(Paragraph("WhatsApp-native clinic management &amp; clinical AI platform", ST["cover_sub"]))
    story.append(vspace(3))
    story.append(Paragraph(f"{TODAY} &nbsp;·&nbsp; Version 4.0.0 &nbsp;·&nbsp; Branch: whatsappmigration",
                            ST["cover_meta"]))
    story.append(vspace(8))
    story.append(hr(C_BLACK, 1))
    story.append(vspace(8))

    # Stats row
    stats = [
        stat_box("39",    "Features Complete"),
        stat_box("8",     "Roadmap Items"),
        stat_box("6",     "Database Tables"),
        stat_box("$0.07", "Cost / Patient / Mo"),
    ]
    stats_table = Table([stats], colWidths=[38*mm]*4, hAlign="LEFT",
                        spaceBefore=0, spaceAfter=0)
    stats_table.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(stats_table)
    story.append(vspace(14))

    # ── Executive Summary ─────────────────────────────────────────────────
    story.append(Paragraph("Executive Summary", ST["section"]))
    story.append(hr())
    story.append(vspace(4))
    story.append(Paragraph(
        "ClinicAI is a production-ready WhatsApp-native clinic assistant that automates the full patient "
        "lifecycle — from appointment booking through real-time consultation, clinical documentation, and "
        "post-visit follow-up — entirely over WhatsApp. Doctors manage their practice via a companion web "
        "dashboard. Every consultation automatically generates a structured SOAP note coded with SNOMED CT "
        "and RxNorm, stored as a persistent medical record, and packaged as an HL7 FHIR R4 Bundle. The "
        "platform is multi-tenant, supports per-clinic AI model selection, and is built for cost efficiency "
        "at approximately <b>$0.07 per patient per month</b> at scale.",
        ST["exec_body"]
    ))
    story.append(vspace(6))
    story.append(Paragraph(
        "The current sprint focus is migrating the WhatsApp messaging layer from Twilio to the Meta "
        "WhatsApp Cloud API directly. Combined with India's updated Jan 2026 per-message rates "
        "(utility: ~$0.0014, service window: FREE), this reduces effective messaging cost by ~82% vs "
        "Twilio — bringing the Growth tier from $107/mo to $30/mo. The core migration is complete on "
        "the <i>whatsappmigration</i> branch and is pending production configuration and live testing.",
        ST["exec_body"]
    ))
    story.append(vspace(10))

    # ── Feature Sections ─────────────────────────────────────────────────
    story.append(Paragraph("Current Features", ST["section"]))
    story.append(hr())

    for i, (category, items) in enumerate(FEATURES):
        block = [
            vspace(8),
            Paragraph(category, ST["subsection"]),
            vspace(3),
            feature_table(items),
        ]
        story.append(KeepTogether(block))

    story.append(PageBreak())

    # ── Roadmap ───────────────────────────────────────────────────────────
    story.append(Paragraph("Roadmap", ST["section"]))
    story.append(hr())
    story.append(vspace(4))
    story.append(Paragraph(
        "Items currently in progress and planned for upcoming sprints. "
        "Blue rows are actively being worked on.",
        ST["body_sm"]
    ))
    story.append(vspace(6))
    story.append(roadmap_table(ROADMAP))
    story.append(vspace(14))

    # ── Cost Breakdown ────────────────────────────────────────────────────
    story.append(Paragraph("Infrastructure Cost Breakdown", ST["section"]))
    story.append(hr())
    story.append(vspace(4))
    story.append(Paragraph(
        "Monthly estimates in USD based on June 2026 published rates. "
        "All prices excl. 18% GST on Meta WhatsApp charges (India). "
        "Two scenarios shown: current Twilio setup vs migration to Meta Cloud API directly.",
        ST["body_sm"]
    ))
    story.append(vspace(10))

    # Twilio scenario
    story.append(Paragraph("Option A — With Twilio (current setup)", ST["subsection"]))
    story.append(vspace(4))
    story.append(cost_table(COST_ROWS_TWILIO, TOTAL_TWILIO, PER_PT_TWILIO, total_color=C_GRAY_DARK))
    story.append(vspace(12))

    # Meta direct scenario
    story.append(Paragraph("Option B — Meta WhatsApp Cloud API direct (migration in progress)", ST["subsection"]))
    story.append(vspace(4))
    story.append(cost_table(COST_ROWS_META, TOTAL_META, PER_PT_META, total_color=C_GREEN))
    story.append(vspace(12))

    # Savings comparison
    story.append(Paragraph("Cost Saving Summary — Twilio vs Meta Direct", ST["subsection"]))
    story.append(vspace(4))
    story.append(savings_table())
    story.append(vspace(10))

    # Note box
    note_data = [[
        Paragraph(
            "<b>WhatsApp India pricing (updated Jan 2026):</b> Meta per-message pricing applies. "
            "Utility messages (confirmations, SOAP delivery): ~$0.0014/msg. "
            "Service messages within a 24-hr customer window: FREE — covers most consultation replies. "
            "Marketing (reminders, insights): ~$0.0107/msg. Add 18% GST on all Meta charges for India. "
            "No BSP markup — direct Meta Cloud API. Effective blended rate for ClinicAI: ~$0.0015/msg vs Twilio $0.0084/msg (82% saving).",
            ST["note"]
        )
    ]]
    note_t = Table(note_data, colWidths=[170*mm])
    note_t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, -1), C_AMBER_BG),
        ("BOX",          (0, 0), (-1, -1), 0.5, colors.HexColor("#F59E0B")),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(note_t)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"OK Generated: {out}")

if __name__ == "__main__":
    build()
