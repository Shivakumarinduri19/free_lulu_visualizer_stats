"""
Automatic Dynamic World LULC Visualizer — FastAPI + Google Earth Engine Backend
------------------------------------------------------------------------------
Run locally:
    pip install fastapi uvicorn earthengine-api pydantic
    earthengine authenticate
    export GEE_PROJECT="your-gcp-project-id"   # optional if default project is set
    uvicorn backend:app --reload --port 8000
"""

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional

import ee
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Official Google Dynamic World V1 classes (values 0-8) and hex palette
# Source: https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1
DW_CLASSES: List[Dict[str, Any]] = [
    {"id": 0, "key": "water", "name": "Water", "color": "#419bdf"},
    {"id": 1, "key": "trees", "name": "Trees", "color": "#397d49"},
    {"id": 2, "key": "grass", "name": "Grass", "color": "#88b053"},
    {"id": 3, "key": "flooded_vegetation", "name": "Flooded Vegetation", "color": "#7a87c6"},
    {"id": 4, "key": "crops", "name": "Crops", "color": "#e49635"},
    {"id": 5, "key": "shrub_and_scrub", "name": "Shrub & Scrub", "color": "#dfc35a"},
    {"id": 6, "key": "built", "name": "Built Area", "color": "#c4281b"},
    {"id": 7, "key": "bare", "name": "Bare Ground", "color": "#a59b8f"},
    {"id": 8, "key": "snow_and_ice", "name": "Snow & Ice", "color": "#b39fe1"},
]
DW_CLASS_BY_ID = {c["id"]: c for c in DW_CLASSES}

EE_INITIALIZED = False
EE_INIT_ERROR: Optional[str] = None


