from io import BytesIO
import logging

import fitz
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)
OCR_LANG = "rus+eng"


def extract_pdf_text_with_ocr(file_bytes: bytes) -> tuple[str, int]:
    logger.info("OCR extractor: engine=pytesseract lang=%s", OCR_LANG)
    with fitz.open(stream=BytesIO(file_bytes), filetype="pdf") as document:
        page_texts: list[str] = []
        logger.info("OCR extractor: started pages=%s", len(document))
        for page in document:
            pixmap = page.get_pixmap(dpi=300)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            page_texts.append(pytesseract.image_to_string(image, lang=OCR_LANG).strip())

        text = "\n".join([chunk for chunk in page_texts if chunk])
        logger.info("OCR extractor: completed text_length=%s", len(text))
        return text, len(document)
