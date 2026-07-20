"""Sindio — Server-Sent Events (SSE) Real-Time Streaming
==========================================================
Provides live alert feeds and stress monitoring updates to the frontend
without WebSocket complexity. Compatible with all HTTP clients.

Endpoint: GET /api/v1/stream/alerts
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models import Alert
from app.mock_simulation import generate_alerts

logger = logging.getLogger("sindio.streaming")

router = APIRouter()


async def _alert_stream() -> AsyncGenerator[str, None]:
    """Generate SSE-formatted alert events every 30 seconds."""
    while True:
        try:
            alerts = generate_alerts(count=3)
            payload = {
                "type": "alerts",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": alerts,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Alert stream error: %s", exc)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
            await asyncio.sleep(5)


@router.get("/stream/alerts")
async def stream_alerts(request: Request):
    """Stream real-time alerts via Server-Sent Events.

    Client usage:
        const source = new EventSource('/api/v1/stream/alerts');
        source.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    return StreamingResponse(
        _alert_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


async def _stress_stream() -> AsyncGenerator[str, None]:
    """Generate SSE-formatted stress summary every 60 seconds."""
    while True:
        try:
            from app.routers.api import _INFRA_TYPES
            import random
            summary = []
            for t in _INFRA_TYPES:
                summary.append({
                    "infrastructure_type": t["name"],
                    "display_name": t["display_name"],
                    "avg_stress": round(random.uniform(0.15, 0.45), 3),
                    "critical_count": random.randint(0, 5),
                })

            payload = {
                "type": "stress_summary",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": summary,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Stress stream error: %s", exc)
            await asyncio.sleep(5)


@router.get("/stream/stress")
async def stream_stress(request: Request):
    """Stream real-time stress summaries via SSE."""
    return StreamingResponse(
        _stress_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
