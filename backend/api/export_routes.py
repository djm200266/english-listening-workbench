"""Export routes: generate and download ZIP package."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import io

from services.export_service import generate_export_zip, sanitize_filename

router = APIRouter(prefix="/api/v1/export", tags=["export"])


@router.post("/tasks/{task_id}")
def export_package(
    task_id: str,
    filename: str | None = Query(None, description="Custom ZIP filename"),
):
    """Generate ZIP package and return as download."""
    try:
        zip_bytes, default_filename, zip_size = generate_export_zip(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "message": str(e)})
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail={"error_code": "ASSET_MISSING", "message": str(e)})

    final_filename = sanitize_filename(filename or default_filename)
    encoded_filename = quote(final_filename, safe='')

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(zip_size),
            "X-Export-Filename": encoded_filename,
            "X-Export-Size": str(zip_size),
        },
    )
