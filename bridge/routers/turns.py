"""HTTP façade for bridge-owned durable Chat and Agent turns."""
from __future__ import annotations

import json
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from ..core.appctx import app
from ..core.turns import TurnConflict, turns


def _body_for_lane(body: dict, lane: str) -> dict:
    # The durable route names the lane explicitly; the existing producers retain
    # their established request shapes.
    out = dict(body)
    out["mode"] = "chat" if lane == "chat" else "agent"
    return out


async def _producer(body: dict, lane: str):
    if lane == "chat":
        from .chat import direct_events
        stream = await direct_events(_body_for_lane(body, lane))
    else:
        from .odychat import agent_events
        stream = await agent_events(_body_for_lane(body, lane))
    async for chunk in stream:
        yield chunk


async def _start(body: dict, record: dict) -> None:
    # Capture a copy before task scheduling.  In particular, do not retain a Request
    # object (its body/lifecycle belongs to the disconnected browser).
    frozen = dict(body)
    await turns.start(record["id"], lambda: _producer(frozen, record["lane"]))


@app.post("/api/turns", status_code=202)
async def create_turn(req: Request):
    try:
        body = await req.json()
    except Exception as exc:
        raise HTTPException(400, "turn request must be JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "turn request must be an object")
    try:
        record, created = await turns.create(body)
    except TurnConflict as exc:
        return JSONResponse(status_code=409, content={
            "id": exc.turn_id,
            "error": "a turn is already running for this session; return to its lane or press Stop",
        })
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if created:
        await _start(body, record)
        record = (await turns.metadata(record["id"])) or record
    content = {k: record[k] for k in ("id", "state", "lane", "session")}
    content["instance"] = turns.instance_id
    return JSONResponse(status_code=202, content=content)


@app.get("/api/turns/active")
async def active_turn(lane: str, session: str):
    try:
        return {"turn": await turns.active(lane, session), "instance": turns.instance_id}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/turns/{turn_id}")
async def turn_metadata(turn_id: str):
    record = await turns.metadata(turn_id)
    if not record:
        raise HTTPException(404, "turn not found")
    return record


@app.get("/api/turns/{turn_id}/events")
async def turn_events(turn_id: str, after: int = 0):
    if after < 0:
        raise HTTPException(400, "after must be non-negative")
    subscription = await turns.subscribe(turn_id, after)
    if subscription is None:
        raise HTTPException(404, "turn not found")
    events, release = subscription

    async def stream():
        async for event in events:
            # Every data frame is a committed event.  Starlette cancelling this
            # response closes only this iterator; the producer task remains owned by
            # TurnStore.
            yield "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"},
                             background=BackgroundTask(release))


@app.post("/api/turns/{turn_id}/stop")
async def stop_turn(turn_id: str):
    record = await turns.stop(turn_id)
    if not record:
        raise HTTPException(404, "turn not found")
    return record
