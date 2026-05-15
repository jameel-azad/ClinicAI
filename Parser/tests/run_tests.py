"""
tests/run_tests.py — Runs all 5 sample PDFs through the live API and prints results.

Usage (server must be running on port 8001):
  python tests/run_tests.py
"""

import json
import os
import sys
import requests

API_URL = "http://localhost:8001/parse-report"
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "sample_reports")

TEST_CASES = [
    {
        "file": "pdf1_clean_cbc.pdf",
        "label": "PDF 1 — Clean CBC (all normal)",
        "hints": {},
    },
    {
        "file": "pdf2_multiple_abnormals.pdf",
        "label": "PDF 2 — Multiple Abnormals (low Hb, high WBC, low Plt)",
        "hints": {},
    },
    {
        "file": "pdf3_critical_values.pdf",
        "label": "PDF 3 — Critical Values (K+ 6.8, Creatinine 5.8)",
        "hints": {},
    },
    {
        "file": "pdf4_urine_routine.pdf",
        "label": "PDF 4 — Urine Routine & Microscopy (non-blood report)",
        "hints": {},
    },
    {
        "file": "pdf5_thyroid_lipid.pdf",
        "label": "PDF 5 — Thyroid Profile + Lipid Panel",
        "hints": {},
    },
]


def run_test(case: dict):
    path = os.path.join(REPORTS_DIR, case["file"])
    if not os.path.exists(path):
        print(f"  [SKIP] File not found: {path}")
        print(f"         Run: python tests/generate_test_pdfs.py first\n")
        return

    with open(path, "rb") as f:
        files = {"pdf_file": (case["file"], f, "application/pdf")}
        data = case.get("hints", {})
        response = requests.post(API_URL, files=files, data=data, timeout=60)

    if response.status_code != 200:
        print(f"  [ERROR] HTTP {response.status_code}: {response.text}\n")
        return

    result = response.json()
    patient = result["patient_info"]
    all_values = result["all_values"]
    abnormals = result["abnormals"]
    criticals = result["criticals"]
    summary = result["doctor_summary"]
    warnings = result.get("warnings", [])

    print(f"\n{'='*65}")
    print(f"  {case['label']}")
    print(f"{'='*65}")
    print(f"\nPatient Info:")
    print(f"  Name:            {patient['name']}")
    print(f"  Age:             {patient['age']}")
    print(f"  Gender:          {patient['gender']}")
    print(f"  DOB:             {patient['dob']}")
    print(f"  Patient ID:      {patient['patient_id']}")
    print(f"  Lab:             {patient['lab_name']}")
    print(f"  Report Date:     {patient['report_date']}")
    print(f"  Referring Dr:    {patient['referring_doctor']}")
    print(f"\nTest Values: {len(all_values)} extracted")
    print(f"Abnormals:   {len(abnormals)}")
    print(f"Criticals:   {len(criticals)}")

    if criticals:
        print("\nCRITICAL VALUES:")
        for c in criticals:
            print(f"  ⚠  {c['parameter']}: {c['value']} {c['unit']} (ref: {c['reference_range']})")

    if abnormals:
        print("\nABNORMAL VALUES:")
        for a in abnormals:
            if a["status"] != "CRITICAL":
                print(f"  {a['status']:4s} {a['parameter']}: {a['value']} {a['unit']} (ref: {a['reference_range']})")

    print(f"\nDOCTOR SUMMARY:\n  {summary}")

    if warnings:
        print(f"\nWARNINGS: {warnings}")


def main():
    print("\nFellowAI — Lab Report Parser Test Runner")
    print("Task 1J · Jameel Ahmad Azad\n")

    # Quick health check
    try:
        health = requests.get("http://localhost:8001/health", timeout=5)
        h = health.json()
        print(f"API status: {h['status']}")
        print(f"API key configured: {h['groq_api_key_configured']}")
        print(f"Model: {h['model']}\n")
    except Exception as e:
        print(f"Could not reach API at localhost:8001: {e}")
        print("Start the server with: uvicorn app.main:app --reload --port 8001")
        sys.exit(1)

    for case in TEST_CASES:
        run_test(case)

    print(f"\n{'='*65}")
    print("All tests complete.")


if __name__ == "__main__":
    main()
