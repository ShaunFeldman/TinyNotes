# TinyNotes

TinyNotes is a tiny FastAPI service for creating and listing short text notes. Notes are kept in memory (no database) and each write is protected by an idempotency key so resubmitting the same request returns the same note.

The actual app code lives in `TinyNotes/`. Use the commands below from the repo root — most steps start by changing into that folder.

## Run locally
```bash
cd TinyNotes
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Include the simple dev API key header on requests:
```
X-API-Key: dev-key
```

## Use the API
```bash
# Create a note (idempotent write)
curl -s -X POST http://127.0.0.1:8000/notes \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: dev-key" \\
  -H "Idempotency-Key: k1" \\
  -d '{"content":"hello world"}'

# List notes
curl -s http://127.0.0.1:8000/notes -H "X-API-Key: dev-key"

# Health and metrics
curl -s http://127.0.0.1:8000/healthz -H "X-API-Key: dev-key"
curl -s http://127.0.0.1:8000/metrics -H "X-API-Key: dev-key"
```

## Tests
```bash
cd TinyNotes
PYTHONPATH=. pytest -q
```

## Docker (optional)
```bash
cd TinyNotes
docker build -t tinynotes .
docker run -p 8080:8080 tinynotes
```

## Serverless (optional)
Minimal AWS SAM template and Lambda adapter are included so this can be deployed behind API Gateway later.
```bash
cd TinyNotes
sam validate && sam build
sam deploy --guided
```

## Notes
- All data is in-memory; it resets when the server restarts.
- The `X-API-Key: dev-key` is a local dev convenience, not a secret.
