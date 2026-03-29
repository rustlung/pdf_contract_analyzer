import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.documents.services.document_processing import process_document
from src.llm.contract_analysis_service import ContractAnalysisError, ContractAnalysisService
from src.shared.masking import mask_document_text


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python scripts/run_single_contract_analysis.py "<path-to-pdf-or-docx>"')
        return 1

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"File not found: {file_path}")
        return 1

    try:
        document_result = process_document(
            file_bytes=file_path.read_bytes(),
            filename=file_path.name,
        )
    except Exception as exc:
        print(f"Document pipeline error: {exc}")
        return 1

    masking_result = mask_document_text(document_result.raw_text)
    print("Document processed:")
    print(f"- filename: {document_result.filename}")
    print(f"- source_type: {document_result.source_type}")
    print(f"- extraction_method: {document_result.extraction_method}")
    print(f"- used_ocr: {document_result.used_ocr}")
    print(f"- pages_count: {document_result.pages_count}")
    print(f"- raw_text_length: {len(document_result.raw_text)}")
    print(f"- replacements_count: {masking_result.replacements_count}")
    print(f"- replacement_stats: {masking_result.replacement_stats}")
    print("")

    try:
        service = ContractAnalysisService()
        analysis_result = service.analyze_contract(masking_result.masked_text)
    except ContractAnalysisError as exc:
        print(f"Contract analysis error: {exc}")
        return 1

    print("LLM analysis result:")
    print(
        json.dumps(
            asdict(analysis_result),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
