from __future__ import annotations

import pytest

from airports_collector.source import (
    MIN_EXPECTED_ROWS,
    SourceError,
    batched,
    compute_row_hash,
    parse_airports,
    sanity_check,
)
from conftest import make_row, to_csv


def test_parse_and_hash(sample_csv: str) -> None:
    records = parse_airports(sample_csv)
    assert [record.id for record in records] == [1, 2, 3, 4]
    assert records[0].type == "large_airport"
    assert records[0].latitude_deg == 10.0
    assert records[1].iata_code is None
    assert records[2].icao_code is None
    assert records[3].type == "medium_airport"
    assert records[0].row_hash == compute_row_hash(records[0].source_values())
    assert len(records[0].row_hash) == 64


def test_hash_changes_with_upstream_field(sample_csv: str) -> None:
    records = parse_airports(sample_csv)
    other = parse_airports(to_csv([make_row(name="Renamed Airport")]))
    assert records[0].row_hash != other[0].row_hash


def test_header_mismatch_rejected(sample_csv: str) -> None:
    broken = sample_csv.replace("latitude_deg", "lat_deg", 1)
    with pytest.raises(SourceError, match="表头"):
        parse_airports(broken)


def test_duplicate_id_rejected() -> None:
    csv_text = to_csv([make_row(), make_row(ident="ZZZ", icao_code="ZZZZ", iata_code="ZZZ")])
    with pytest.raises(SourceError, match="重复"):
        parse_airports(csv_text)


def test_bad_type_rejected() -> None:
    csv_text = to_csv([make_row(type="airport")])
    with pytest.raises(SourceError, match="type"):
        parse_airports(csv_text)


def test_bad_scheduled_service_rejected() -> None:
    csv_text = to_csv([make_row(scheduled_service="maybe")])
    with pytest.raises(SourceError, match="scheduled_service"):
        parse_airports(csv_text)


def test_sanity_check_thresholds(sample_csv: str) -> None:
    records = parse_airports(sample_csv)
    with pytest.raises(SourceError, match="低于安全下限"):
        sanity_check(records)
    sanity_check(records, min_rows=1, min_large_airports=1)
    with pytest.raises(SourceError, match="large_airport"):
        sanity_check(records, min_rows=1, min_large_airports=5)
    assert MIN_EXPECTED_ROWS > 1000


def test_batched() -> None:
    assert list(batched(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def test_header_order_is_tolerated() -> None:
    # 真实 CSV 的列顺序与数据字典页面不同，解析必须按列名而不是位置。
    csv_text = to_csv([make_row()])
    lines = csv_text.splitlines()
    header = lines[0].split(",")
    reordered = list(header)
    icao_index = reordered.index("icao_code")
    gps_index = reordered.index("gps_code")
    reordered[icao_index], reordered[gps_index] = reordered[gps_index], reordered[icao_index]
    row_values = lines[1].split(",")
    row_values[icao_index], row_values[gps_index] = row_values[gps_index], row_values[icao_index]
    shuffled = "\n".join([",".join(reordered), ",".join(row_values)]) + "\n"
    records = parse_airports(shuffled)
    assert records[0].icao_code == "AAAA"
    assert records[0].gps_code == "AAAA"


def test_missing_column_rejected(sample_csv: str) -> None:
    lines = sample_csv.splitlines()
    header = lines[0].split(",")
    keep = [index for index, name in enumerate(header) if name != "icao_code"]
    trimmed = "\n".join(
        ",".join(parts[index] for index in keep) for parts in (line.split(",") for line in lines)
    ) + "\n"
    with pytest.raises(SourceError, match="缺少"):
        parse_airports(trimmed)
