"""
Stage 1: open one PDF and print every word with its position on the page.

Goal is just to *see* the raw data pdfplumber gives us before we try to
organize it into records and fields. Nothing here is saved anywhere yet.

Run from the repo root:
    python services/worker/inspect_pdf.py
"""

import pdfplumber

PDF_PATH = "services/worker/sample_pdfs/nmac.pdf"

with pdfplumber.open(PDF_PATH) as pdf:
    print(f"Total pages: {len(pdf.pages)}")

    first_page = pdf.pages[0]
    words = first_page.extract_words(use_text_flow=True, keep_blank_chars=False)

    print(f"\nWords found on page 1: {len(words)}")
    print("\nFirst 40 words (text, x0, top):")
    for w in words[:40]:
        print(f"  x0={w['x0']:6.1f}  top={w['top']:6.1f}  text={w['text']!r}")
