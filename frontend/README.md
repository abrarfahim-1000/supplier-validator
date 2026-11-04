# Frontend

React + Vite + TypeScript single-page app for the Supplier Document Checker. It collects one
purchase request CSV or JSON and up to twenty supplier quotation PDFs, follows the backend job, and shows
one decision per document.

All decisions, comparisons, rule checks and extracted values come from the backend. The app
never evaluates a rule itself and never fabricates a value.

## Commands

Run from `frontend/`:

```bash
npm install
npm run dev        # http://localhost:5173, expects the API on http://127.0.0.1:8000
npm run test       # vitest
npm run typecheck  # strict tsc, no emit
npm run lint       # eslint
npm run build      # typecheck, then a production build into dist/
```

Start the backend first, from `backend/`:

```bash
.venv/Scripts/python.exe -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8000
```

## Configuration

`VITE_API_BASE_URL` is the only variable. It is public and set at build time. Copy
`.env.example` to `.env` locally, or set the variable in the hosting project. No secrets ever
belong in the frontend environment.

## API types

`src/api/schema.d.ts` is generated from `contracts/openapi.json`. Do not edit it by hand.
After any backend contract change, re-export the contract from `backend/`, then regenerate:

```bash
cd backend
.venv/Scripts/python.exe -m api.contract

cd ../frontend
npm run generate:api
```

## Structure

```
src/
  api/          generated OpenAPI types and the typed fetch client
  components/   upload, processing, and expandable result views
  ui/           file validation helpers, labels, and result formatting
  workflow/     backend health, job polling, progress stages, and upload limits
  App.tsx       page shell and service status
  styles.css    design tokens, layout, and responsive states
```

The app uses plain CSS and a small set of Tabler icons. There is no UI or state library.

## Current state

Upload, processing, and results are implemented on one page. The page collects one purchase
request CSV or JSON and up to twenty supplier PDFs, then `Run validation` creates a real backend job and
polls it about once per second. Progress reflects completed documents and the five statuses
reported for each document. Results are fetched only after the job reports completed:

- decision counts for approved, rejected and needs-a-person documents;
- one collapsible card per document (supplier, quotation number, decision, one-line reason);
- expanded: extracted fields, purchase request comparison, every rule check, supporting
  snippets grouped by source with the rules that cite them, and the final decision.

Nothing is simulated: every value comes from `GET /jobs/{id}/results`. Missing or ambiguous
fields show as flagged instead of being filled in, and a document that failed processing is
shown as needing a person with the backend's failure reason. Transient status or result-fetch
network failures keep the same job id and retry with backoff; expired or unknown jobs return
to upload with the backend message and the selected files intact.
