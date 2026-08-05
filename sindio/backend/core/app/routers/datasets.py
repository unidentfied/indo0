from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..services.dataset_catalog import list_datasets, get_dataset

datasets_router = APIRouter(prefix="/datasets", tags=["datasets"])


@datasets_router.get("/")
async def api_list_datasets(category: str | None = Query(None)):
    return list_datasets(category=category)


@datasets_router.get("/{dataset_id}")
async def api_get_dataset(dataset_id: str):
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    return dataset


@datasets_router.get("/{dataset_id}/download")
async def api_download_dataset(dataset_id: str):
    dataset = get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")

    fmt = dataset["format"]
    fields = dataset["fields"]

    if fmt == "geojson":
        sample = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [36.8219, -1.2833],
                    },
                    "properties": {
                        f["name"]: "sample_value" if f["type"] == "string" else 0.0
                        for f in fields
                    },
                }
            ],
            "metadata": {
                "dataset_id": dataset["id"],
                "name": dataset["name"],
                "record_count": dataset["record_count"],
                "note": "This is a sample. For full data access, use the API endpoint.",
            },
        }
        return Response(
            content=json.dumps(sample, indent=2),
            media_type="application/geo+json",
            headers={"Content-Disposition": f"attachment; filename={dataset_id}.geojson"},
        )

    elif fmt == "csv":
        headers_line = ",".join(f["name"] for f in fields)
        sample_rows = [
            ",".join("sample" if f["type"] == "string" else "0" for f in fields)
            for _ in range(3)
        ]
        csv_content = headers_line + "\n" + "\n".join(sample_rows)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={dataset_id}.csv"},
        )

    elif fmt == "json":
        sample = {
            "dataset": dataset["id"],
            "name": dataset["name"],
            "sample_records": [
                {f["name"]: "sample" if f["type"] == "string" else 0 for f in fields}
                for _ in range(3)
            ],
            "note": "This is a sample. For full data access, use the API endpoint: " + dataset["api_endpoint"],
        }
        return Response(
            content=json.dumps(sample, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={dataset_id}.json"},
        )

    return {"message": f"Download not available for format '{fmt}'", "dataset": dataset["name"]}
