from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.api.documents.document_types import DocumentProcessingError
from src.api.documents.services import document_processing
from src.api.services import web_pipeline


def test_pdf_over_size_limit_is_rejected_before_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    extract_direct = Mock()
    monkeypatch.setattr(document_processing, "extract_pdf_text_direct", extract_direct)

    with pytest.raises(DocumentProcessingError, match="Размер PDF превышает допустимые"):
        document_processing.process_document(
            b"x" * 11,
            filename="large.pdf",
            max_pdf_size_bytes=10,
            scenario_type="recognize",
        )

    extract_direct.assert_not_called()


def test_scanned_pdf_over_ocr_page_limit_is_rejected_before_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_processing, "extract_pdf_text_direct", Mock(return_value=("", 11)))
    extract_ocr = Mock()
    monkeypatch.setattr(document_processing, "extract_pdf_text_with_ocr", extract_ocr)

    with pytest.raises(DocumentProcessingError, match="не более 10 страниц"):
        document_processing.process_document(
            b"pdf",
            filename="scan.pdf",
            max_ocr_pages=10,
            scenario_type="recognize",
        )

    extract_ocr.assert_not_called()


def test_scanned_pdf_within_ocr_page_limit_starts_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_processing, "extract_pdf_text_direct", Mock(return_value=("", 10)))
    extract_ocr = Mock(return_value=("recognized text", 10))
    monkeypatch.setattr(document_processing, "extract_pdf_text_with_ocr", extract_ocr)

    result = document_processing.process_document(
        b"pdf",
        filename="scan.pdf",
        max_ocr_pages=10,
        scenario_type="recognize",
    )

    assert result.used_ocr is True
    extract_ocr.assert_called_once_with(b"pdf")


def test_text_pdf_over_ocr_page_limit_is_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "text " * 20
    monkeypatch.setattr(document_processing, "extract_pdf_text_direct", Mock(return_value=(text, 11)))
    extract_ocr = Mock()
    monkeypatch.setattr(document_processing, "extract_pdf_text_with_ocr", extract_ocr)

    result = document_processing.process_document(
        b"pdf",
        filename="text.pdf",
        max_ocr_pages=10,
        scenario_type="analyze",
    )

    assert result.used_ocr is False
    assert result.pages_count == 11
    extract_ocr.assert_not_called()


def test_web_upload_shows_size_limit_error_instead_of_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.main import app

    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "10")
    monkeypatch.setattr(document_processing, "extract_pdf_text_direct", Mock())

    with TestClient(app) as client:
        response = client.post(
            "/web/run",
            data={"mode": "recognize"},
            files={"file1": ("large.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
            follow_redirects=False,
        )
        assert response.status_code == 303

        upload_page = client.get(response.headers["location"])

    assert "Размер PDF превышает допустимые 10 МБ" in upload_page.text


def test_web_upload_template_shows_pdf_limits_for_all_file_fields() -> None:
    from src.api.main import app

    with TestClient(app) as client:
        response = client.get("/web/upload")

    assert response.status_code == 200
    assert response.text.count("до 10 МБ") == 4
    assert response.text.count("до 10 страниц") == 4
