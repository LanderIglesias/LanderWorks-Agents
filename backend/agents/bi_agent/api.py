"""api.py — Endpoints FastAPI del BI Agent (con soporte de gráficas)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .anomaly_detector import scan_dataset
from .data_loader import (
    create_session_id,
    delete_session,
    get_session,
    load_csv,
    session_exists,
)
from .demo_template import demo_html
from .engine import answer_question

load_dotenv()

router = APIRouter(prefix="/bi-agent", tags=["bi-agent"])

UPLOAD_DIR = Path(tempfile.gettempdir()) / "bi_agent_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_DATA_PATH = Path(__file__).resolve().parent / "data" / "saas_metrics.csv"
MAX_CSV_SIZE_BYTES = 10 * 1024 * 1024


# ── Schemas ──────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    session_id: str
    question: str


class AskResponse(BaseModel):
    success: bool
    answer: str
    code: str | None = None
    result: dict | list | str | int | float | None = None
    result_type: str | None = None
    error: str | None = None
    chart: str | None = None  # base64 PNG — NUEVO
    trace: list[str] = []
    subtasks: list[dict] = []
    anomalies: list[dict] = []


class UploadResponse(BaseModel):
    session_id: str
    rows: int
    columns: list[str]
    schema: dict
    filename: str


class ScanAnomaliesRequest(BaseModel):
    session_id: str


class ScanAnomaliesResponse(BaseModel):
    success: bool
    anomalies: list[dict]
    raw_count: int
    summary: str


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(file: UploadFile = File(...)):  # noqa: B008
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV.")

    content = await file.read()
    if len(content) > MAX_CSV_SIZE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"CSV exceeds {MAX_CSV_SIZE_BYTES // 1024 // 1024} MB limit."
        )

    session_id = create_session_id()
    csv_path = UPLOAD_DIR / f"{session_id}.csv"
    csv_path.write_bytes(content)

    try:
        result = load_csv(str(csv_path), session_id=session_id)
        return UploadResponse(
            session_id=result["session_id"],
            rows=result["rows"],
            columns=result["columns"],
            schema=result["schema"],
            filename=file.filename,
        )
    except Exception as e:
        delete_session(session_id)
        raise HTTPException(status_code=500, detail=f"Failed to load CSV: {e}") from e
    finally:
        if csv_path.exists():
            csv_path.unlink()


@router.get("/sample")
def load_sample_data():
    if not SAMPLE_DATA_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="Sample dataset not found. Run: python backend/agents/bi_agent/generate_sample_data.py",
        )
    try:
        result = load_csv(SAMPLE_DATA_PATH)
        return {
            "session_id": result["session_id"],
            "rows": result["rows"],
            "columns": result["columns"],
            "schema": result["schema"],
            "filename": "saas_metrics.csv (sample)",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load sample: {e}") from e


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    if not payload.session_id or not payload.question.strip():
        raise HTTPException(status_code=400, detail="session_id and question are required.")

    if not session_exists(payload.session_id):
        raise HTTPException(
            status_code=404, detail="Session not found. Upload a CSV first at /bi-agent/upload."
        )

    try:
        result = answer_question(payload.session_id, payload.question)
        return AskResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error answering question: {e}") from e


@router.post("/scan-anomalies", response_model=ScanAnomaliesResponse)
def scan_anomalies(payload: ScanAnomaliesRequest):
    if not session_exists(payload.session_id):
        raise HTTPException(status_code=404, detail="Session not found.")

    session = get_session(payload.session_id)
    df = session["df"]
    schema = session["schema"]

    date_col = _find_column(schema, ["date", "time"])
    id_col = _find_column(schema, ["_id", "id"], suffix_match=True)

    raw_anomalies = scan_dataset(df, date_col=date_col, id_col=id_col)

    if not raw_anomalies:
        return ScanAnomaliesResponse(
            success=True,
            anomalies=[],
            raw_count=0,
            summary="No significant anomalies detected in the dataset.",
        )

    interpreted = _interpret_anomalies(raw_anomalies, df)
    high = sum(1 for a in interpreted if a.get("severity") == "high")
    medium = sum(1 for a in interpreted if a.get("severity") == "medium")
    summary = _build_summary(high, medium, len(interpreted))

    return ScanAnomaliesResponse(
        success=True,
        anomalies=interpreted,
        raw_count=len(raw_anomalies),
        summary=summary,
    )


@router.get("/session/{session_id}")
def get_session_info(session_id: str):
    if not session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    session = get_session(session_id)
    return {
        "session_id": session_id,
        "schema": session["schema"],
        "source": session["source"],
        "rows": len(session["df"]),
    }


@router.delete("/session/{session_id}")
def delete_session_endpoint(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"ok": True, "message": f"Session {session_id} deleted."}


@router.get("/demo", response_class=HTMLResponse)
def serve_demo():
    return HTMLResponse(content=demo_html())


# ── Helpers ──────────────────────────────────────────────────────────────


def _find_column(schema: dict, keywords: list[str], suffix_match: bool = False) -> str | None:
    for col in schema.get("columns", []):
        name = col["name"].lower()
        for kw in keywords:
            if suffix_match:
                if name.endswith(kw.lower()):
                    return col["name"]
            else:
                if kw.lower() in name:
                    return col["name"]
    return None


def _interpret_anomalies(raw_anomalies: list[dict], df) -> list[dict]:
    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    except Exception:
        return _fallback_format(raw_anomalies)

    high = [a for a in raw_anomalies if a.get("severity") == "high"]
    medium = [a for a in raw_anomalies if a.get("severity") == "medium"]
    top = (high + medium)[:10]
    if not top:
        top = raw_anomalies[:5]

    system = """You are a data analyst turning raw statistical anomalies into business-language alerts.

