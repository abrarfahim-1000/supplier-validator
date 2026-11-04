# Build note: Supplier Document Checker

## What I built

I used generative AI tools first to plan the approach, select a stack that fit the requirements, and break the work into ordered steps: deterministic checks and schemas, extraction and evaluation, API, then frontend. I used AI during implementation to iterate on the backend and to shape the frontend design, including its upload, processing, and evidence-focused results screens. I reviewed and refined the outputs against the project constraints, especially that code makes decisions and uncertain cases go to a person. The result is a single-page supplier document checker backed by a fixed LangGraph pipeline, with a React frontend for upload, progress, and evidence-backed decisions.

## How I tested it and results

I used AI-generated automated tests with synthetic documents and canned model responses. The latest recorded backend run had 173 passing tests; evaluation against the ten local sample packs matched both expected decisions and triggered rule IDs (10/10 each). Frontend lint and production build passed. Manually, I checked file selection, replacement, and removal, and reviewed the upload and results screens in light and dark mode. A browser validation run displayed job progress and results, but it connected to a canned API server, so it did not verify the full flow against the real backend. The latest frontend test run had two workflow failures, and the API upload integration test stalled in the test environment.

## Problems faced during development

The free extraction model was much slower than expected: the HTTP timeout did not impose a true wall-clock limit, SDK and application retries compounded, and the selected model spent minutes reasoning before returning fields. I added a hard deadline, kept retries in one layer, and made reasoning effort configurable. Extraction also shortened evidence lines and varied item-code formatting; clearer prompt examples, verified evidence-line recovery, and more robust exact matching addressed these cases. A missing expected rule in the hand-written ground truth was corrected by its owner rather than by changing the checker.

Some validation work remains incomplete: two frontend workflow tests fail, and the latest API upload integration run stalled. An earlier browser run used a canned server, so the browser flow still needs verification against the real backend. The free endpoint can still be slow or nondeterministic; jobs are lost on restart, and the rate limiter sees the hosting proxy rather than individual clients. The app has not been deployed.

## What I would do next

I would extend the checker to handle quotations with multiple line items, matching and evaluating each line against the purchase request while keeping an overall decision for the supplier. I would also add a downloadable audit report with the extracted values, line-by-line comparisons, rule outcomes, and source evidence, so procurement staff can share and retain the review. A later expansion could support comparing several supplier quotes side by side for the same purchase request.
