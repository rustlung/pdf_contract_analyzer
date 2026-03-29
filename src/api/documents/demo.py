import argparse
import logging
from pathlib import Path

from src.api.documents.services.document_processing import process_document


def main() -> None:
    parser = argparse.ArgumentParser(description="DocuMind document pipeline demo")
    parser.add_argument("file_path", help="Path to input PDF or DOCX file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    path = Path(args.file_path)
    result = process_document(
        file_bytes=path.read_bytes(),
        filename=path.name,
    )
    print("filename:", result.filename)
    print("source_type:", result.source_type)
    print("extraction_method:", result.extraction_method)
    print("pages_count:", result.pages_count)
    print("used_ocr:", result.used_ocr)
    print("raw_text_length:", len(result.raw_text))


if __name__ == "__main__":
    main()
