from io import BytesIO

from docx import Document


def extract_docx_text(file_bytes: bytes) -> tuple[str, int]:
    document = Document(BytesIO(file_bytes))
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    filtered = [paragraph for paragraph in paragraphs if paragraph]
    return "\n".join(filtered), 1