For each anomaly, write a 1-2 sentence explanation in business terms with the actual values.

Return ONLY a JSON array, no preamble:
[
  {
    "severity": "high" | "medium" | "low",
    "title": "Short title (max 8 words)",
    "message": "1-2 sentences with concrete values and a hypothesis for why",
    "metric": "the metric involved"
  }
]
"""

    anomalies_str = _format_for_prompt(top)
    dataset_size = f"{len(df)} rows, {df.shape[1]} columns"
    cols = ", ".join(df.columns.tolist()[:15])

    user_msg = f"""Dataset: {dataset_size}
Columns: {cols}

Statistical anomalies found:
{anomalies_str}

Interpret them."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=system,
            messages=[
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": "["},
            ],
        )
        raw = "[" + response.content[0].text
        return _parse_json_array(raw) or _fallback_format(top)
    except Exception:
        return _fallback_format(top)


def _format_for_prompt(anomalies: list[dict]) -> str:
    lines = []
    for i, a in enumerate(anomalies, start=1):
        lines.append(f"Anomaly {i} [{a['severity']}]:")
        lines.append(f"  Type: {a['type']}")
        lines.append(f"  Metric: {a['metric']}")
        for k, v in a["details"].items():
            lines.append(f"  {k}: {v}")
        lines.append("")
    return "\n".join(lines)


def _parse_json_array(raw: str) -> list[dict]:
    import json

    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("[")
    if start == -1:
        return []

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(raw)):
        char = raw[i]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                candidate = raw[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    return []
    return []


def _fallback_format(raw_anomalies: list[dict]) -> list[dict]:
    formatted = []
    for a in raw_anomalies[:8]:
        details = a.get("details", {})
        title = f"{a.get('type', 'anomaly').title()} in {a.get('metric', 'data')}"
        message = ", ".join(f"{k}={v}" for k, v in details.items())
        formatted.append(
            {
                "severity": a.get("severity", "medium"),
                "title": title,
                "message": message,
                "metric": a.get("metric", "unknown"),
            }
        )
    return formatted


def _build_summary(high: int, medium: int, total: int) -> str:
    if total == 0:
        return "No significant anomalies detected in the dataset."
    if high > 0:
        return f"{total} anomalies detected — {high} high severity. Review the alerts below."
    if medium > 0:
        return f"{total} anomalies detected — {medium} medium severity. Worth investigating."
    return f"{total} minor anomalies detected. No critical issues."
