from __future__ import annotations

from decimal import Decimal

import pytest

from api.uploads import validate_purchase_request
from checker.purchase_request import (
    PurchaseRequestError,
    load_purchase_request_csv,
    load_purchase_request_json,
)

HEADER = "PR number,Item,Description,Unit,Quantity requested,Maximum unit price (BDT)\n"


def write_csv(path, body: str, *, header: str = HEADER) -> None:
    path.write_text(header + body, encoding="utf-8-sig")


def test_valid_csv_is_loaded_with_decimals(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(
        path,
        'PR-9999-001,S,"Synthetic Widget, 10 cm",piece,"1,234",9.99\n'
        'PR-9999-001,G,"Synthetic Gadget, 20 cm",piece,20000,3.50\n',
    )

    request = load_purchase_request_csv(path)

    assert request.pr_number == "PR-9999-001"
    assert len(request.lines) == 2
    first = request.lines[0]
    assert first.item_code == "S"
    assert first.description == "Synthetic Widget, 10 cm"
    assert first.unit == "piece"
    assert first.quantity_requested == Decimal("1234")
    assert first.max_unit_price == Decimal("9.99")
    assert first.csv_line.startswith('PR-9999-001,S,"Synthetic Widget')


def test_missing_column_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    header = "PR number,Item,Description,Unit,Quantity requested\n"
    write_csv(path, "PR-1,A,Item A,piece,100\n", header=header)

    with pytest.raises(PurchaseRequestError) as excinfo:
        load_purchase_request_csv(path)
    assert "Maximum unit price (BDT)" in str(excinfo.value)


def test_non_numeric_value_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(path, "PR-1,A,Item A,piece,one hundred,10.00\n")

    with pytest.raises(PurchaseRequestError) as excinfo:
        load_purchase_request_csv(path)
    assert "Quantity requested" in str(excinfo.value)


def test_empty_csv_is_a_setup_error(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(path, "")

    with pytest.raises(PurchaseRequestError) as excinfo:
        load_purchase_request_csv(path)
    assert "no item rows" in str(excinfo.value)


def test_multiple_purchase_requests_are_rejected(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(
        path,
        "PR-1,A,Item A,piece,100,10.00\nPR-2,B,Item B,piece,200,20.00\n",
    )

    with pytest.raises(PurchaseRequestError) as excinfo:
        load_purchase_request_csv(path)
    assert "exactly one PR number" in str(excinfo.value)


def test_rows_without_item_code_are_rejected(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(path, "PR-1,,Item A,piece,100,10.00\n")

    with pytest.raises(PurchaseRequestError) as excinfo:
        load_purchase_request_csv(path)
    assert "Item" in str(excinfo.value)


def test_trailing_blank_lines_are_ignored(tmp_path) -> None:
    path = tmp_path / "pr.csv"
    write_csv(path, "PR-1,A,Item A,piece,100,10.00\n\n\n")

    request = load_purchase_request_csv(path)
    assert len(request.lines) == 1


def test_valid_json_is_loaded_with_decimal_values(tmp_path) -> None:
    path = tmp_path / "pr.json"
    path.write_text(
        '{"pr_number":"PR-9999-001","lines":[{"item_code":"S",'
        '"description":"Synthetic Widget","unit":"piece",'
        '"quantity_requested":1234,"max_unit_price":9.99}]}',
        encoding="utf-8",
    )

    request = load_purchase_request_json(path)

    assert request.pr_number == "PR-9999-001"
    assert request.lines[0].quantity_requested == Decimal("1234")
    assert request.lines[0].max_unit_price == Decimal("9.99")
    assert request.lines[0].csv_line == "PR-9999-001,S,Synthetic Widget,piece,1234,9.99"


def test_json_missing_required_value_is_rejected(tmp_path) -> None:
    path = tmp_path / "pr.json"
    path.write_text(
        '{"pr_number":"PR-1","lines":[{"item_code":"A",'
        '"description":"Item A","unit":"piece","quantity_requested":10}]}',
        encoding="utf-8",
    )

    with pytest.raises(PurchaseRequestError, match="max_unit_price"):
        load_purchase_request_json(path)


@pytest.mark.parametrize(
    ("filename", "content", "expected_pr"),
    [
        (
            "anything.bin",
            HEADER + "PR-1,A,Item A,piece,10,2.50\n",
            "PR-1",
        ),
        (
            "request.upload",
            '{"pr_number":"PR-2","lines":[{"item_code":"B",'
            '"description":"Item B","unit":"piece",'
            '"quantity_requested":20,"max_unit_price":"3.00"}]}',
            "PR-2",
        ),
    ],
)
def test_upload_format_is_detected_from_content_not_filename(
    tmp_path, filename: str, content: str, expected_pr: str
) -> None:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")

    request = validate_purchase_request(path)

    assert request.pr_number == expected_pr
