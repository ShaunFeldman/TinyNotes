from __future__ import annotations
import time
import threading
import uuid
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="TinyNotes API",
    version="1.0.0",
    description="A tiny in-memory notes API with idempotency, rate limits, and simple metrics.",
)

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
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home():
    return """
    <!doctype html>
    <html lang=\"en\">
    <head>
      <meta charset=\"utf-8\" />
      <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
      <title>TinyNotes</title>
      <style>
        body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; max-width: 820px; }}
        header {{ margin-bottom: 16px; }}
        h1 {{ margin: 0 0 4px 0; }}
        .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin: 12px 0; }}
        label {{ display: block; font-weight: 600; margin: 8px 0 4px; }}
        input[type=text], textarea {{ width: 100%; padding: 8px; border: 1px solid #e5e7eb; border-radius: 6px; }}
        button {{ background: #111827; color: white; border: none; border-radius: 6px; padding: 8px 12px; cursor: pointer; }}
        button:disabled {{ opacity: .6; cursor: default; }}
        .row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
        .muted {{ color: #6b7280; }}
        pre {{ background: #f8fafc; padding: 12px; border-radius: 8px; overflow: auto; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
        .right {{ text-align: right; }}
      </style>
    </head>
    <body>
      <header>
        <h1>TinyNotes</h1>
        <div class=\"muted\">Create and list short notes. Idempotent writes. Simple metrics.</div>
      </header>

      <div class=\"card\">
        <div class=\"row\">
          <div style=\"flex:1\">
            <label>API key header (X-API-Key)</label>
            <input id=\"apiKey\" type=\"text\" value=\"dev-key\" />
          </div>
          <div>
            <label>&nbsp;</label>
            <button onclick=\"ping()\">Check health</button>
          </div>
        </div>
        <div id=\"health\" class=\"muted\"></div>
      </div>

      <div class=\"card\">
        <label>New note</label>
        <textarea id=\"content\" rows=\"3\" placeholder=\"Write something short...\"></textarea>
        <div class=\"row\">
          <div style=\"flex:1\">
            <label>Idempotency-Key (auto if blank)</label>
            <input id=\"idem\" type=\"text\" placeholder=\"e.g., k1\" />
          </div>
          <div>
            <label>&nbsp;</label>
            <button id=\"createBtn\" onclick=\"createNote()\">Create note</button>
          </div>
        </div>
        <div id=\"createOut\" class=\"muted\"></div>
      </div>

      <div class=\"card\">
        <div class=\"row\">
          <h3 style=\"margin:0;flex:1\">Notes</h3>
          <button onclick=\"listNotes()\">Refresh</button>
        </div>
        <table id=\"notesTable\">
          <thead><tr><th>ID</th><th>Content</th><th class=\"right\">Created</th></tr></thead>
          <tbody id=\"notesBody\"></tbody>
        </table>
      </div>

      <div class=\"card\">
        <div class=\"row\">
          <h3 style=\"margin:0;flex:1\">Metrics</h3>
          <button onclick=\"loadMetrics()\">Refresh</button>
        </div>
        <pre id=\"metrics\" class=\"muted\"></pre>
      </div>

      <p class=\"muted\">Tip: Full API docs at <a href=\"/docs\">/docs</a></p>

      <script>
        const $ = (id) => document.getElementById(id);
        const headers = () => ({ 'Content-Type': 'application/json', 'X-API-Key': $('apiKey').value || '' });
        const fmtTime = (ts) => new Date(ts * 1000).toLocaleString();
        const genIdem = () => 'k-' + Math.random().toString(16).slice(2,10);

        async function ping() {
          $('health').textContent = 'Checking...';
          const r = await fetch('/healthz', { headers: headers() });
          $('health').textContent = r.ok ? 'ok' : ('err ' + r.status);
        }

        async function createNote() {
          const content = $('content').value.trim();
          if (!content) { $('createOut').textContent = 'Please enter content'; return; }
          const key = $('idem').value.trim() || genIdem();
          $('idem').value = key;
          $('createBtn').disabled = true;
          $('createOut').textContent = 'Creating...';
          const r = await fetch('/notes', { method: 'POST', headers: { ...headers(), 'Idempotency-Key': key }, body: JSON.stringify({ content }) });
          $('createBtn').disabled = false;
          if (!r.ok) { $('createOut').textContent = 'Error ' + r.status; return; }
          const note = await r.json();
          $('createOut').textContent = 'Created ' + note.id + ' at ' + fmtTime(note.createdAt);
          $('content').value = '';
          listNotes();
        }

        async function listNotes() {
          const r = await fetch('/notes', { headers: headers() });
          const body = $('notesBody');
          body.innerHTML = '';
          if (!r.ok) { body.innerHTML = '<tr><td colspan=3>Error ' + r.status + '</td></tr>'; return; }
          const notes = await r.json();
          if (!notes.length) { body.innerHTML = '<tr><td colspan=3 class=\"muted\">No notes yet</td></tr>'; return; }
          for (const n of notes) {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${n.id}</td><td>${n.content}</td><td class=\"right\">${fmtTime(n.createdAt)}</td>`;
            body.appendChild(tr);
          }
        }

        async function loadMetrics() {
          const r = await fetch('/metrics', { headers: headers() });
          const data = r.ok ? await r.json() : { error: r.status };
          $('metrics').textContent = JSON.stringify(data, null, 2);
        }

        // initial load
        listNotes();
        ping();
        loadMetrics();
      </script>
    </body>
    </html>
    """

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
    # idempotency check and create within a single critical section
    with STORE_LOCK:
        saved = IDEMPOTENCY.get("create_note", {}).get(idem_key)
        if saved:
            return saved

        note = NoteOut(id=str(uuid.uuid4())[:8], content=body.content, createdAt=now())
        NOTES.append(note)
        IDEMPOTENCY.setdefault("create_note", {})[idem_key] = note.model_dump()
        return note

@app.get("/notes", response_model=List[NoteOut])
async def list_notes(_: str = Depends(rate_limit)):
    with STORE_LOCK:
        return NOTES

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
