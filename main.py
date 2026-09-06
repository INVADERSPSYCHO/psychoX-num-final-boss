import os
import requests
import pyarrow.parquet as pq
import io
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from starlette.responses import JSONResponse
from datetime import datetime, timedelta

# ── CONFIG ──────────────────────────────────────────────
API_KEY = os.environ.get("API_KEY", "psychoxd")  # 🔥 Env se lo, nahi toh default
DEVELOPER = "@psychopathmc"
SUPPORT_MSG = "For API purchase, contact @psychopathmc"
BASE_URL = "https://huggingface.co/datasets/Kzr0xx/icrm-hitek-full-db-mixed/resolve/main"  # 🔥 FIXED
CACHE_TTL = 300

app = FastAPI(title="PsychopathMC OSINT API", version="10.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(FastAPIHTTPException)
async def custom_http_exception_handler(request: Request, exc: FastAPIHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "developer": DEVELOPER,
            "support": SUPPORT_MSG,
        }
    )

# ── Helper: Circle Lookup ──────────────────────────────
def get_circle(num: str) -> str:
    prefixes = {
        "9810": "AIRTEL DELHI", "9871": "AIRTEL DELHI", "9818": "AIRTEL DELHI",
        "9910": "VI DELHI", "8826": "JIO DELHI", "9999": "AIRTEL DELHI",
        "9971": "AIRTEL DELHI", "9883": "JIO WB", "9564": "JIO WB",
    }
    pref = num[:4]
    return prefixes.get(pref, "UNKNOWN CIRCLE")

# ── Simple Cache ─────────────────────────────────────────
_cache = {}
_cache_time = {}

def get_cache(url, column, value):
    key = f"{url}|{column}|{value}"
    if key in _cache and (datetime.now() - _cache_time[key]).seconds < CACHE_TTL:
        return _cache[key]
    return None

def set_cache(url, column, value, data):
    key = f"{url}|{column}|{value}"
    _cache[key] = data
    _cache_time[key] = datetime.now()
    if len(_cache) > 100:
        oldest = min(_cache_time, key=_cache_time.get)
        del _cache[oldest]
        del _cache_time[oldest]

# ── Fetch Logic ──────────────────────────────────────────
def fetch_data(url: str, column: str, value: str, limit: int = 15):
    cached = get_cache(url, column, value)
    if cached is not None:
        return cached

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []
        needed_cols = ["name", "fathersName", "phoneNumber", "aadharNumber", "otherNumber", "address"]
        table = pq.read_table(io.BytesIO(resp.content), columns=needed_cols)
        df = table.to_pandas()
        if column not in df.columns:
            return []
        filtered = df[df[column] == value]
        results = filtered.head(limit).to_dict(orient="records")
        set_cache(url, column, value, results)
        return results
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

# ── Endpoints ────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "message": "PsychoAPI is live. Use /psychoapi?Number=XXX&key=psychoxd",
        "developer": DEVELOPER,
        "support": SUPPORT_MSG,
    }

# 🔥 1. Naya Endpoint – /psychoapi (Jaisa tune manga tha)
@app.get("/psychoapi")
def psychoapi(
    Number: str = Query(..., description="Phone number"),
    key: str = Query(..., description="API Key"),
    limit: int = Query(15, ge=1, le=50)
):
    # Key Check
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not Number.isdigit():
        raise HTTPException(status_code=400, detail="Invalid number format")

    last_digit = Number[-1]
    shard = int(last_digit) % 7

    phone_url = f"{BASE_URL}/idx_phone.{shard}.parquet"
    results = fetch_data(phone_url, "phoneNumber", Number, limit)

    if not results:
        aadhar_url = f"{BASE_URL}/idx_aadhar.{shard}.parquet"
        results = fetch_data(aadhar_url, "aadharNumber", Number, limit)

    # Deduplicate
    seen = set()
    unique_results = []
    for row in results:
        aadhar_val = row.get("aadharNumber")
        if aadhar_val not in seen:
            seen.add(aadhar_val)
            unique_results.append(row)
    results = unique_results

    formatted = []
    for row in results:
        formatted.append({
            "num": row.get("phoneNumber"),
            "name": row.get("name"),
            "fname": row.get("fathersName"),
            "aadhar": row.get("aadharNumber"),
            "address": row.get("address"),
            "circle": get_circle(Number),
            "email": None,
            "alt": row.get("otherNumber"),
        })

    return {
        "response": {
            "parameters": {
                "value": Number,
                "service": "phone number info",
                "success": len(formatted) > 0
            },
            "data": formatted
        },
        "developer": DEVELOPER,
        "support": SUPPORT_MSG,
    }

# 🔥 2. Purana Endpoint – /search (Backward compatibility ke liye)
@app.get("/search")
def search(
    q: str | None = Query(None),
    mobile: str | None = Query(None),
    key: str = Query(...),  # mandatory
    limit: int = Query(5, ge=1, le=20)
):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    query = (q or mobile or "").strip()
    if not query:
        raise HTTPException(422, "Provide q or mobile")

    last_digit = query[-1]
    shard = int(last_digit) % 7

    phone_url = f"{BASE_URL}/idx_phone.{shard}.parquet"
    results = fetch_data(phone_url, "phoneNumber", query, limit)

    if not results:
        aadhar_url = f"{BASE_URL}/idx_aadhar.{shard}.parquet"
        results = fetch_data(aadhar_url, "aadharNumber", query, limit)

    # Deduplicate
    seen = set()
    unique_results = []
    for row in results:
        aadhar_val = row.get("aadharNumber")
        if aadhar_val not in seen:
            seen.add(aadhar_val)
            unique_results.append(row)
    results = unique_results

    return {
        "success": len(results) > 0,
        "query": query,
        "count": len(results),
        "results": results,
        "developer": DEVELOPER,
        "support": SUPPORT_MSG,
    }
