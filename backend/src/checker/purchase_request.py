"""Load and validate purchase request CSV or JSON files.

The file is a company input, not a supplier document, so it is trusted for structure but
still parsed strictly: missing columns or unparseable numbers are setup errors, surfaced
before any document is checked.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from checker.schemas import PurchaseRequest, PurchaseRequestLine

REQUIRED_COLUMNS = (
    "PR number",
    "Item",
    "Description",
    "Unit",
    "Quantity requested",
    "Maximum unit price (BDT)",
)


class PurchaseRequestError(ValueError):
    """The purchase request file cannot be used."""


def _decimal(value: str, *, column: str, row: int) -> Decimal:
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise PurchaseRequestError(
            f"row {row}: column '{column}' is not a number: {value!r}"
        ) from exc


def _csv_row(line: PurchaseRequestLine) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="")
    writer.writerow(
        [
            line.pr_number,
            line.item_code,
            line.description,
            line.unit,
            format(line.quantity_requested, "f"),
            format(line.max_unit_price, "f"),
        ]
    )
    return buffer.getvalue()


def load_purchase_request_csv(path: Path) -> PurchaseRequest:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PurchaseRequestError(f"cannot read purchase request CSV: {path}") from exc

    reader = csv.DictReader(io.StringIO(text))
    headers = [header.strip() for header in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise PurchaseRequestError("purchase request CSV is missing columns: " + ", ".join(missing))

    lines: list[PurchaseRequestLine] = []
    for row_number, row in enumerate(reader, start=2):
        if not any((value or "").strip() for value in row.values() if isinstance(value, str)):
            continue
        item_code = (row.get("Item") or "").strip()
        description = (row.get("Description") or "").strip()
        if not item_code or not description:
            raise PurchaseRequestError(f"row {row_number}: 'Item' and 'Description' are required")
        line = PurchaseRequestLine(
            pr_number=(row.get("PR number") or "").strip(),
            item_code=item_code,
            description=description,
            unit=(row.get("Unit") or "").strip(),
            quantity_requested=_decimal(
                row.get("Quantity requested") or "", column="Quantity requested", row=row_number
            ),
            max_unit_price=_decimal(
                row.get("Maximum unit price (BDT)") or "",
                column="Maximum unit price (BDT)",
                row=row_number,
            ),
            csv_line="",
        )
        lines.append(line.model_copy(update={"csv_line": _csv_row(line)}))

    if not lines:
        raise PurchaseRequestError("purchase request CSV has no item rows")
    pr_numbers = {line.pr_number for line in lines}
    if len(pr_numbers) != 1:
        raise PurchaseRequestError("purchase request CSV must reference exactly one PR number")
    return PurchaseRequest(pr_number=next(iter(pr_numbers)), lines=lines)


def _json_decimal(value: Any, *, field: str, row: int) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise PurchaseRequestError(f"row {row}: '{field}' must be a decimal number or string")
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise PurchaseRequestError(f"row {row}: '{field}' is not a valid decimal") from exc


def load_purchase_request_json(path: Path) -> PurchaseRequest:
    """Load the JSON form: {pr_number, lines:[{item_code, description, unit,
    quantity_requested, max_unit_price}]}.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)
    except (OSError, UnicodeDecodeError) as exc:
        raise PurchaseRequestError("cannot read purchase request JSON as UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise PurchaseRequestError("purchase request is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise PurchaseRequestError("purchase request JSON must be an object")
    pr_number = payload.get("pr_number")
    raw_lines = payload.get("lines")
    if not isinstance(pr_number, str) or not pr_number.strip():
        raise PurchaseRequestError("purchase request JSON requires a non-empty 'pr_number'")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise PurchaseRequestError("purchase request JSON requires a non-empty 'lines' array")

    lines: list[PurchaseRequestLine] = []
    for row_number, raw_line in enumerate(raw_lines, start=1):
        if not isinstance(raw_line, dict):
            raise PurchaseRequestError(f"line {row_number} must be a JSON object")
        item_code = raw_line.get("item_code")
        description = raw_line.get("description")
        unit = raw_line.get("unit")
        if not isinstance(item_code, str) or not item_code.strip():
            raise PurchaseRequestError(f"line {row_number}: 'item_code' is required")
        if not isinstance(description, str) or not description.strip():
            raise PurchaseRequestError(f"line {row_number}: 'description' is required")
        if not isinstance(unit, str):
            raise PurchaseRequestError(f"line {row_number}: 'unit' must be a string")
        line = PurchaseRequestLine(
            pr_number=pr_number.strip(),
            item_code=item_code.strip(),
            description=description.strip(),
            unit=unit.strip(),
            quantity_requested=_json_decimal(
                raw_line.get("quantity_requested"), field="quantity_requested", row=row_number
            ),
            max_unit_price=_json_decimal(
                raw_line.get("max_unit_price"), field="max_unit_price", row=row_number
            ),
            csv_line="",
        )
        lines.append(line.model_copy(update={"csv_line": _csv_row(line)}))

    return PurchaseRequest(pr_number=pr_number.strip(), lines=lines)
