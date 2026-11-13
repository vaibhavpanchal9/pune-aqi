"""Step 10 (3/3), part b. The service: three endpoints over the forecasts table.

    uvicorn app:app --reload          # then open http://127.0.0.1:8000/docs
    pytest tests/test_api.py -v

    GET /            what is here
    GET /health      is the pipeline alive: newest reading, last run, forecasts on file. Always 200;
                     the "status" field says ok / upstream_lag / broken, same rules as healthcheck.py
    GET /forecast    the forecasts on file for the hours ahead, with the 80% band and the tier
                     of the model that made each one (full / day / short)
                     404 for a sensor without a model, 422 for a sensor_id that is not a number
    GET /stats       live accuracy so far (as issued, never revised) overall, per tier and per model
                     version, next to the walk-forward figures, plus lead time and availability

FastAPI validates the inputs and the outputs against the Pydantic models below, and writes the
interactive documentation at /docs from them. service.py does the database work.
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import service

IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(
    title="Pune AQI forecast",
    version=service.MODEL_VERSION,
    description=(
        "PM2.5 forecasts 24 hours ahead for one reference-grade station in Pune, issued hourly by an "
        "unattended pipeline (OpenAQ -> Postgres -> ridge model). Every forecast is stored once and "
        "scored against the reading that arrives a day later: /stats is the live, out-of-sample record."
    ),
)


# ----------------------------------------------------------------------------- response models
class ForecastRow(BaseModel):
    target_time: datetime = Field(description="the hour being forecast, UTC")
    target_time_ist: str = Field(description="the same hour in Indian Standard Time, for reading")
    lead_hours: float = Field(description="how far ahead this forecast is, from now")
    point: float = Field(description="PM2.5 forecast, µg/m³")
    lower: float = Field(description="10th percentile")
    upper: float = Field(description="90th percentile")
    issued_at: datetime
    tier: str = Field(description="which tier of the model made it: full, day or short (fewer lags)")


class ForecastResponse(BaseModel):
    sensor_id: int
    station: Optional[str]
    model_version: str
    horizon_hours: int
    band: str
    data_as_of: Optional[datetime] = Field(description="the newest reading hour the forecasts used")
    generated_at: datetime
    forecasts: list[ForecastRow]


class HealthResponse(BaseModel):
    status: str = Field(description="ok | upstream_lag | broken")
    checked_at: datetime
    pipeline: dict
    data: dict
    forecasts: dict


class StatsResponse(BaseModel):
    sensor_id: int
    model_version: str
    live: dict
    live_by_tier: list[dict]
    live_by_version: list[dict]
    lead_time: dict
    availability_7d: dict
    tiers: list[dict]
    walk_forward: Optional[dict]
    trained_on: dict


# ----------------------------------------------------------------------------- routes
@app.get("/", include_in_schema=False)
def root():
    return {"service": "pune-aqi", "docs": "/docs",
            "endpoints": ["/health", f"/forecast?sensor_id={service.SENSOR}", "/stats"]}


@app.get("/health", response_model=HealthResponse)
def health():
    return service.health()


@app.get("/forecast", response_model=ForecastResponse)
def forecast(sensor_id: int = Query(service.SENSOR, description="OpenAQ sensor id; only the modelled station is served")):
    if sensor_id != service.SENSOR:
        raise HTTPException(status_code=404, detail=f"no model for sensor {sensor_id}; served: {service.SENSOR}")
    data = service.forecast(sensor_id)
    now = datetime.now(timezone.utc)
    rows = []
    for r in data["forecasts"]:
        t = r["target_time"]
        rows.append({**r,
                     "target_time_ist": t.astimezone(IST).strftime("%a %d %b %H:%M IST"),
                     "lead_hours": round((t - now).total_seconds() / 3600, 1)})
    return {**data, "generated_at": now, "forecasts": rows}


@app.get("/stats", response_model=StatsResponse)
def stats():
    return service.stats()
