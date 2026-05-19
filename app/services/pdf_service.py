import os
import sys
import tempfile
import httpx
import pdfplumber
import logging
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

try:
    from app.graph.parser.pipeline import lab_report_pipeline
except ImportError:
    lab_report_pipeline = None
    print("Warning: Could not import app.graph.parser.pipeline")

load_dotenv()
logger = logging.getLogger(__name__)

async def download_media(media_url: str) -> str:
    """Download media from Twilio to a temporary file and return the path."""
    # Twilio WhatsApp media URLs might need basic auth depending on account settings,
    # but typically for WhatsApp inbound it's a publicly accessible URL for a short time
    # or requires auth. We'll use the Twilio account SID and Auth Token if available.
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    
    auth = None
    if account_sid and auth_token:
        auth = (account_sid, auth_token)

    async with httpx.AsyncClient() as client:
        response = await client.get(media_url, auth=auth, follow_redirects=True)
        response.raise_for_status()
        
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(response.content)
            
    return temp_path

def check_safety(pdf_path: str) -> bool:
    """
    Check if the PDF is a valid, safe lab report.
    Reads the first page and asks an LLM to verify it.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return False
            first_page = pdf.pages[0].extract_text()
            if not first_page:
                return False
    except Exception as e:
        logger.error(f"Error reading PDF for safety check: {e}")
        return False
        
    prompt = """
    You are a safety filter for a medical AI system.
    Review the following text extracted from the first page of a document.
    Determine if this document appears to be a legitimate medical or laboratory report.
    If it contains any explicit, malicious, harmful, or clearly non-medical spam content, respond with "UNSAFE".
    If it looks like a standard medical/lab document (even if partial), respond with "SAFE".
    Reply with ONLY the word "SAFE" or "UNSAFE".
    """
    
    try:
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        llm = ChatGroq(
            model=model,
            temperature=0,
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"--- DOCUMENT TEXT ---\n{first_page[:2000]}\n--- END TEXT ---")
        ]
        response = llm.invoke(messages)
        content = response.content.strip().upper()
        return "SAFE" in content
    except Exception as e:
        logger.error(f"Safety check LLM error: {e}")
        # Default to safe if LLM fails, or fail-safe? We'll fail-safe.
        return False

def format_report_reply(state: dict) -> str:
    """Format the parser output into a WhatsApp friendly message."""
    errors = state.get("errors", [])
    if errors:
        return "Sorry, I encountered an error while processing the report: " + "; ".join(errors)

    patient_info = state.get("patient_info", {})
    name = patient_info.get("name", "Unknown")
    summary = state.get("doctor_summary", "No summary available.")
    
    reply_lines = [
        f"📄 *Lab Report Analysis*",
        f"Patient: {name}",
        f"",
        f"📝 *Summary*:",
        summary,
        f""
    ]
    
    abnormals = state.get("abnormals", [])
    if abnormals:
        reply_lines.append(f"⚠️ *Abnormal Findings* ({len(abnormals)}):")
        for ab in abnormals:
            # e.g., - Hemoglobin: 11.2 g/dL (ref: 12-15) [LOW]
            status_emoji = "🔴" if ab.get("status") == "CRITICAL" else "🟠"
            reply_lines.append(f"{status_emoji} {ab.get('parameter')}: {ab.get('value')} {ab.get('unit', '')} (Ref: {ab.get('reference_range')}) [{ab.get('status')}]")
    else:
        reply_lines.append("✅ No abnormal values detected.")
        
    return "\n".join(reply_lines)

async def handle_incoming_pdf(media_url: str) -> str:
    """
    Main workflow for handling a PDF:
    1. Download
    2. Check Safety
    3. Parse
    4. Format Reply
    """
    if not lab_report_pipeline:
        return "Sorry, the report parser is currently offline."
        
    temp_path = None
    try:
        temp_path = await download_media(media_url)
        
        # Check safety
        is_safe = check_safety(temp_path)
        if not is_safe:
            return "This document does not appear to be a valid lab report or could not be verified for safety."
            
        # Run Parser
        print(f"[Parser] Invoking pipeline for {temp_path}")
        initial_state = {"pdf_path": temp_path}
        final_state = lab_report_pipeline.invoke(initial_state)
        
        reply = format_report_reply(final_state)
        return reply
        
    except Exception as e:
        logger.error(f"Error handling PDF: {e}")
        return "Sorry, an error occurred while processing the PDF."
    finally:
        # Cleanup
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
