# Supplier Document Checker

Checks fictional supplier quotations against a purchase request and a fixed set of company
rules. Every document gets one decision: **Approve**, **Reject**, or **Needs a person to
check**, with the rule IDs and quoted evidence behind it.

The model reads; code decides. The LLM only extracts fields. Matching, comparisons,
thresholds, arithmetic and the final decision are deterministic Python.

Built for BIAI AI Engineer Round 2, Task 1. All data is fictional.

## Layout

```
backend/          Python backend: pipeline, rules, evaluation harness, API
  src/checker/    schemas, normalization, checks, decisions, graph, CLI
  src/api/        FastAPI job flow, thin over the graph
  tests/          unit and integration tests (synthetic fixtures, no live model)
  evals/          evaluation harness against ground_truth.csv
  rules/          company_rules.yaml, the only place thresholds live
  data/           sample files, git-ignored, placed locally
contracts/        openapi.json, the contract the frontend generates types from
ground_truth.csv  hand-checked expectations per pack
frontend/         React + Vite + TypeScript app
```

Everything under `backend/` is Python and runs from that directory. Files at the root are
shared: the API contract, the ground truth, and the documentation.

## What the project does

The checker accepts a purchase request and supplier quote PDFs, extracts quote fields, and
compares them with the request and company rules. It returns one result per quote with a
decision, rule checks, reasons, flags for uncertain fields, and the source snippets that
support its findings.

The processing pipeline is a fixed LangGraph flow, run once per document. The model is used
only to extract fields from PDF text. Pydantic validates the extracted structure and source
snippets; Python code normalizes values, matches purchase request lines, performs all
comparisons and arithmetic, evaluates every configured rule, and decides the outcome. The
model never sets thresholds or makes the final decision. A missing, ambiguous, invalid, or
unverifiable value is routed to **Needs a person to check** instead of being guessed.

The frontend provides one upload, processing, and results flow. The API runs documents
sequentially within a job, reports progress from the graph stages, and keeps job state in
memory until expiry. The repository includes a CLI for local runs, an evaluation harness,
synthetic tests, and the OpenAPI contract used to generate frontend API types.

## Tech stack

- **Backend:** Python 3.12, managed with `uv`; Pydantic v2 schemas; LangGraph orchestration;
  `pdfplumber` with `pypdf` fallback for PDF text; OpenAI Python SDK configured for an
  OpenRouter-compatible endpoint; FastAPI, `python-multipart`, and Uvicorn for the API.
- **Frontend:** React, TypeScript, and Vite. API types are generated from
  `contracts/openapi.json` with `openapi-typescript`; Vitest covers frontend logic.
- **Quality and evaluation:** `pytest` for backend tests, `ruff` for linting and formatting,
  `mypy` for type checking, and `ground_truth.csv` for decision evaluation.

Tests use synthetic documents and canned model responses. They do not call a live model.

## Pipeline

One graph run per document: load and extract text, parse fields with the LLM, normalize and
verify every snippet, match the purchase request line, run every rule check, then decide.
There is one conditional edge: an unreadable PDF or failed/invalid extraction produces a
terminal **Needs a person to check** result with a reason. Uncertain individual fields do
not branch there; the checks return needs-person and precedence (reject over needs-person
over approve) settles the outcome. Multi-line quotes, unmatched purchase request lines and
other cases outside the numbered rules produce an `EDGE-*` reason with no rule ID.

## Rules and ground truth

- `backend/rules/company_rules.yaml` is the only place thresholds live. Check functions read
  them from there; none are hard-coded.
- `ground_truth.csv` at the repository root is the hand-checked expected decision and
  triggered rule IDs per pack. It is never edited to make a score pass.

Rule IDs follow the company rules document: `REJ-01`..`REJ-05` for reject rules and
`NP-01`..`NP-07` for needs-person rules. Anything the numbered rules do not cover (for
example a quote with more than one line item, an unreadable PDF, or no matching purchase
request line) is an edge case and routes to a person with an `EDGE-*` code and no rule ID.

## Requirements

