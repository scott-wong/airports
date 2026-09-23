from __future__ import annotations

import json

from airports_collector.storage.repository import AirportRepository, utc_now
from conftest import FakeStorage


def test_run_lifecycle() -> None:
    storage = FakeStorage(
        {
            "INSERT INTO airports.collector_run": [{"run_id": 42}],
            "WITH input AS": [{"inserted": 3, "updated": 2, "unchanged": 1, "reactivated": 1}],
            "UPDATE airports.airport\nSET is_active": [{"id": 1}, {"id": 2}],
        }
    )
    repo = AirportRepository(storage, batch_size=2)
    run_id = repo.start_run("https://example.com/airports.csv", "abc")
    assert run_id == 42

    repo.clear_staging(run_id)
    snapshot = utc_now()
    rows = [{"id": index, "ident": f"X{index}", "row_hash": "h"} for index in range(5)]
    staged = 0
    for chunk in repo.chunks(rows):
        staged += repo.stage_rows(run_id, snapshot, chunk)
    assert staged == 5
    staging_batches = [params for sql, params in storage.calls if "INSERT INTO airports.airport_staging" in sql]
    assert len(staging_batches) == 3
    first = staging_batches[0]
    assert first[0] == 42
    assert first[1] == snapshot.isoformat()
    assert json.loads(first[2])[0]["ident"] == "X0"

    merge = repo.merge(run_id)
    assert (merge.inserted, merge.updated, merge.unchanged, merge.reactivated) == (3, 2, 1, 1)
    assert merge.total == 6

    assert repo.deactivate_missing(snapshot) == 2

    repo.finish_run(
        run_id,
        etag=None,
        last_modified=None,
        source_sha256="sha",
        source_bytes=10,
        rows_total=5,
        rows_inserted=3,
        rows_updated=2,
        rows_unchanged=1,
        rows_reactivated=1,
        rows_deactivated=2,
        rows_large_airport=1,
        rows_large_airport_missing_zh=0,
    )
    finish_params = storage.params_for("UPDATE airports.collector_run")[0]
    assert finish_params[0] == 42
    assert finish_params[1] == "succeeded"
    assert finish_params[12] == 1


def test_fail_run_truncates_message() -> None:
    storage = FakeStorage()
    AirportRepository(storage).fail_run(9, "x" * 3000)
    params = storage.params_for("SET status = 'failed'")[0]
    assert len(params[1]) == 2000


def test_deactivate_uses_lt_not_neq() -> None:
    storage = FakeStorage({"UPDATE airports.airport": [{"id": 1}]})
    AirportRepository(storage).deactivate_missing(utc_now())
    sql = [statement for statement in storage.sql_calls() if "is_active = false" in statement][0]
    assert "source_snapshot_at < $1" in sql
