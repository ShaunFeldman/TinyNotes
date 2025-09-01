from __future__ import annotations
import time
import threading
import uuid
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

app = FastAPI(title="TinyNotes API", version="1.0.0")

# ---------- Simple models ----------
class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=240)

class NoteOut(BaseModel):
    id: str
    content: str
    createdAt: int

# ---------- In-memory stores (demo only) ----------
NOTES: List[NoteOut] = []
IDEMPOTENCY: Dict[str, Dict[str, dict]] = {}  # scope -> key -> response
STORE_LOCK = threading.RLock()

def now() -> int:
    return int(time.time())

# ---------- Rate limiting (token bucket per API key) ----------
class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = rate_per_sec
        self.capacity = burst
        self.tokens = burst
        self.last = time.time()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            t = time.time()
            elapsed = t - self.last
            self.last = t
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

BUCKETS: Dict[str, TokenBucket] = {}
BUCKETS_LOCK = threading.Lock()
DEV_API_KEY = "dev-key"

def rate_limit(x_api_key: Optional[str] = Header(default=None)) -> str:
    key = x_api_key or DEV_API_KEY
    with BUCKETS_LOCK:
        bucket = BUCKETS.get(key)
        if bucket is None:
            bucket = TokenBucket(rate_per_sec=10.0, burst=20)
            BUCKETS[key] = bucket
    if not bucket.allow():
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    return key

# ---------- Metrics (simple p95 per endpoint) ----------
DURS: Dict[str, List[float]] = {}
COUNTS: Dict[str, int] = {}
METRICS_LOCK = threading.RLock()

def record_metric(name: str, dur_ms: float):
    with METRICS_LOCK:
        arr = DURS.get(name)
        if arr is None:
            arr = []
            DURS[name] = arr
        arr.append(dur_ms)
        if len(arr) > 1000:
            del arr[: len(arr) - 1000]
        COUNTS[name] = COUNTS.get(name, 0) + 1

def p95(arr: List[float]) -> float:
    if not arr:
        return 0.0
    s = sorted(arr)
    idx = max(0, int(round(0.95 * (len(s))) - 1))
    return s[idx]

@app.middleware("http")
async def timing_mw(request: Request, call_next):
    start = time.time()
    try:
        return await call_next(request)
    finally:
        dur = (time.time() - start) * 1000.0
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        name = f"{request.method} {path}"
        record_metric(name, dur)

# ---------- Endpoints ----------
@app.get("/healthz", response_class=PlainTextResponse)
async def healthz(_: str = Depends(rate_limit)):
    return "ok"

@app.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(
    body: NoteCreate,
    idem_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    _: str = Depends(rate_limit),
):
    if not idem_key:
        raise HTTPException(status_code=400, detail="missing Idempotency-Key header")
    # return saved response if key was used
    with STORE_LOCK:
        saved = IDEMPOTENCY.get("create_note", {}).get(idem_key)
    if saved:
        return JSONResponse(saved, status_code=201)

    note = NoteOut(id=str(uuid.uuid4())[:8], content=body.content, createdAt=now())
    NOTES.append(note)
    IDEMPOTENCY.setdefault("create_note", {})[idem_key] = note.model_dump()
    return JSONResponse(note.model_dump(), status_code=201)

@app.get("/notes", response_model=List[NoteOut])
async def list_notes(_: str = Depends(rate_limit)):
    with STORE_LOCK:
        return [n.model_dump() for n in NOTES]

@app.get("/metrics")
async def metrics(_: str = Depends(rate_limit)):
    with METRICS_LOCK:
        snap = {k: {"count": COUNTS.get(k, 0), "p95_ms": round(p95(v), 2)} for k, v in DURS.items()}
    return snap

# AWS Lambda adapter (optional)
try:
    from mangum import Mangum
    handler = Mangum(app)
except Exception:  # pragma: no cover
    handler = None
