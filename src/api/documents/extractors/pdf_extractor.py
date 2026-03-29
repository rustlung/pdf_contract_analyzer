from io import BytesIO

import fitz


def extract_pdf_text_direct(file_bytes: bytes) -> tuple[str, int]:
    with fitz.open(stream=BytesIO(file_bytes), filetype="pdf") as document:
        page_texts: list[str] = []
        for page in document:
            page_texts.append(page.get_text("text").strip())

        text = "\n".join([chunk for chunk in page_texts if chunk])
        return text, len(document)
