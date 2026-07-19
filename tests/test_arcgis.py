from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from cre_pipeline.arcgis import ArcGisPropertyAdapter, map_feature


def _attributes(object_id: int) -> dict[str, object]:
    return {
        "OBJECTID": object_id,
        "UNIQUE_ID": f"fixture-{object_id}",
        "PROPERTY_ID": f"P{object_id:08d}",
        "ACCOUNT": f"A{object_id:06d}",
        "OWNER_NAME": f"FIXTURE OWNER {object_id} LLC",
        "HOUSE_NUMBER": f"{object_id:06d}",
        "HOUSE_SUFFIX": None,
        "STREET_DIRECTION": None,
        "STREET_NAME": "EXAMPLE",
        "STREET_TYPE": "RD",
        "UNIT": None,
        "CITY": "LARGO",
        "ZIP5": "20774",
        "MNCPPC_USE": "COM",
        "BPRUC": "04000",
        "ZONE_CODE1": "CGO",
        "LAND_AREA_SQFT": 20000,
        "STRUCTURE_SQ_FT": "0010000",
        "YEAR_BUILT": "1990",
        "FCV_LAND": 250000,
        "FCV_IMPS": 500000,
        "SALES_PRICE": 700000,
        "TRANSFER_DATE": "20150102",
        "MAIL_STREET": "PO BOX 100",
        "MAIL_CITY": "LARGO",
        "MAIL_STATE": "MD",
        "MAIL_ZIP5": "20774",
        "UPDATED_DATE": 1760054400000,
    }


def test_mapping_preserves_raw_values() -> None:
    record = map_feature(_attributes(1), datetime.now(UTC))
    assert record.address == "000001 EXAMPLE RD"
    assert record.building_area_sqft == 10000
    assert record.last_sale_date is not None
    assert record.source_raw["building_area_sqft"] == "0010000"
    assert isinstance(record.source_raw["address"], dict)


def test_adapter_paginates_and_uses_cache(tmp_path: Path) -> None:
    metadata = json.loads(
        Path("docs/schemas/property_flattened_layer_0.json").read_text(encoding="utf-8")
    )
    features = [{"attributes": _attributes(index)} for index in range(1, 4)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=metadata)
        offset = int(request.url.params["resultOffset"])
        count = int(request.url.params["resultRecordCount"])
        return httpx.Response(
            200,
            json={
                "features": features[offset : offset + count],
                "exceededTransferLimit": offset + count < len(features),
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = ArcGisPropertyAdapter(client=client, cache_dir=tmp_path, page_size=2)
    first = list(adapter.records(3))
    first_call_count = calls
    second = list(adapter.records(3))

    assert [record.source_record_id for record in first] == [
        "fixture-1",
        "fixture-2",
        "fixture-3",
    ]
    assert [record.source_record_id for record in second] == [
        "fixture-1",
        "fixture-2",
        "fixture-3",
    ]
    assert first_call_count == 3
    assert calls == first_call_count
