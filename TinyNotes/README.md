# TinyNotes (Python / FastAPI)

This is a tiny REST API I built to learn the basics that show up on SWE internship job posts:
- REST endpoints with Python/FastAPI
- OpenAPI docs (auto at `/docs`)
- JSON validation
- Rate limiting (token bucket)
- Idempotency keys on writes
- Simple p95 metrics per endpoint
- CI with GitHub Actions
- Optional Dockerfile and a minimal AWS SAM template so I can deploy later

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
I use a simple dev API key. On requests, include:
```
X-API-Key: dev-key
```

## Example
```bash
# Create a note (idempotent write)
curl -s -X POST http://127.0.0.1:8000/notes   -H "Content-Type: application/json"   -H "X-API-Key: dev-key"   -H "Idempotency-Key: k1"   -d '{"content":"hello world"}'

# List notes
curl -s http://127.0.0.1:8000/notes -H "X-API-Key: dev-key"

# Health + metrics (includes p95)
curl -s http://127.0.0.1:8000/healthz -H "X-API-Key: dev-key"
curl -s http://127.0.0.1:8000/metrics -H "X-API-Key: dev-key"
```

## Tests
```bash
pytest -q
```

## Docker (optional)
```bash
docker build -t tinynotes .
docker run -p 8080:8080 tinynotes
```

## Serverless (optional)
I kept a minimal SAM template and Lambda adapter so I can deploy this behind API Gateway later:
```bash
sam validate && sam build
sam deploy --guided
```

## Notes
This keeps everything in memory to stay simple. If I want persistence and real cloud limits later, I can swap in DynamoDB and API Gateway usage plans.
