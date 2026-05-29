"""
Generates updated ClinicAI Demo0 evaluation PDF with WhatsApp Business API cost section.
Fixes: ₹ symbol via Arial TTF + white text in dark total rows.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
    Table, TableStyle, HRFlowable, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Register Arial TTF (supports ₹ and full Unicode) ─────────────────────────
pdfmetrics.registerFont(TTFont("Arial",      r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic",r"C:\Windows\Fonts\ariali.ttf"))

# ── Palette ───────────────────────────────────────────────────────────────────
DARK_GREEN  = colors.HexColor("#1A3C34")
MED_GREEN   = colors.HexColor("#2D6A4F")
LIGHT_GREEN = colors.HexColor("#D8F3DC")
TABLE_DARK  = colors.HexColor("#1A1A2E")
TABLE_ALT   = colors.HexColor("#F5F5F5")
TABLE_BORDER= colors.HexColor("#CCCCCC")
WHITE       = colors.white
BLACK       = colors.HexColor("#1A1A1A")
GREY        = colors.HexColor("#666666")
GOLD        = colors.HexColor("#F4A261")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CW = PAGE_W - 2 * MARGIN


# ── Styles ────────────────────────────────────────────────────────────────────
def make_styles():
    s = {}
    base = dict(fontName="Arial", fontSize=10, textColor=BLACK, leading=15)
    bold = dict(fontName="Arial-Bold")
    ital = dict(fontName="Arial-Italic")

    s["doc_title"] = ParagraphStyle("doc_title", **{**base, **bold,
        "fontSize": 19, "textColor": WHITE, "alignment": TA_CENTER, "leading": 24})
    s["intro"] = ParagraphStyle("intro", **{**base,
        "leading": 16, "spaceAfter": 6, "alignment": TA_JUSTIFY})
    s["sec_label"] = ParagraphStyle("sec_label", **{**base, **bold,
        "fontSize": 11, "textColor": WHITE})
    s["sec_title"] = ParagraphStyle("sec_title", **{**base, **bold,
        "fontSize": 13, "textColor": WHITE})
    s["sub_header"] = ParagraphStyle("sub_header", **{**base, **bold,
        "fontSize": 11, "textColor": MED_GREEN, "spaceBefore": 10, "spaceAfter": 4})
    s["body"] = ParagraphStyle("body", **{**base,
        "leading": 16, "spaceAfter": 5, "alignment": TA_JUSTIFY})
    s["bullet"] = ParagraphStyle("bullet", **{**base,
        "leftIndent": 14, "spaceAfter": 3, "leading": 15})
    s["table_hdr"] = ParagraphStyle("table_hdr", **{**base, **bold,
        "fontSize": 9, "textColor": WHITE})
    s["table_body"] = ParagraphStyle("table_body", **{**base,
        "fontSize": 9, "leading": 13})
    s["table_body_bold"] = ParagraphStyle("table_body_bold", **{**base, **bold,
        "fontSize": 9, "leading": 13})
    s["table_body_green"] = ParagraphStyle("table_body_green", **{**base, **bold,
        "fontSize": 9, "textColor": MED_GREEN, "leading": 13})
    # White text for dark-background total rows
    s["total_white"] = ParagraphStyle("total_white", **{**base, **bold,
        "fontSize": 9, "textColor": WHITE, "leading": 13})
    s["total_gold"] = ParagraphStyle("total_gold", **{**base, **bold,
        "fontSize": 9, "textColor": GOLD, "leading": 13})
    s["insight_label"] = ParagraphStyle("insight_label", **{**base, **bold,
        "fontSize": 9, "textColor": WHITE, "alignment": TA_CENTER})
    s["insight_body"] = ParagraphStyle("insight_body", **{**base,
        "fontSize": 9.5, "leading": 15, "alignment": TA_JUSTIFY})
    s["note"] = ParagraphStyle("note", **{**base, **ital,
        "fontSize": 8.5, "textColor": GREY, "leading": 13, "spaceBefore": 4})
    return s


S = make_styles()


# ── Reusable builders ─────────────────────────────────────────────────────────
def p(text, style="body"):
    return Paragraph(text, S[style])

def sp(h=4):
    return Spacer(1, h * mm)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER)

def bullet(text):
    return Paragraph(f"• {text}", S["bullet"])

def title_block():
    t = Table([[p("ClinicAI — Post-Demo Feedback & Action Plan", "doc_title")]],
              colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), DARK_GREEN),
        ("PADDING",    (0,0), (-1,-1), 14),
    ]))
    return t

def section_header(num, title):
    nw = 22 * mm
    t = Table([[p(str(num), "sec_label"), p(title, "sec_title")]],
              colWidths=[nw, CW - nw])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,0), MED_GREEN),
        ("BACKGROUND", (1,0), (1,0), DARK_GREEN),
        ("PADDING",    (0,0), (-1,-1), 8),
        ("ALIGN",      (0,0), (0,0), "CENTER"),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ]))
    return t

def dark_table(header_row, data_rows, col_widths):
    """Standard table: dark header, alternating white/grey rows."""
    all_rows = [header_row] + data_rows
    t = Table(all_rows, colWidths=col_widths)
    style = [
        ("BACKGROUND", (0,0), (-1,0), TABLE_DARK),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("PADDING",    (0,0), (-1,-1), 6),
        ("VALIGN",     (0,0), (-1,-1), "TOP"),
        ("BOX",        (0,0), (-1,-1), 0.5, TABLE_BORDER),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, TABLE_BORDER),
    ]
    for i in range(1, len(all_rows)):
        bg = TABLE_ALT if i % 2 == 0 else WHITE
        style.append(("BACKGROUND", (0,i), (-1,i), bg))
    t.setStyle(TableStyle(style))
    return t

def cost_table(header_row, data_rows, total_row, col_widths):
    """Table with dark header, alternating rows, and a dark TOTAL row with white/gold text."""
    all_rows = [header_row] + data_rows + [total_row]
    t = Table(all_rows, colWidths=col_widths)
    style = [
        # Header
        ("BACKGROUND", (0,0), (-1,0), TABLE_DARK),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("PADDING",    (0,0), (-1,-1), 6),
        ("VALIGN",     (0,0), (-1,-1), "TOP"),
        ("BOX",        (0,0), (-1,-1), 0.5, TABLE_BORDER),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, TABLE_BORDER),
        # Total row
        ("BACKGROUND", (0,-1), (-1,-1), TABLE_DARK),
    ]
    for i in range(1, len(data_rows) + 1):
        bg = TABLE_ALT if i % 2 == 0 else WHITE
        style.append(("BACKGROUND", (0,i), (-1,i), bg))
    t.setStyle(TableStyle(style))
    return t

def two_col_table(rows, col_widths):
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), LIGHT_GREEN),
        ("FONTSIZE",   (0,0), (-1,-1), 9.5),
        ("PADDING",    (0,0), (-1,-1), 7),
        ("VALIGN",     (0,0), (-1,-1), "TOP"),
        ("BOX",        (0,0), (-1,-1), 0.5, TABLE_BORDER),
        ("INNERGRID",  (0,0), (-1,-1), 0.3, TABLE_BORDER),
    ]))
    return t

def key_insight(text):
    lw = 22 * mm
    t = Table([[p("Key\nInsight", "insight_label"), p(text, "insight_body")]],
              colWidths=[lw, CW - lw])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,0), MED_GREEN),
        ("BACKGROUND", (1,0), (1,0), LIGHT_GREEN),
        ("PADDING",    (0,0), (-1,-1), 9),
        ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
        ("BOX",        (0,0), (-1,-1), 0.5, MED_GREEN),
    ]))
    return t


# ══════════════════════════════════════════════════════════════════════════════
# SECTIONS
# ══════════════════════════════════════════════════════════════════════════════

def build_section1(story):
    story.append(section_header(1, "SNOMED / HL7 Benchmark for Prescriptions"))
    story.append(sp(6))
    story.append(p("What Was Asked", "sub_header"))
    story.append(p("Prescriptions generated by the AI engine must be validated against SNOMED CT "
                   "and HL7 FHIR standards before they are forwarded to the doctor for final review. "
                   "Only after the doctor approves the standardised prescription should it be sent "
                   "to the patient."))
    story.append(sp(4))
    story.append(p("What This Means", "sub_header"))
    story.append(p("Currently, ClinicAI generates a free-text SOAP note and a PDF. The feedback "
                   "is asking us to add one of these two layers of clinical interoperability compliance:"))
    story.append(sp(3))
    story.append(two_col_table([
        [p("SNOMED CT", "table_body_green"),
         p("A global clinical terminology standard. Every diagnosis, symptom, and medication in "
           "the prescription must be mapped to an official SNOMED concept ID before it is "
           "considered clinically valid.", "table_body")],
        [p("HL7 FHIR", "table_body_green"),
         p("Health Level 7 — Fast Healthcare Interoperability Resources. The prescription must "
           "be serialised as a FHIR MedicationRequest resource so it can be read by any EHR "
           "or pharmacy system, not just ClinicAI.", "table_body")],
    ], [CW * 0.18, CW * 0.82]))
    story.append(sp(5))
    story.append(p("Revised Prescription Pipeline", "sub_header"))
    story.append(p("The updated flow adds two new nodes to the existing LangGraph pipeline:"))
    story.append(sp(3))
    hdr = [p("", "table_hdr"), p("Node", "table_hdr"), p("What It Does", "table_hdr")]
    rows = [
        [p("1","table_body"), p("transcribe_node","table_body"),
         p("Groq Whisper — voice note → raw transcript","table_body")],
        [p("2","table_body"), p("soap_generator_node","table_body"),
         p("LLaMA 3.3 70B — transcript → structured SOAP JSON","table_body")],
        [p("3","table_body"), p("grounding_check_node","table_body"),
         p("Verify every SOAP sentence against transcript (existing)","table_body")],
        [p("4","table_body"), p("snomed_mapping_node ★","table_body_green"),
         p("Extract drug names & diagnoses → map to SNOMED CT concept IDs via FHIR Terminology API","table_body")],
        [p("5","table_body"), p("fhir_bundle_node ★","table_body_green"),
         p("Serialise prescription as HL7 FHIR MedicationRequest + Condition resources","table_body")],
        [p("6","table_body"), p("pdf_output_node","table_body"),
         p("Generate PDF — now includes SNOMED codes + FHIR bundle reference","table_body")],
        [p("7","table_body"), p("doctor_approval","table_body"),
         p("Doctor reviews standardised prescription on WhatsApp — Approve / Reject","table_body")],
        [p("8","table_body"), p("patient_delivery","table_body"),
         p("Approved FHIR-compliant prescription PDF sent to patient","table_body")],
    ]
    story.append(dark_table(hdr, rows, [CW*0.06, CW*0.27, CW*0.67]))
    story.append(sp(3))
    story.append(p("★ = new nodes to be added", "note"))
    story.append(sp(5))
    story.append(p("APIs / Tools to Use", "sub_header"))
    for b in [
        "FHIR Terminology Server (NLM / HAPI FHIR) — free SNOMED CT lookup API",
        "RxNorm API (NIH) — maps drug trade names to standard identifiers",
        "Google Cloud Healthcare FHIR API — for FHIR resource storage if needed",
        "Existing Groq LLaMA 3.3 70B — extract drug name + dosage + indication from SOAP Plan section",
    ]:
        story.append(bullet(b))


def build_section2(story):
    story.append(sp(8)); story.append(hr()); story.append(sp(6))
    story.append(section_header(2, "Executables — Doctor & Patient UX Flows"))
    story.append(sp(6))
    story.append(p("What Was Asked", "sub_header"))
    story.append(p("Provide concrete executable walkthroughs showing exactly how the doctor uses "
                   "ClinicAI and how the patient uses ClinicAI — step by step, screen by screen "
                   "(or message by message), covering every interaction point."))
    story.append(sp(5))
    story.append(p("Doctor Flow — Step by Step", "sub_header"))
    hdr = [p("Step","table_hdr"), p("What Happens","table_hdr")]
    rows = [
        [p("Step 1 — Setup","table_body"),
         p("Doctor registers their WhatsApp number. ClinicAI sends a welcome message with a short onboarding guide (under 2 minutes to read).","table_body")],
        [p("Step 2 — Receive Booking","table_body"),
         p("Patient books an appointment. Doctor receives a WhatsApp message: 'New booking: Ramesh Kumar, 14 May 2026, 11:00 AM. [APPROVE] [REJECT] [SUGGEST TIME]'","table_body")],
        [p("Step 3 — One-Tap Approve","table_body"),
         p("Doctor taps Approve. Patient is automatically notified. Appointment is logged.","table_body")],
        [p("Step 4 — Voice Note","table_body"),
         p("After consultation, doctor records a WhatsApp voice note (30–90 seconds) describing the encounter in English or Hinglish.","table_body")],
        [p("Step 5 — Review PDF","table_body"),
         p("~30 seconds later, doctor receives the SOAP note PDF on WhatsApp. They read it and reply 'APPROVE [prescription ID]' or 'REJECT [reason]'.","table_body")],
        [p("Step 6 — Lab Report ACK","table_body"),
         p("When a patient uploads a lab report, doctor receives the AI summary + original PDF. Doctor replies 'OK [lab ID]' to acknowledge.","table_body")],
        [p("Step 7 — That's It","table_body"),
         p("No app downloads. No logins. No portal. Everything happens in the same WhatsApp thread the doctor already uses.","table_body")],
    ]
    story.append(dark_table(hdr, rows, [CW*0.28, CW*0.72]))
    story.append(sp(6))
    story.append(p("Patient Flow — Step by Step", "sub_header"))
    hdr2 = [p("Step","table_hdr"), p("What Happens","table_hdr")]
    rows2 = [
        [p("Step 1 — Book","table_body"),
         p("Patient messages the clinic WhatsApp number in English, Hindi, or Hinglish: 'I want to book an appointment with Dr. Mehta tomorrow morning.' AI collects name and preferred time through natural conversation.","table_body")],
        [p("Step 2 — Confirmation","table_body"),
         p("Once doctor approves, patient receives: 'Your appointment with Dr. Mehta is confirmed for 15 May 2026 at 11:00 AM. We will send you a reminder.'","table_body")],
        [p("Step 3 — Reminder","table_body"),
         p("Patient receives an automatic WhatsApp reminder before the appointment. No action needed.","table_body")],
        [p("Step 4 — Prescription","table_body"),
         p("After the consultation, the doctor approves the AI-generated prescription. Patient receives the PDF directly on WhatsApp.","table_body")],
        [p("Step 5 — Lab Report","table_body"),
         p("Patient forwards their lab report PDF to the clinic WhatsApp number. AI processes it and notifies the doctor. Patient receives 'Dr. Mehta has reviewed your lab report' once acknowledged.","table_body")],
        [p("Step 6 — Cancellation","table_body"),
         p("Patient messages 'Cancel my appointment'. AI confirms the cancellation and notifies the doctor.","table_body")],
    ]
    story.append(dark_table(hdr2, rows2, [CW*0.28, CW*0.72]))


def build_section3(story):
    story.append(sp(8)); story.append(hr()); story.append(sp(6))
    story.append(section_header(3, "Cost Analysis — AI Engine & Full Setup"))
    story.append(sp(6))

    story.append(p("What Was Asked", "sub_header"))
    story.append(p("Provide a clear cost breakdown of running the ClinicAI AI engine and the full "
                   "infrastructure for a real clinic — covering API costs, hosting, and messaging. "
                   "<b>This section has been updated to reflect production deployment using the "
                   "WhatsApp Business API (Meta Cloud API) directly, replacing the Twilio sandbox "
                   "used during demo.</b>"))
    story.append(sp(5))

    story.append(p("Assumptions for Cost Model", "sub_header"))
    for b in [
        "1 doctor, 1 clinic",
        "30 appointments per day, ~600 per month",
        "20 voice notes per day (not every appointment generates a prescription), ~400 per month",
        "50 lab reports per month",
        "Average voice note duration: 60 seconds",
        "Average lab report: 3 pages PDF",
    ]:
        story.append(bullet(b))
    story.append(sp(5))

    # Pricing model
    story.append(p("WhatsApp Business API — Pricing Model (Meta Cloud API)", "sub_header"))
    story.append(p("The WhatsApp Business API charges per <b>conversation</b> (a 24-hour window "
                   "of messages with one user), not per individual message. This makes long "
                   "multi-message exchanges significantly cheaper than per-message billing."))
    story.append(sp(3))
    phdr = [p("Category","table_hdr"), p("India Rate","table_hdr"), p("Notes","table_hdr")]
    prows = [
        [p("Utility conversations","table_body"),
         p("₹0.33 / conversation (~$0.004)","table_body"),
         p("Transactional templates: confirmations, reminders, prescriptions, follow-ups","table_body")],
        [p("Service conversations","table_body"),
         p("FREE — first 1,000/month; ₹0.18 after","table_body"),
         p("Patient-initiated messages — booking inquiries, follow-up replies, lab uploads","table_body")],
        [p("Marketing conversations","table_body"),
         p("₹0.58 / conversation","table_body"),
         p("Not used by ClinicAI — all outbound messages are utility or free service","table_body")],
        [p("Platform access fee","table_body"),
         p("₹0 / month","table_body"),
         p("Meta Cloud API is free to access; pay only per conversation","table_body")],
        [p("One-time setup","table_body"),
         p("₹0","table_body"),
         p("Verified Facebook Business Manager + phone number registration — both free","table_body")],
    ]
    story.append(dark_table(phdr, prows, [CW*0.28, CW*0.28, CW*0.44]))
    story.append(sp(5))

    # Conversation volume
    story.append(p("Monthly Conversation Volume — 1 Clinic", "sub_header"))
    story.append(p("Each row below represents one ClinicAI workflow and the number of unique "
                   "24-hour conversation windows it opens per month."))
    story.append(sp(3))

    vhdr = [p("Workflow","table_hdr"), p("Type","table_hdr"),
            p("Conversations/Month","table_hdr"), p("Monthly Cost","table_hdr")]
    vrows = [
        [p("Appointment confirmations","table_body"), p("Utility","table_body"),
         p("600","table_body"), p("₹198.00","table_body")],
        [p("Appointment reminders (sent day before)","table_body"), p("Utility","table_body"),
         p("~500","table_body"), p("₹165.00","table_body")],
        [p("Prescription PDF delivery to patient","table_body"), p("Utility","table_body"),
         p("400","table_body"), p("₹132.00","table_body")],
        [p("Follow-up check-in messages","table_body"), p("Utility","table_body"),
         p("200","table_body"), p("₹66.00","table_body")],
        [p("Lab report patient acknowledgments","table_body"), p("Utility","table_body"),
         p("50","table_body"), p("₹16.50","table_body")],
        [p("Doctor-side notifications (1 doctor ~30 windows/month)","table_body"), p("Utility","table_body"),
         p("30","table_body"), p("₹9.90","table_body")],
        [p("Patient-initiated (bookings, queries, lab uploads)","table_body"), p("Service","table_body"),
         p("~900","table_body"), p("₹0  (free tier)","table_body")],
    ]
    vtotal = [p("TOTAL","total_white"), p("","total_white"),
              p("~1,780 conversations","total_white"), p("₹587.40","total_gold")]
    story.append(KeepTogether(cost_table(vhdr, vrows, vtotal, [CW*0.40, CW*0.14, CW*0.23, CW*0.23])))
    story.append(sp(5))

    # Monthly cost breakdown
    story.append(p("Monthly Cost Breakdown — Production (1 Clinic)", "sub_header"))
    chdr = [p("Component","table_hdr"), p("Detail","table_hdr"), p("Est. Cost / Month","table_hdr")]
    crows = [
        [p("Groq — Whisper","table_body"),
         p("400 voice notes × ~60s avg. Groq Whisper is currently free in beta; "
           "est. at $0.001/min post-pricing","table_body"),
         p("~$0.40  (~₹33)","table_body")],
        [p("Groq — LLaMA 3.3 70B","table_body"),
         p("SOAP generation + FHIR coding + grounding check + intent detection. "
           "~1,400 LLM calls × ~800 tokens avg = ~1.1M tokens","table_body"),
         p("~$0.90  (~₹75)","table_body")],
        [p("WhatsApp Business API\n(Meta Cloud — Production)","table_body"),
         p("~1,780 utility conversations/month (confirmations, reminders, prescriptions, "
           "follow-ups, lab acks). Patient-initiated conversations: FREE (under 1,000/month "
           "free tier). See conversation breakdown above.","table_body"),
         p("~₹587  (~$7)","table_body")],
        [p("Cloud Hosting (FastAPI)","table_body"),
         p("1 vCPU, 2GB RAM on Railway / Render paid tier — required for production "
           "webhook reliability","table_body"),
         p("~$7  (~₹580)","table_body")],
        [p("PDF Storage","table_body"),
         p("SOAP PDFs + lab reports. ~450 files/month × avg 200KB = ~90MB. "
           "S3 / Cloudflare R2 free tier","table_body"),
         p("~$0","table_body")],
        [p("Domain + SSL","table_body"),
         p("Custom domain for webhook endpoint (e.g. Namecheap + Cloudflare)","table_body"),
         p("~$1  (~₹83)","table_body")],
        [p("WhatsApp Business API\nOne-time Setup","table_body"),
         p("Verified Facebook Business Manager account + phone number registration. "
           "No platform fee. No BSP subscription.","table_body"),
         p("₹0  (free)","table_body")],
    ]
    ctotal = [p("TOTAL","total_white"),
              p("For ~1,050 interactions/month (production scale, 1 clinic)","total_white"),
              p("~₹900–1,000/month\n(~$11–12)","total_gold")]
    story.append(KeepTogether(cost_table(chdr, crows, ctotal, [CW*0.28, CW*0.49, CW*0.23])))
    story.append(sp(4))
    story.append(p(
        "<b>Note on production vs sandbox pricing:</b> The original demo estimate (₹345 for "
        "messaging) used Twilio sandbox rates, which do not reflect production WhatsApp "
        "Business API conversation fees. In production, Twilio WABA adds a per-message "
        "markup of ~$0.005/message on top of Meta's conversation fees, making production "
        "Twilio cost approximately ₹1,700–2,000/month for the same volume. The Meta Cloud "
        "API direct approach at ₹587/month is <b>65–70% cheaper</b> than production Twilio.",
        "note"))
    story.append(sp(5))

    # Scale table
    story.append(p("Cost at Scale — 10 Clinics", "sub_header"))
    shdr = [p("Component","table_hdr"), p("Detail","table_hdr"), p("Est. Cost / Month","table_hdr")]
    srows = [
        [p("Groq (Whisper + LLM)","table_body"),
         p("10× volume — ~14,000 LLM calls, ~4,000 voice notes. Still within "
           "Groq's competitive pricing tier.","table_body"),
         p("~$13  (~₹1,079)","table_body")],
        [p("WhatsApp Business API\n(Meta Cloud)","table_body"),
         p("~17,800 utility conversations (10 clinics × 1,780). Service conversations: "
           "~9,000/month after 1,000 free threshold = 8,000 × ₹0.18.","table_body"),
         p("~₹7,314  (~$88)","table_body")],
        [p("Cloud Hosting","table_body"),
         p("Upgrade to 2 vCPU / 4GB RAM (e.g. Railway Pro or AWS t3.small). "
           "Single deployment serves all 10 clinics.","table_body"),
         p("~$20  (~₹1,660)","table_body")],
        [p("Monitoring & Logging","table_body"),
         p("Sentry + basic CloudWatch / Logtail","table_body"),
         p("~$10  (~₹830)","table_body")],
    ]
    stotal = [p("TOTAL","total_white"),
              p("For ~10,500 interactions/month (10 clinics)","total_white"),
              p("~₹10,500–11,000/month\n(~$126–133)","total_gold")]
    story.append(KeepTogether(cost_table(shdr, srows, stotal, [CW*0.28, CW*0.49, CW*0.23])))
    story.append(sp(5))

    story.append(key_insight(
        "At production scale with WhatsApp Business API (Meta Cloud API), ClinicAI costs "
        "under ₹1,000/month per clinic — approximately ₹33/day. Switching directly to "
        "Meta's Cloud API eliminates the Twilio BSP per-message markup (~$0.005/message), "
        "reducing messaging costs by 65–70% versus production Twilio. This remains the "
        "core financial argument against $299/month (₹24,800) enterprise tools like "
        "Suki AI — ClinicAI delivers comparable functionality at roughly 1/25th the cost."
    ))
    story.append(sp(5))
    story.append(p("Cost If We Switch to sLLM (Feedback 4)", "sub_header"))
    story.append(p("A self-hosted fine-tuned model eliminates per-token API costs but introduces "
                   "infrastructure costs (GPU rental or cloud ML). See Section 4 for the full analysis."))


def build_section4(story):
    story.append(sp(8)); story.append(hr()); story.append(sp(6))
    story.append(section_header(4, "sLLM — Domain-Specific Fine-Tuned Model"))
    story.append(sp(6))
    story.append(p("What Was Asked", "sub_header"))
    story.append(p("Consider building or using a small language model (sLLM) that is fine-tuned "
                   "specifically on medical/clinical domain data, rather than relying on a "
                   "general-purpose LLM like LLaMA 3.3 70B via Groq."))
    story.append(sp(5))
    story.append(p("What sLLM Means in This Context", "sub_header"))
    story.append(p("A 'small language model' here does not mean a weak model — it means a model "
                   "that is smaller than frontier models (GPT-4, LLaMA 70B) but fine-tuned on "
                   "domain-specific data so it outperforms larger general models on that narrow "
                   "task. Examples relevant to ClinicAI:"))
    story.append(sp(3))
    for b in [
        "BioMistral-7B — fine-tuned on PubMed + medical QA datasets",
        "MedAlpaca — LLaMA fine-tuned on medical instruction data",
        "ClinicalCamel — fine-tuned on clinical SOAP notes specifically",
        "Custom fine-tuned LLaMA 3.1 8B — trained on Indian clinic transcripts + SOAP pairs (ideal long-term goal)",
    ]:
        story.append(bullet(b))
    story.append(sp(5))
    story.append(p("Benefits for ClinicAI", "sub_header"))
    for b in [
        "Better SOAP note quality — a model trained on clinical notes understands 'OD', 'BD', 'TDS', 'IHD', 'DM' natively without prompt engineering",
        "Lower hallucination risk on medical terminology — domain-specific training reduces confident wrong answers",
        "No per-token API cost — self-hosted model means zero Groq/OpenAI billing at scale",
        "Data privacy — patient voice notes and SOAP notes never leave our infrastructure",
        "SNOMED mapping accuracy — a clinical sLLM maps drug names and diagnoses more reliably than a general LLM",
    ]:
        story.append(bullet(b))
    story.append(sp(5))
    story.append(p("Trade-offs & Challenges", "sub_header"))
    for b in [
        "Infrastructure cost — a 7B parameter model needs a GPU to run at useful latency (~20–40ms per token on A10G). AWS/GCP GPU instance: ~$300–600/month vs ~$5/month Groq API costs at current demo scale.",
        "Fine-tuning data — we need labelled Indian clinical transcripts + SOAP pairs. This data does not exist publicly and would need to be collected from partner clinics (with DPDP Act 2023 compliance).",
        "Maintenance — general models improve automatically (Groq pushes new versions). A self-hosted sLLM requires periodic retraining.",
        "Latency risk — if the GPU instance goes down, the entire WhatsApp bot goes down. Groq API has 99.9% uptime SLA.",
    ]:
        story.append(bullet(b))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def build_pdf(output_path: str):
    doc = BaseDocTemplate(
        output_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )
    frame = Frame(MARGIN, MARGIN, CW, PAGE_H - 2 * MARGIN, id="main")
    doc.addPageTemplates([PageTemplate(id="main_page", frames=[frame])])

    story = []
    story.append(title_block())
    story.append(sp(6))
    story.append(p("This document summarises the four feedback items received after the ClinicAI "
                   "evaluation demo. The demo successfully demonstrated all five end-to-end "
                   "workflows for a 1-doctor, 1-patient scenario on WhatsApp. "
                   "<b>Section 3 has been updated to reflect production deployment costs using "
                   "the WhatsApp Business API (Meta Cloud API) directly.</b>"))
    story.append(sp(6))
    story.append(hr())
    story.append(sp(6))

    build_section1(story)
    build_section2(story)
    build_section3(story)
    build_section4(story)

    doc.build(story)
    print(f"PDF written: {output_path}")


if __name__ == "__main__":
    out = r"C:\Users\LENOVO\Downloads\ClinicAI_Updated_CostAnalysis_WhatsAppAPI.pdf"
    build_pdf(out)
