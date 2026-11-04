# Supplier Document Checker

Checks supplier quotation PDFs against a purchase request and company rules. Each quote
receives an **Approve**, **Reject**, or **Needs a person to check** decision, with reasons
and source evidence.

The model extracts fields; Python code validates them, compares prices and quantities,
applies rules, and decides. Unclear or unverifiable information goes to a person. The
project uses fictional sample data only.

## Project structure and stack

- **Backend:** Python 3.12 managed with uv, Pydantic v2, LangGraph, pdfplumber with pypdf
  fallback, OpenAI SDK configured for an OpenRouter-compatible endpoint, FastAPI, and Uvicorn.
- **Frontend:** React, TypeScript, and Vite; Vitest for frontend tests.
- **Quality:** pytest, Ruff, and mypy.
- **Key files:** backend/rules/company_rules.yaml holds thresholds; contracts/openapi.json
  drives generated frontend API types; ground_truth.csv contains expected evaluation results.
- **Code layout:** backend/src/checker contains the pipeline and CLI; backend/src/api contains
  the job API; backend/tests uses synthetic documents and canned model responses.

## Get started

Requirements: Python 3.12, uv, Node.js 20+, and npm. The dev.sh launcher requires Bash
(Git Bash or WSL on Windows).

From the repository root, install dependencies:

    cd backend && uv sync
    cd ../frontend && npm install
    cd ..

Copy backend/.env.example to backend/.env and set OPENROUTER_MODEL and OPENROUTER_API_KEY
for document extraction. The default endpoint is https://openrouter.ai/api/v1.

    cp backend/.env.example backend/.env

Keep real API keys in backend environment variables or the local backend .env. Frontend
variables are public and must not contain secrets.

### Start both services

From the repository root:

    bash ./dev.sh

Open http://localhost:5173. The API runs at http://127.0.0.1:8000. Press Ctrl+C to stop
both services. Set API_PORT or FRONTEND_PORT to change ports.

The app accepts a purchase request CSV or JSON and supplier quote PDFs. It creates a job,
shows backend-reported progress, then displays one expandable result per document. The
default upload limit is 20 PDFs and can be changed with MAX_PDFS.

## Run the CLI

Place the purchase request at backend/data/purchase-request.csv and PDFs in the same
directory. Sample files are not included in the repository. From backend/, run:

    uv run python -m checker.cli

The CLI processes top-level PDFs in filename order and prints each decision and its reasons.
To use another directory, purchase request, or rules file:

    uv run python -m checker.cli --data-dir path/to/documents \
      --purchase-request path/to/purchase-request.csv \
      --rules rules/company_rules.yaml

By default, the purchase request is <data-dir>/purchase-request.csv. The CLI calls the
configured extraction model. Exit code 0 means every document produced a result; 2 means the
inputs or configuration were unusable. Run uv run python -m checker.cli --help for options.

## API and frontend

The API uses the same graph as the CLI. Main endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | /health | Health check |
| POST | /jobs | Upload a purchase request and quote PDFs |
| GET | /jobs/{id} | Poll job and document stage progress |
| GET | /jobs/{id}/results | Retrieve results after completion |

Jobs process documents sequentially. Uploaded files are temporary, job state is held in
memory until expiry, and one document failure does not stop the others. Run a single backend
worker.

From frontend/, use these commands:

    npm run dev
    npm run typecheck
    npm run lint
    npm run test
    npm run build

Frontend API types are generated from contracts/openapi.json. Do not edit
frontend/src/api/schema.d.ts by hand. After changing the API schema, export it from backend/
with uv run python -m api.contract, then run npm run generate:api from frontend/.

## Tests and evaluation

From backend/:

    uv run pytest
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run python evals/run_eval.py

Evaluation compares local sample packs with the root ground_truth.csv and reports decision
accuracy, rule ID differences, and mismatches. It needs local sample files and working
OpenRouter settings. Never edit ground truth or commit sample files.

See backend/.env.example for environment variable names. Local .env files, sample data,
caches, and temporary files are excluded by .gitignore.
