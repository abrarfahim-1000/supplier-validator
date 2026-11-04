"""Validate and stage uploads on disk.

Bytes are streamed to server-generated names while one SHA-256 is computed on the way, so a
job never holds upload data in memory and a client filename never reaches the filesystem.
The purchase request is validated before any document is checked, so a broken CSV fails the
request instead of every document.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from api.errors import (
    DUPLICATE_FILE,
    EMPTY_FILE,
    FILE_TOO_LARGE,
    INTERNAL_ERROR,
    INVALID_PDF,
    INVALID_PURCHASE_REQUEST,
    NO_SUPPLIER_DOCUMENTS,
    TOO_MANY_DOCUMENTS,
    ApiError,
)
from api.settings import ApiSettings
from checker.file_types import PDF_MAGIC
from checker.purchase_request import (
    PurchaseRequestError,
    load_purchase_request_csv,
    load_purchase_request_json,
)
from checker.schemas import PurchaseRequest

CHUNK_BYTES = 64 * 1024
PURCHASE_REQUEST_NAME = "purchase-request"
MAX_DISPLAY_NAME = 120


@dataclass(frozen=True)
class StagedFile:
    path: Path
    original_name: str
    size_bytes: int
    digest: str


@dataclass(frozen=True)
class StagedJob:
    purchase_request: PurchaseRequest
    documents: tuple[StagedFile, ...]


def display_name(raw: str | None, fallback: str) -> str:
    """A filename safe to show and to store in job state. Never used as a path."""
    name = Path(raw or "").name
    cleaned = "".join(char for char in name if char.isprintable()).strip()
    if not cleaned:
        return fallback
    return cleaned[:MAX_DISPLAY_NAME]


def _stored_path(work_dir: Path, name: str) -> Path:
    path = work_dir / name
    # Names are generated here, so this can only fail if the layout changes.
    if path.resolve().parent != work_dir.resolve():
        raise ApiError(500, INTERNAL_ERROR, "the upload directory is not usable")
    return path


async def _write_stream(
    upload: UploadFile, path: Path, *, max_bytes: int, label: str
) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as handle:
        while chunk := await upload.read(CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise ApiError(
                    413,
                    FILE_TOO_LARGE,
                    f"the {label} is larger than {max_bytes // (1024 * 1024)} MB",
                )
            digest.update(chunk)
            handle.write(chunk)
    if size == 0:
        raise ApiError(400, EMPTY_FILE, f"the {label} is empty")
    return size, digest.hexdigest()


async def stage_supplier_documents(
    uploads: Sequence[UploadFile],
    work_dir: Path,
    *,
    settings: ApiSettings,
) -> tuple[StagedFile, ...]:
    if not uploads:
        raise ApiError(400, NO_SUPPLIER_DOCUMENTS, "upload at least one supplier quotation PDF")
    if len(uploads) > settings.max_pdfs:
        raise ApiError(
            400,
            TOO_MANY_DOCUMENTS,
            f"at most {settings.max_pdfs} supplier quotation PDFs can be checked at once",
        )

    staged: list[StagedFile] = []
    for index, upload in enumerate(uploads, start=1):
        name = display_name(upload.filename, f"document-{index:02d}.pdf")
        path = _stored_path(work_dir, f"document-{index:02d}.pdf")
        size, digest = await _write_stream(
            upload, path, max_bytes=settings.max_file_bytes, label="supplier quotation"
        )
        with path.open("rb") as handle:
            if handle.read(len(PDF_MAGIC)) != PDF_MAGIC:
                raise ApiError(400, INVALID_PDF, f"'{name}' is not a PDF file")
        staged.append(StagedFile(path=path, original_name=name, size_bytes=size, digest=digest))
    return tuple(staged)


async def stage_purchase_request(
    upload: UploadFile,
    work_dir: Path,
    *,
    settings: ApiSettings,
) -> StagedFile:
    name = display_name(upload.filename, PURCHASE_REQUEST_NAME)
    path = _stored_path(work_dir, f"{PURCHASE_REQUEST_NAME}.upload")
    size, digest = await _write_stream(
        upload, path, max_bytes=settings.max_file_bytes, label="purchase request"
    )
    return StagedFile(path=path, original_name=name, size_bytes=size, digest=digest)


def validate_purchase_request(path: Path) -> PurchaseRequest:
    """Strictly validate a request before any supplier document is checked."""
    try:
        text = path.read_text(encoding="utf-8-sig")
        first_character = text.lstrip()[:1]
        loader = (
            load_purchase_request_json
            if first_character in {"{", "["}
            else load_purchase_request_csv
        )
        return loader(path)
    except PurchaseRequestError as exc:
        raise ApiError(400, INVALID_PURCHASE_REQUEST, str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise ApiError(
            400, INVALID_PURCHASE_REQUEST, "the purchase request must be UTF-8 encoded text"
        ) from exc
    except OSError as exc:
        raise ApiError(500, INTERNAL_ERROR, "the purchase request could not be read") from exc
    except csv.Error as exc:
        raise ApiError(
            400, INVALID_PURCHASE_REQUEST, "the purchase request is not valid CSV text"
        ) from exc


async def stage_job(
    *,
    work_dir: Path,
    purchase_request: UploadFile,
    supplier_quotes: Sequence[UploadFile],
    settings: ApiSettings,
) -> StagedJob:
    documents = await stage_supplier_documents(supplier_quotes, work_dir, settings=settings)
    request_file = await stage_purchase_request(purchase_request, work_dir, settings=settings)

    seen = {request_file.digest}
    for document in documents:
        if document.digest in seen:
            raise ApiError(
                400,
                DUPLICATE_FILE,
                f"'{document.original_name}' is uploaded more than once",
            )
        seen.add(document.digest)

    return StagedJob(
        purchase_request=validate_purchase_request(request_file.path),
        documents=documents,
    )
