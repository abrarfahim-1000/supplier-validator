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

## Status

Steps 1 to 4 are implemented: schemas, rules-as-data, normalization, deterministic checks
and decision precedence; PDF text extraction, LLM field extraction with schema validation
and bounded retries; the fixed, linear LangGraph pipeline; the evaluation harness that
scores against `ground_truth.csv`; and the hosted API job flow with its exported OpenAPI
contract. All of it is covered by tests that use synthetic PDFs and canned model output, so
no live model is called. The frontend covers the whole journey: upload, job polling with
real progress, and a results dashboard with one collapsible card per supplier document.
Deployment is the remaining step (see `AGENTS.md`).

The current handoff notes in `HANDOFF.md` describe the state at the end of step 4 and what
the frontend codes against.

## Pipeline

One graph run per document: load and extract text, parse fields with the LLM, normalize and
verify every snippet, match the purchase request line, run every rule check, then decide.
There is one conditional edge: an unreadable PDF or failed/invalid extraction produces a
terminal **Needs a person to check** result with a reason. Uncertain individual fields do
not branch there; the checks return needs-person and precedence (reject over needs-person
over approve) settles the outcome. Multi-line quotes, unmatched purchase request lines and
other cases outside the numbered rules produce an `EDGE-*` reason with no rule ID.

## Sample files (not in this repo)

The sample files are never committed. Copy them into `backend/data/` locally:

```
backend/data/purchase-request.csv
backend/data/supplier-pack-01.pdf ... supplier-pack-10.pdf
```

`data/` is git-ignored.

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
- Node 20+ for the frontend

## Setup

Everything below runs from `backend/`:

```bash
cd backend
uv sync
```

Copy `backend/.env.example` to `backend/.env` and fill in the LLM settings when you run
extraction. The deterministic tests never call a live model.

The backend and the evaluation harness load `.env` themselves on startup, so nothing needs
to be exported first. Real environment variables always win over the file, a missing `.env`
is not an error (the hosted deployment has none), and `ENV_FILE` points the loader at a
different file when needed. Tests set `ENV_FILE` to a nonexistent path so a developer's
`.env` never leaks into a test run.

`LLM_REASONING_EFFORT` is optional and is sent to the endpoint as `reasoning.effort`. Set it
to `none` for a reasoning model so a call fits inside `LLM_TIMEOUT_SECONDS`; leave it empty
for an endpoint that does not accept the field.

## Frontend

The app lives in `frontend/` and is a static Vite build. It needs Node 20+.

To run the local API and frontend together from the repository root, use Bash:

```bash
bash ./dev.sh
```

This uses the existing backend virtual environment and frontend dependencies, starts the API
at `http://127.0.0.1:8000` (or reuses a healthy API already there) and serves the frontend at
`http://localhost:5173`, the backend's configured CORS origin. Ctrl+C stops processes the
script started. Set `API_PORT` or
`FRONTEND_PORT` to change the ports. For a first-time setup, run `uv sync` from `backend/`
and `npm install` from `frontend/` first.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Copy `frontend/.env.example` to `frontend/.env` to point `VITE_API_BASE_URL` at the API. The
local default is `http://127.0.0.1:8000`. The variable is
public and set at build time; the frontend holds no secrets.

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

The page accepts one purchase request CSV or JSON file and up to twenty supplier quotation PDFs, with a
progress ring per selected file. `Run validation` creates a real job and polls its status,
showing real document progress and a spinner until the backend reports the job finished. The
results then render below the upload section, which is scrolled into view: decision counts,
and one collapsible card per document with its extracted fields, purchase request comparison,
every rule check, the supporting snippets and the final decision. A document that failed
processing is shown as needing a person with its failure reason, never as rejected.

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

## Env example

See `backend/.env.example`. Backend secrets stay in the backend environment; the frontend
only gets the public API base URL.
