"""
Web UI orchestration: thin wrappers around existing document/LLM/masking services.
"""

from __future__ import annotations

import time
from dataclasses import asdict

from src.api.documents.document_types import DocumentProcessingError
from src.api.documents.docx_reconstruction_service import DocxReconstructionError, DocxReconstructionService
from src.api.documents.services.document_processing import process_document
from src.llm.contract_analysis_service import ContractAnalysisError, ContractAnalysisService
from src.llm.contract_comparison_service import ContractComparisonError, ContractComparisonService
from src.shared.masking import mask_document_text


def run_recognize_pdf(
    file_bytes: bytes,
    filename: str,
    *,
    trace_id: str | None = None,
) -> tuple[bytes, dict]:
    if not filename.lower().endswith(".pdf"):
        raise DocumentProcessingError("Режим распознавания принимает только PDF.")
    timings: dict[str, float] = {}
    result = process_document(
        file_bytes,
        filename=filename,
        mime_type="application/pdf",
        trace_id=trace_id,
    )
    if result.ocr_seconds is not None:
        timings["ocr_time"] = result.ocr_seconds
    svc = DocxReconstructionService()
    t0 = time.perf_counter()
    docx_bytes = svc.generate_docx(result.raw_text)
    timings["docx_generation_time"] = time.perf_counter() - t0
    meta = {
        "used_ocr": result.used_ocr,
        "pages_count": result.pages_count,
        "extraction_method": result.extraction_method,
        "_timings": timings,
    }
    return docx_bytes, meta


def run_analyze(
    file_bytes: bytes,
    filename: str,
    mime_type: str | None,
    *,
    trace_id: str | None = None,
) -> dict:
    timings: dict[str, float] = {}
    result = process_document(file_bytes, filename=filename, mime_type=mime_type, trace_id=trace_id)
    if result.ocr_seconds is not None:
        timings["ocr_time"] = result.ocr_seconds
    t0 = time.perf_counter()
    masked = mask_document_text(result.raw_text)
    timings["masking_time"] = time.perf_counter() - t0
    service = ContractAnalysisService()
    t1 = time.perf_counter()
    analysis = service.analyze_contract(masked.masked_text)
    timings["analysis_time"] = time.perf_counter() - t1
    return {
        "extraction": {
            "used_ocr": result.used_ocr,
            "pages_count": result.pages_count,
            "extraction_method": result.extraction_method,
        },
        "analysis": asdict(analysis),
        "_timings": timings,
    }


def run_compare(
    file1_bytes: bytes,
    file1_name: str,
    file1_mime: str | None,
    file2_bytes: bytes,
    file2_name: str,
    file2_mime: str | None,
    *,
    trace_id: str | None = None,
) -> dict:
    timings: dict[str, float] = {}
    r1 = process_document(file1_bytes, filename=file1_name, mime_type=file1_mime, trace_id=trace_id)
    r2 = process_document(file2_bytes, filename=file2_name, mime_type=file2_mime, trace_id=trace_id)
    ocr_sum = 0.0
    for r in (r1, r2):
        if r.ocr_seconds is not None:
            ocr_sum += r.ocr_seconds
    if ocr_sum > 0:
        timings["ocr_time"] = ocr_sum
    t0 = time.perf_counter()
    m1 = mask_document_text(r1.raw_text)
    m2 = mask_document_text(r2.raw_text)
    timings["masking_time"] = time.perf_counter() - t0
    service = ContractComparisonService()
    t1 = time.perf_counter()
    comparison = service.compare_contracts(m1.masked_text, m2.masked_text)
    timings["comparison_time"] = time.perf_counter() - t1
    return {
        "doc1": {"filename": file1_name, "used_ocr": r1.used_ocr},
        "doc2": {"filename": file2_name, "used_ocr": r2.used_ocr},
        "comparison": asdict(comparison),
        "_timings": timings,
    }


__all__ = [
    "run_recognize_pdf",
    "run_analyze",
    "run_compare",
    "DocumentProcessingError",
    "DocxReconstructionError",
    "ContractAnalysisError",
    "ContractComparisonError",
]
