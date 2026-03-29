import argparse
import logging
from pathlib import Path

from src.api.documents import process_document
from src.api.documents.docx_reconstruction_service import DocxReconstructionService
from src.api.documents.text_normalizer import normalize_extracted_text_for_docx


DEFAULT_INPUT = Path(r"C:\Users\visig\Downloads\test_docs\contract1_services.pdf")
DEFAULT_OUTPUT = Path("tmp/contract1_services_reconstructed.docx")


def run_funnel(input_pdf: Path, output_docx: Path) -> None:
    logging.info("Input funnel started for: %s", input_pdf)

    if not input_pdf.exists():
        raise FileNotFoundError(f"Файл не найден: {input_pdf}")

    file_bytes = input_pdf.read_bytes()
    logging.info("PDF bytes loaded: %s", len(file_bytes))

    result = process_document(
        file_bytes=file_bytes,
        filename=input_pdf.name,
        mime_type="application/pdf",
    )

    logging.info(
        "Document processed: source=%s, method=%s, pages=%s, used_ocr=%s, text_length=%s",
        result.source_type,
        result.extraction_method,
        result.pages_count,
        result.used_ocr,
        len(result.raw_text),
    )
    normalized_paragraphs = normalize_extracted_text_for_docx(result.raw_text)
    logging.info(
        "Text normalized for reconstruction: raw_lines=%s, normalized_paragraphs=%s",
        len(result.raw_text.splitlines()),
        len(normalized_paragraphs),
    )

    reconstruction_service = DocxReconstructionService()
    docx_bytes = reconstruction_service.generate_docx(result.raw_text)
    logging.info("DOCX reconstructed: bytes=%s", len(docx_bytes))

    output_docx.parent.mkdir(parents=True, exist_ok=True)
    output_docx.write_bytes(docx_bytes)

    print("=== Funnel completed ===")
    print(f"Input file: {input_pdf}")
    print(f"Extraction method: {result.extraction_method}")
    print(f"Used OCR: {result.used_ocr}")
    print(f"Pages: {result.pages_count}")
    print(f"Extracted text length: {len(result.raw_text)}")
    print(f"Raw lines: {len(result.raw_text.splitlines())}")
    print(f"Normalized paragraphs: {len(normalized_paragraphs)}")
    print(f"Output DOCX: {output_docx.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run full PDF input funnel: extract text -> reconstruct DOCX"
    )
    parser.add_argument(
        "--input-pdf",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to input PDF file",
    )
    parser.add_argument(
        "--output-docx",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path to output reconstructed DOCX file",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    run_funnel(args.input_pdf, args.output_docx)


if __name__ == "__main__":
    main()