- Python 3.12 via [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm for the frontend
- Bash to use `dev.sh` (Git Bash or WSL on Windows)

## Setup

From the repository root, install the backend and frontend dependencies:

```bash
cd backend && uv sync
cd ../frontend && npm install
cd ..
```

Copy `backend/.env.example` to `backend/.env` and set `OPENROUTER_MODEL` and
`OPENROUTER_API_KEY` before running the CLI or submitting a job that needs extraction. The
default base URL is `https://openrouter.ai/api/v1`. Keep real keys in the local `.env` or
environment; never put them in frontend variables. The backend also reads its environment
file when the CLI or evaluation harness starts. Real environment variables take precedence,
and a missing `.env` is allowed. `ENV_FILE` selects a different environment file when needed.

For example, in Bash:

```bash
cp backend/.env.example backend/.env
```

Tests set `ENV_FILE` to a nonexistent path so a developer's local `.env` does not affect
test runs. You can run them without live model credentials.

`LLM_REASONING_EFFORT` is optional and is sent to the endpoint as `reasoning.effort`. Set it
to `none` for a reasoning model so a call fits inside `LLM_TIMEOUT_SECONDS`; leave it empty
for an endpoint that does not accept the field.

## Run the app locally

After installing dependencies, start both local services together from the repository root:

```bash
bash ./dev.sh
```

`dev.sh` starts the FastAPI backend and Vite frontend in parallel. Open
`http://localhost:5173`; the API runs at `http://127.0.0.1:8000` by default. The script uses
the installed `backend/.venv` and `frontend/node_modules`, exits if a healthy API already
responds on the selected API port, and stops both services when you press Ctrl+C. It is a
Bash script, so on Windows run it from Git Bash or WSL. Set `API_HOST`, `API_PORT`,
`FRONTEND_HOST`, or `FRONTEND_PORT` to change the bind addresses and ports.
`VITE_API_BASE_URL` can override the API URL passed to Vite.

For a first run, complete the setup above and configure the backend model credentials. You
can also run either service on its own while developing:

```bash
cd backend && uv run uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal, run the frontend from the repository root:

```bash
cd frontend && npm run dev -- --host localhost --port 5173
```

The frontend's optional `frontend/.env` can set `VITE_API_BASE_URL`; copy
`frontend/.env.example` to create it. This is a public build-time URL, never a place for
secrets. The default points to the local backend.

The page accepts one purchase request CSV or JSON file and up to the configured number of
supplier PDFs (20 by default). It creates a job, polls for real backend stage progress, and
shows one expandable result card per document after the job completes. A processing failure
is shown as needing a person, not as an automatic rejection.

## CLI

The CLI runs the same extraction, comparison, rules, and decision pipeline without the web
API or ground-truth scoring. It finds every top-level `*.pdf` in a directory, processes them
in filename order, and prints each decision with its reasons. Put the purchase request CSV
in that directory as `purchase-request.csv`, or pass its path explicitly.

Place local sample or synthetic input files under `backend/data/` (see
[Sample files](#sample-files-not-in-this-repo)), then from `backend/` run:

```bash
uv run python -m checker.cli
```

To use another input directory or specify the purchase request and rules files:

```bash
uv run python -m checker.cli --data-dir path/to/documents \
  --purchase-request path/to/purchase-request.csv \
  --rules rules/company_rules.yaml
```

Options `--purchase-request` and `--rules` are optional. By default, the purchase request is
`<data-dir>/purchase-request.csv`, and the rules are `backend/rules/company_rules.yaml`.
The CLI needs working OpenRouter settings because it calls the configured extraction model.
It returns exit code `0` when every document produced a result, even if some decisions are
Reject or Needs a person; it returns `2` when the input files or setup are unusable. Run
`uv run python -m checker.cli --help` for the available options.

For scored evaluation against the hand-written expected outcomes, use the separate
`evals/run_eval.py` command described in [Evaluation](#evaluation).

## Frontend development

The app lives in `frontend/` and is a static Vite build. It needs Node.js 20+.

Checks, from `frontend/`:

```bash
npm run typecheck
npm run lint
npm run test
npm run build
```

`src/api/schema.d.ts` is generated from `contracts/openapi.json`; never edit it by hand.
After a contract change, re-export the contract from `backend/`, then run
`npm run generate:api`.

Problems found while building this, with causes and fixes, are recorded in `ISSUES.md`.

## API

The API wraps the same per-document graph. Job state is held in memory, so run exactly one
worker process, from `backend/`:

```bash
.venv/Scripts/python.exe -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
```

`--factory` is required: `create_app()` builds the app, which is how tests inject settings
and a canned model completer.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness check; also what the host polls |
| `POST` | `/jobs` | Multipart: one `purchase_request` CSV or JSON plus one or more `supplier_quotes` PDFs |
| `GET` | `/jobs/{id}` | Polling payload: overall state, counts, per-document stage statuses |
| `GET` | `/jobs/{id}/results` | One decision per document; `409` until the job completes |

`POST /jobs` returns `201` immediately and processing continues in a background thread.
Documents are checked one at a time. Each graph node reports when a stage starts and
finishes, so the stage statuses are the real ones rather than a timer.

JSON purchase requests use an object with `pr_number` and a `lines` array. Each line has
`item_code`, `description`, `unit`, `quantity_requested`, and `max_unit_price`; numeric values
may be JSON numbers or decimal strings. For example:

```json
{
  "pr_number": "PR-0000-001",
  "lines": [
    {
      "item_code": "A",
      "description": "Blue denim roll, 12 oz",
      "unit": "piece",
      "quantity_requested": 100,
      "max_unit_price": "10.00"
    }
  ]
}
```

Every error is `{"error": {"code": "...", "message": "..."}}`: `404` for an unknown or
expired job, `409` before results exist, `429` when the server is busy or a client creates
jobs too quickly, `413` for oversized files, and `400` for uploads that fail content validation.
Uploads are streamed to a per-job temporary directory under
server-generated names, hashed to reject duplicates, and deleted when the job ends. A
document that fails becomes a needs-person result with a processing-failure flag; the other
documents still finish.

Upload filenames and MIME labels do not determine document type. The backend recognizes
quotation PDFs from their PDF signature and identifies the purchase request as CSV or JSON
from its contents. The original filenames are retained only for display in job status and
results.

Configuration comes from the environment: `MAX_PDFS`, `MAX_FILE_MB`, `MAX_CONCURRENT_JOBS`,
`JOB_TTL_SECONDS`, `JOB_TIMEOUT_SECONDS`, `RATE_LIMIT_JOBS`, `RATE_LIMIT_WINDOW_SECONDS`,
`TEMP_DIR_BASE` and `ALLOWED_ORIGINS`. See `.env.example`. Locally these are read from
`.env`; the host injects real variables.

## API contract

`contracts/openapi.json` at the repository root is exported from the app and committed. The
frontend generates its types from it, so export it again after any change to the API or its
models (from `backend/`):

```bash
.venv/Scripts/python.exe -m api.contract
```

The command writes to `../contracts/openapi.json`. `tests/test_api_contract.py` fails when
the committed file drifts from the app.

## Checks

From `backend/`:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

On machines where an application-control policy blocks the console scripts (`pytest.exe`,
`mypy.exe`), run them through the interpreter instead:

```bash
uv run python -m pytest
uv run python -m mypy
```

## Evaluation

`evals/run_eval.py` sends every pack in `backend/data/` through the real graph, once each and
sequentially, and compares each decision and set of triggered rule IDs with the root
`ground_truth.csv`:

```bash
.venv/Scripts/python.exe evals/run_eval.py      # or: uv run python evals/run_eval.py
```

The headline is decision accuracy, followed by a per-pack table and every mismatch with
its reasons. Exit codes: `0` all packs match, `1` at least one differs, `2` the evaluation
cannot run (missing data, inconsistent ground truth, missing LLM settings). The harness
needs `OPENROUTER_*` settings and never edits ground truth. Rule IDs are compared as sets;
the reject-first ordering is covered by unit tests.

## Running documents without ground truth

`python -m checker.cli` is the auxiliary runner: same graph, no scoring. It runs every PDF
in a directory and prints the decision and reasons for each one, which is useful while
developing or for documents that have no expected answer.

```bash
.venv/Scripts/python.exe -m checker.cli
.venv/Scripts/python.exe -m checker.cli --data-dir some/folder
```

Defaults are `backend/data` and its `purchase-request.csv`; `--rules` overrides the rules
file. Exit codes: `0` when every document was processed (whatever it decided), `2` when the
inputs or configuration are unusable.

## Decision boundaries

Strict inequalities follow the rules document: exactly 3% over the maximum price, exactly
20% advance, exactly 45 days, exactly 5% quantity gap and exactly 30 days validity do not
trigger their rules. Money and percentages use `Decimal`; arithmetic tolerance is 0.01 BDT,
set in the rules file.

## Evidence and quotes

Every extracted field carries the text it came from, and a rule that depends on a field the
document does not clearly state sends the document to a person. The model is asked to copy
the source line verbatim; when it instead rebuilds the line (for example `Supplier BIN: ...`
for a line printed as `Supplier TIN: ... BIN: ...`), the quote is checked against the
document and, if the value appears verbatim on exactly one printed line, that line becomes
the evidence. A value that appears nowhere, or on several lines, is never guessed: the field
stays unverified and the document is routed to a person.