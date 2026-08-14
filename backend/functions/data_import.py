import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.config import load_config
from backend.core.operation_log import get_operation_log


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    import re
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m", "%B %Y", "%b %Y", "%d %B %Y",
)


def _looks_like_date_string(series) -> bool:
    """Strictly parse string values with known formats (no dateutil fallback, no warnings)."""
    s = series.dropna().head(20)
    if len(s) == 0 or any(not isinstance(v, str) for v in s):
        return False
    for fmt in _DATE_FORMATS:
        try:
            parsed = pd.to_datetime(s, format=fmt)
            if parsed.notna().all():
                return True
        except (ValueError, TypeError):
            continue
    return False


_SUFFIX_MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9}


def _to_num(v) -> float | None:
    """Parse a scalar to float, tolerating commas, currency symbols, K/M/B/% suffixes."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    s = str(v).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if not s:
        return None
    last = s[-1].upper()
    if last == "%":
        s = s[:-1].strip()
    elif last in _SUFFIX_MULTIPLIERS:
        try:
            return float(s[:-1].strip()) * _SUFFIX_MULTIPLIERS[last]
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _coerce_numeric(series) -> pd.Series:
    """Coerce a column to numeric, tolerating thousand separators / currency symbols."""
    if pd.api.types.is_numeric_dtype(series):
        return series
    try:
        return pd.to_numeric(series.map(_to_num), errors="coerce")
    except Exception:
        return pd.Series([pd.NA] * len(series), dtype="Float64", index=series.index)


def _detect_column_types(df: pd.DataFrame) -> dict[str, str]:
    """Detect column types: date, numeric, categorical."""
    detected = {"date_cols": [], "numeric_cols": [], "categorical_cols": []}

    def _looks_like_year(series) -> bool:
        try:
            vals = series.dropna().astype(float)
        except (TypeError, ValueError):
            return False
        if len(vals) == 0 or vals.min() < 1900 or vals.max() > 2100:
            return False
        return all(float(v).is_integer() for v in vals)

    for col in df.columns:
        series = df[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            detected["date_cols"].append(col)
        elif _looks_like_year(series):
            detected["date_cols"].append(col)
        elif pd.api.types.is_numeric_dtype(series):
            detected["numeric_cols"].append(col)
        else:
            coerced = _coerce_numeric(series)
            non_null = int(series.notna().sum())
            if non_null > 0 and int(coerced.notna().sum()) / non_null >= 0.9:
                detected["numeric_cols"].append(col)
            elif _looks_like_date_string(series):
                detected["date_cols"].append(col)
            else:
                detected["categorical_cols"].append(col)
    return detected


def import_data(file_id: str, sheet_name: str | None = None, header_row: int = 0) -> dict:
    """Parse Excel/CSV file and return structured data."""
    cfg = load_config()
    uploads_dir = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
    if not uploads_dir.is_absolute():
        uploads_dir = Path(__file__).resolve().parent.parent.parent / uploads_dir
    
    file_path = uploads_dir / file_id
    if not file_path.exists():
        return {"error": f"File not found: {file_id}"}
    
    try:
        if file_path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, sheet_name=sheet_name or 0, header=header_row)
        elif file_path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path, header=header_row)
        else:
            return {"error": f"Unsupported file type: {file_path.suffix}. Use .xlsx, .xls, or .csv"}
    except Exception as e:
        return {"error": f"Failed to parse file: {e}"}
    
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        return {"error": "File contains no data"}
    
    columns = list(df.columns)
    rows = df.head(100).values.tolist()
    dtypes = {col: str(df[col].dtype) for col in columns}
    sample = df.head(10).to_dict(orient="records")
    detected = _detect_column_types(df)
    
    result = {
        "file_id": file_id,
        "columns": columns,
        "dtypes": dtypes,
        "row_count": len(df),
        "sample": sample,
        "detected": detected,
    }
    
    get_operation_log().record(
        "import", "data", file_id, file_path.name,
        details={"rows": len(df), "columns": len(columns)},
    )
    
    return result


def import_data_to_store(file_id: str, sheet_name: str | None = None, header_row: int = 0, 
                         store_type: str = "research", topic: str | None = None,
                         project_name: str | None = None) -> dict:
    """Import data and store as data_points in research or project."""
    from backend.core.research_store import get_research_store
    from backend.core.project_store import get_project_store
    
    parse_result = import_data(file_id, sheet_name, header_row)
    if "error" in parse_result:
        return parse_result
    
    if store_type == "research":
        if not topic:
            return {"error": "topic is required for research store"}
        store = get_research_store()
        project = store._find_by_topic(topic)
        if not project:
            return {"error": f"Research '{topic}' not found"}
        
        df = _read_file_as_df(file_id, sheet_name, header_row)
        data_points = _convert_df_to_data_points(df, parse_result["detected"])
        if not data_points:
            return {"error": "No numeric data found in the file — nothing was imported. Make sure at least one column contains numbers (years, counts, amounts)."}
        
        for dp in data_points:
            store.add_data_point(
                topic, dp["label"], str(dp["value"]), 
                dp.get("unit"), dp.get("confidence"), dp.get("sources", [])
            )
        
        return {
            "message": f"Imported {len(data_points)} data points into research '{topic}'",
            "data_points": len(data_points),
            "detected": parse_result["detected"],
        }
    
    elif store_type == "project":
        if not project_name:
            return {"error": "project_name is required for project store"}
        store = get_project_store()
        project = store.find_project_by_name(project_name)
        if not project:
            return {"error": f"Project '{project_name}' not found"}
        
        df = _read_file_as_df(file_id, sheet_name, header_row)
        data_points = _convert_df_to_data_points(df, parse_result["detected"])
        if not data_points:
            return {"error": "No numeric data found in the file — nothing was imported. Make sure at least one column contains numbers (years, counts, amounts)."}
        
        for dp in data_points:
            store.add_data_point(
                project["id"], dp["label"], str(dp["value"]),
                dp.get("unit"), dp.get("confidence"), dp.get("sources", [])
            )
        
        return {
            "message": f"Imported {len(data_points)} data points into project '{project_name}'",
            "data_points": len(data_points),
            "detected": parse_result["detected"],
        }
    
    return {"error": f"Invalid store_type: {store_type}. Must be 'research' or 'project'"}


def _read_file_as_df(file_id: str, sheet_name: str | None = None, header_row: int = 0) -> pd.DataFrame:
    cfg = load_config()
    uploads_dir = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
    if not uploads_dir.is_absolute():
        uploads_dir = Path(__file__).resolve().parent.parent.parent / uploads_dir
    
    file_path = uploads_dir / file_id
    if file_path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(file_path, sheet_name=sheet_name or 0, header=header_row)
    elif file_path.suffix.lower() == ".csv":
        return pd.read_csv(file_path, header=header_row)
    raise ValueError(f"Unsupported file type: {file_path.suffix}")


def _fmt_value(v) -> str:
    """Normalize display value: integral floats show as ints (2020.0 → 2020)."""
    try:
        f = float(v)
        if f.is_integer():
            return str(int(f))
        return str(f)
    except (TypeError, ValueError):
        return str(v)


def _convert_df_to_data_points(df: pd.DataFrame, detected: dict) -> list[dict]:
    data_points = []
    date_cols = detected.get("date_cols", [])
    numeric_cols = detected.get("numeric_cols", [])
    categorical_cols = detected.get("categorical_cols", [])

    df = df.copy()
    for num_col in numeric_cols:
        df[num_col] = _coerce_numeric(df[num_col])

    for idx, row in df.iterrows():
        for num_col in numeric_cols:
            val = row[num_col]
            try:
                num_val = float(val)
            except (TypeError, ValueError):
                continue
            if pd.isna(num_val):
                continue
            label_parts = []
            for cat_col in categorical_cols:
                cat_val = row[cat_col]
                if pd.notna(cat_val):
                    label_parts.append(f"{cat_val}")
            for date_col in date_cols:
                date_val = row[date_col]
                if pd.notna(date_val):
                    label_parts.append(_fmt_value(date_val))

            label = " | ".join(label_parts) if label_parts else f"Row {idx}"
            data_points.append({
                "label": label,
                "value": _fmt_value(num_val),
                "unit": "",
                "confidence": "high",
                "sources": [f"imported_from_file_row_{idx}"],
            })

    return data_points


def list_imported_files() -> list[dict]:
    """List all files in uploads directory."""
    cfg = load_config()
    uploads_dir = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
    if not uploads_dir.is_absolute():
        uploads_dir = Path(__file__).resolve().parent.parent.parent / uploads_dir
    
    if not uploads_dir.exists():
        return []
    
    files = []
    for f in uploads_dir.iterdir():
        if f.is_file() and f.suffix.lower() in (".xlsx", ".xls", ".csv"):
            files.append({
                "file_id": f.name,
                "name": f.name,
                "size": f.stat().st_size,
                "modified": _utcnow(),
            })
    return files


def save_uploaded_file(file_content: bytes, filename: str) -> str:
    """Save uploaded file to uploads directory and return file_id."""
    cfg = load_config()
    uploads_dir = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
    if not uploads_dir.is_absolute():
        uploads_dir = Path(__file__).resolve().parent.parent.parent / uploads_dir
    
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    file_id = f"{uuid.uuid4().hex[:12]}_{filename}"
    file_path = uploads_dir / file_id
    file_path.write_bytes(file_content)
    
    return file_id