def init_earth_engine() -> None:
    """Initialize Google Earth Engine using service account or local credentials."""
    global EE_INITIALIZED, EE_INIT_ERROR
    if EE_INITIALIZED:
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Automatically load local .env if present
    env_file = os.path.join(base_dir, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            pass

    # Check for service account JSON file in directory or via environment variable
    sa_file = os.getenv("GEE_SERVICE_ACCOUNT_FILE")
    if not sa_file:
        for candidate in ("service_account.json", "gee-key.json", "credentials.json"):
            candidate_path = os.path.join(base_dir, candidate)
            if os.path.exists(candidate_path):
                sa_file = candidate_path
                break

    try:
        if sa_file and os.path.exists(sa_file):
            with open(sa_file, "r", encoding="utf-8") as f:
                sa_info = json.load(f)
            sa_email = sa_info.get("client_email") or os.getenv("GEE_SERVICE_ACCOUNT_EMAIL")
            project = sa_info.get("project_id") or os.getenv("GEE_PROJECT")
            credentials = ee.ServiceAccountCredentials(sa_email, key_file=sa_file)
            ee.Initialize(credentials=credentials, project=project)
        else:
            sa_key_json = os.getenv("GEE_SERVICE_ACCOUNT_JSON")
            sa_email = os.getenv("GEE_SERVICE_ACCOUNT_EMAIL")
            project = os.getenv("GEE_PROJECT")
            if sa_key_json and sa_email:
                credentials = ee.ServiceAccountCredentials(sa_email, key_data=sa_key_json)
                ee.Initialize(credentials=credentials, project=project)
            elif project:
                ee.Initialize(project=project)
            else:
                ee.Initialize()

        EE_INITIALIZED = True
        EE_INIT_ERROR = None
    except Exception as exc:
        EE_INITIALIZED = False
        EE_INIT_ERROR = str(exc)


app = FastAPI(
    title="Dynamic World LULC Visualizer API",
    description="Automatic Land Use / Land Cover tile & zonal statistics service powered by Google Earth Engine.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    init_earth_engine()


class AnalyzeRequest(BaseModel):
    geometry: Dict[str, Any] = Field(
        ...,
        description="GeoJSON Geometry (Polygon/MultiPolygon) or GeoJSON Feature from Leaflet.draw",
    )
    start_date: date = Field(..., description="Start date (YYYY-MM-DD), earliest 2015-06-27")
    end_date: date = Field(..., description="End date (YYYY-MM-DD), exclusive upper bound or inclusive day")
    scale: int = Field(10, ge=10, le=250, description="Reduction scale in meters (default 10m native)")


class CompareRequest(BaseModel):
    geometry: Dict[str, Any] = Field(
        ...,
        description="GeoJSON Geometry (Polygon/MultiPolygon) or GeoJSON Feature from Leaflet.draw",
    )
    start_date_a: date = Field(..., description="Period A Start Date")
    end_date_a: date = Field(..., description="Period A End Date")
    start_date_b: date = Field(..., description="Period B Start Date")
    end_date_b: date = Field(..., description="Period B End Date")
    scale: int = Field(20, ge=10, le=250, description="Reduction scale in meters (default 20m for fast change detection)")


def extract_ee_geometry(geojson_obj: Dict[str, Any]) -> ee.Geometry:
    """Normalize GeoJSON Feature or Geometry into an ee.Geometry."""
    obj_type = geojson_obj.get("type")
    if obj_type == "Feature":
        geom = geojson_obj.get("geometry")
        if not geom:
            raise ValueError("GeoJSON Feature is missing 'geometry'.")
    elif obj_type == "FeatureCollection":
        features = geojson_obj.get("features", [])
        if not features:
            raise ValueError("GeoJSON FeatureCollection is empty.")
        return ee.FeatureCollection(features).geometry()
    else:
        geom = geojson_obj

    return ee.Geometry(geom)


def compute_dw_composite_and_stats(
    aoi: ee.Geometry, start_date: date, end_date: date, scale: int
) -> Dict[str, Any]:
    """Helper to compute Dynamic World mode composite tile URL and zonal statistics."""
    dw_col = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(aoi)
        .filterDate(start_date.isoformat(), end_date.isoformat())
    )

    scene_count = dw_col.size().getInfo()
    if scene_count == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No Dynamic World scenes found between {start_date} and {end_date}. Try expanding the date window.",
        )

    dw_label = dw_col.select("label").mode().clip(aoi).rename("label")

    vis_params = {
        "min": 0,
        "max": 8,
        "palette": [c["color"] for c in DW_CLASSES],
    }
    map_id = dw_label.getMapId(vis_params)
    tile_url = map_id["tile_fetcher"].url_format

    area_image = ee.Image.pixelArea().addBands(dw_label)
    grouped = area_image.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class_id"),
        geometry=aoi,
        scale=scale,
        maxPixels=1e9,
        bestEffort=True,
    ).getInfo()

    groups = grouped.get("groups", []) if grouped else []
    area_by_class_m2: Dict[int, float] = {
        int(item["class_id"]): float(item["sum"]) for item in groups
    }

    total_area_m2 = sum(area_by_class_m2.values())
    classes_out: List[Dict[str, Any]] = []

    for cls in DW_CLASSES:
        area_m2 = area_by_class_m2.get(cls["id"], 0.0)
        area_ha = area_m2 / 10_000.0
        area_km2 = area_m2 / 1_000_000.0
        pct = (area_m2 / total_area_m2 * 100.0) if total_area_m2 > 0 else 0.0
        classes_out.append(
            {
                "id": cls["id"],
                "key": cls["key"],
                "name": cls["name"],
                "color": cls["color"],
                "area_m2": round(area_m2, 2),
                "area_ha": round(area_ha, 2),
                "area_km2": round(area_km2, 4),
                "percentage": round(pct, 2),
            }
        )

    classes_sorted = sorted(classes_out, key=lambda x: x["area_m2"], reverse=True)
    dominant = classes_sorted[0] if classes_sorted else None

    return {
        "tile_url": tile_url,
        "scene_count": scene_count,
        "scale_m": scale,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_area_ha": round(total_area_m2 / 10_000.0, 2),
        "total_area_km2": round(total_area_m2 / 1_000_000.0, 4),
        "dominant_class": dominant["name"] if dominant else None,
        "classes": classes_out,
        "classes_sorted": classes_sorted,
    }


@app.get("/")
def serve_frontend() -> FileResponse:
    """Serve the interactive Leaflet frontend if placed alongside backend.py."""
    dir_path = os.path.dirname(os.path.abspath(__file__))
    for candidate in ("index.html", "dynamic_world_lulc_visualizer.html"):
        candidate_path = os.path.join(dir_path, candidate)
        if os.path.exists(candidate_path):
            return FileResponse(candidate_path)
    raise HTTPException(status_code=404, detail="index.html not found next to backend.py")


@app.get("/api/health")
def health() -> Dict[str, Any]:
    if not EE_INITIALIZED:
        init_earth_engine()
    return {
        "status": "ok" if EE_INITIALIZED else "error",
        "earth_engine_initialized": EE_INITIALIZED,
        "error": EE_INIT_ERROR,
    }


@app.post("/api/lulc/analyze")
def analyze_lulc(req: AnalyzeRequest) -> Dict[str, Any]:
    """Single period LULC composite and zonal statistics."""
    if not EE_INITIALIZED:
        init_earth_engine()
    if not EE_INITIALIZED:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not initialized: {EE_INIT_ERROR}",
        )

    if req.end_date <= req.start_date:
        raise HTTPException(status_code=400, detail="end_date must be after start_date.")

    try:
        aoi = extract_ee_geometry(req.geometry)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid GeoJSON geometry: {exc}")

    try:
        data = compute_dw_composite_and_stats(aoi, req.start_date, req.end_date, req.scale)
        # Match expected single-period format
        data["classes"] = data["classes_sorted"]
        return data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Earth Engine processing error: {exc}")


@app.post("/api/lulc/compare")
def compare_lulc(req: CompareRequest) -> Dict[str, Any]:
    """
    Multi-temporal LULC Change Detection:
    Computes composites for Period A (before) and Period B (after), computes class deltas,
    and returns XYZ tile URLs for split-panel side-by-side comparison.
    """
    if not EE_INITIALIZED:
        init_earth_engine()
    if not EE_INITIALIZED:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not initialized: {EE_INIT_ERROR}",
        )

    if req.end_date_a <= req.start_date_a:
        raise HTTPException(status_code=400, detail="Period A: end_date must be after start_date.")
    if req.end_date_b <= req.start_date_b:
        raise HTTPException(status_code=400, detail="Period B: end_date must be after start_date.")

    try:
        aoi = extract_ee_geometry(req.geometry)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid GeoJSON geometry: {exc}")

    try:
        res_a = compute_dw_composite_and_stats(aoi, req.start_date_a, req.end_date_a, req.scale)
        res_b = compute_dw_composite_and_stats(aoi, req.start_date_b, req.end_date_b, req.scale)

        map_a = {c["id"]: c for c in res_a["classes"]}
        map_b = {c["id"]: c for c in res_b["classes"]}

        deltas = []
        for cls in DW_CLASSES:
            cid = cls["id"]
            ha_a = map_a[cid]["area_ha"]
            ha_b = map_b[cid]["area_ha"]
            diff_ha = round(ha_b - ha_a, 2)
            pct_a = map_a[cid]["percentage"]
            pct_b = map_b[cid]["percentage"]
            diff_pct = round(pct_b - pct_a, 2)

            deltas.append({
                "id": cid,
                "key": cls["key"],
                "name": cls["name"],
                "color": cls["color"],
                "area_ha_a": ha_a,
                "area_ha_b": ha_b,
                "diff_ha": diff_ha,
                "pct_a": pct_a,
                "pct_b": pct_b,
                "diff_pct": diff_pct,
            })

        # Identify significant changes
        gainers = [d for d in deltas if d["diff_ha"] > 0]
        losers = [d for d in deltas if d["diff_ha"] < 0]
        gainers.sort(key=lambda x: x["diff_ha"], reverse=True)
        losers.sort(key=lambda x: x["diff_ha"])

        top_gainer = gainers[0] if gainers else None
        top_loser = losers[0] if losers else None

        summary_parts = []
        if top_gainer and top_gainer["diff_ha"] > 0.05:
            summary_parts.append(
                f"{top_gainer['name']} expanded by +{top_gainer['diff_ha']:,} ha (+{top_gainer['diff_pct']}%)"
            )
        if top_loser and abs(top_loser["diff_ha"]) > 0.05:
            summary_parts.append(
                f"{top_loser['name']} decreased by {top_loser['diff_ha']:,} ha ({top_loser['diff_pct']}%)"
            )

        summary_text = (
            f"From {req.start_date_a.year} to {req.start_date_b.year}: "
            + (", while ".join(summary_parts) + "." if summary_parts else "Land cover remained largely stable.")
        )

        return {
            "period_a": {
                **res_a,
                "classes": res_a["classes_sorted"],
            },
            "period_b": {
                **res_b,
                "classes": res_b["classes_sorted"],
            },
            "deltas": sorted(deltas, key=lambda x: abs(x["diff_ha"]), reverse=True),
            "top_gainer": top_gainer,
            "top_loser": top_loser,
            "summary": summary_text,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Earth Engine comparison error: {exc}")