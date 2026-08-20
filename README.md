# Obliq.io Compliance Agent Prototype

Obliq.io is a prototype compliance operations console for accounting and compliance teams. A user enters a client ID, the backend checks local compliance data, an LLM coordinates the checks, and the frontend displays the result as an explainable audit trace.

This is a demonstration prototype, not a production compliance platform. It uses a local JSON file instead of a database and drafts reminders without sending real email.

## What the Prototype Does

For a selected client, the system:

1. Receives a client ID from the frontend.
2. Checks which required documents are missing.
3. Checks upcoming and overdue deadlines.
4. Allows the agent to draft a reminder when action is needed.
5. Returns the tool calls, verification status, and final message.
6. Displays the result in the frontend as a simulated email.

The frontend also has a bulk overview action that lists clients with missing documents or deadline activity in the configured time window.

## High-Level Architecture

The project has two applications:

- **Backend:** Python and FastAPI, running on port `8000`.
- **Frontend:** Next.js, React, TypeScript, and Tailwind CSS, running on port `3000`.

```text
                         +----------------------+
                         |  Next.js Frontend    |
                         |  localhost:3000      |
                         +----------+-----------+
                                    |
                         HTTP JSON requests
                                    |
                         +----------v-----------+
                         |  FastAPI Backend     |
                         |  localhost:8000      |
                         +----------+-----------+
                                    |
                +-------------------+-------------------+
                |                                       |
       +--------v---------+                    +--------v---------+
       | Agent Orchestrator|                    | Compliance Tools  |
       | agent.py          |                    | tools.py          |
       +--------+----------+                    +--------+----------+
                |                                        |
                | Gemini API                              | cached reads
                |                                        |
       +--------v---------+                    +--------v----------+
       | Google Gemini     |                    | data.json          |
       | tool calling      |                    | mock data store    |
       +------------------+                    +--------------------+
```

The backend is stateless per request. The conversation and tool results exist only while one request is running. The data cache is an in-process optimization; it is not a persistent database.

## Request Flow

### 1. User starts an audit

The user enters a client ID, such as `101`, and clicks **Initialize agent**.

The frontend sends:

```http
POST http://localhost:8000/api/v1/compliance/check
Content-Type: application/json
```

```json
{
  "client_id": "101"
}
```

At the same time, the frontend shows clearly labeled synthetic status lines. These lines are visual feedback, not private model chain-of-thought.

### 2. FastAPI receives the request

`main.py` validates the request using Pydantic. It calls `run_compliance_agent()` from `agent.py` and measures the request duration.

The route returns a structured success response:

```json
{
  "status": "success",
  "took_ms": 1200,
  "data": {}
}
```

If the client does not exist, the backend returns HTTP `404`. Unexpected server failures return HTTP `500`.

### 3. The agent asks Gemini to use tools

`agent.py` sends the user request to Gemini using the Google Generative Language HTTP API. It provides function declarations generated from `TOOL_SCHEMAS` in `tools.py`.

The agent is instructed to:

- use only facts returned by local tools
- call both document and deadline checks before deciding about a reminder
- avoid inventing dates, client details, or document names
- return a final JSON object with `summary`, `actions`, and `final_status`

### 4. Tools query local data

The available tools are:

- `get_missing_docs(client_id)`
- `get_upcoming_deadlines(client_id, within_days=30)`
- `trigger_reminder(...)`
- `get_compliance_overview(within_days=30)` for the overview route

`tools.py` loads and validates `data.json` with Pydantic models. Normal requests reuse an in-memory database cache so every tool call does not reread the file from disk. Use `load_data(force_reload=True)` when a deliberate reload is needed.

### 5. Tool results return to the agent

Each tool result is added to the execution log. The agent can then request another tool or provide its final response.

The reminder guardrail requires both of these checks to have run first:

```text
get_missing_docs
get_upcoming_deadlines
        |
        v
trigger_reminder, only when action is required
```

### 6. The frontend renders the result

When the backend responds, the frontend:

1. Stops the synthetic trace timers.
2. Appends the actual tool names returned by the backend.
3. Shows the final status and message.
4. Displays the message inside a mock dark email client.
5. Shows a local **Approve & Dispatch Reminder** action.

The dispatch button only changes frontend state and displays `Message sent to client`. It does not call an SMTP service or backend endpoint.

## Repository Structure

```text
Obliq/
├── agent.py                 # Gemini orchestration and tool-calling loop
├── data.json                # Local mock clients, documents, and deadlines
├── main.py                 # FastAPI app and HTTP routes
├── requirements.txt         # Python dependencies
├── tools.py                 # Validated compliance tools and data cache
├── Genarateata.py           # Utility for regenerating mock data
├── docs/                    # Internal project documentation
├── Frontend/
│   ├── package.json         # Frontend scripts and dependencies
│   └── src/app/
│       ├── layout.tsx       # Root Next.js layout
│       └── page.tsx         # Main dashboard and audit workflow
└── .gitignore               # Project-wide ignored files
```

Only the root `README.md` is intentionally included in Git. Other Markdown files remain ignored by the root `.gitignore`.

## Requirements

Install the following before running the project:

- Python 3.11 or newer recommended
- Node.js 20 or newer recommended
- npm
- A Gemini API key for the live audit endpoint

## Backend Setup

From the project root in PowerShell:

```powershell
cd "C:\Users\Gulab Jangid\Desktop\Obliq"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a local `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.6-flash
```

The `.env` file is ignored by Git and must never be committed.

Start the backend:

```powershell
uvicorn main:app --reload --port 8000
```

Useful backend URLs:

- Health check: `http://localhost:8000/health`
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Frontend Setup

Open a second terminal:

```powershell
cd "C:\Users\Gulab Jangid\Desktop\Obliq\Frontend"
npm install
npm run dev
```

Open `http://localhost:3000` in a browser.

The frontend defaults to the backend at `http://localhost:8000`. To use another backend URL, create `Frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Because this variable starts with `NEXT_PUBLIC_`, it is exposed to browser code. It must contain a public URL only, never a secret.

## API Reference

### Health

```http
GET /health
```

Example response:

```json
{
  "status": "ok"
}
```

### Run a compliance check

```http
POST /api/v1/compliance/check
```

Request:

```json
{
  "client_id": "101"
}
```

The response includes:

- `status`: HTTP workflow status
- `took_ms`: elapsed backend time
- `data.client_id`: checked client
- `data.verification.documents_checked`: whether the document tool ran
- `data.verification.deadlines_checked`: whether the deadline tool ran
- `data.execution_log`: tool calls and their results
- `data.agent_result`: the final model response

PowerShell example:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/v1/compliance/check" `
  -ContentType "application/json" `
  -Body '{"client_id":"101"}'
```

### Compliance overview

```http
GET /api/v1/compliance/overview
```

This returns clients with missing documents, upcoming deadlines, or overdue deadlines.

PowerShell example:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/compliance/overview"
```

### Invalid client behavior

A client ID that does not exist returns HTTP `404` instead of an unhelpful HTTP `500`:

```json
{
  "detail": "'Client 999 not found'"
}
```

## Data Model

`data.json` contains three top-level collections:

### Clients

Each client has an ID, contact details, and a list of required documents.

### Documents

Each document belongs to a client and has a status such as:

- `uploaded`
- `missing`
- `pending`

A required document is treated as missing when it is not uploaded. Explicitly missing records are also reported.

### Deadlines

Each deadline belongs to a client and contains an event name and ISO date. Deadlines before today are overdue. Future deadlines within the selected window are upcoming.

## Error Handling

The backend uses several protection layers:

- Pydantic validates incoming request and tool arguments.
- Unknown tools return an error result to the agent.
- Tool failures are returned as structured error text to the agent.
- Reminder execution is blocked until both required checks run.
- Missing clients are mapped to HTTP `404` by `main.py`.
- Markdown code fences around model JSON are removed before JSON parsing.
- The frontend handles network errors, invalid payloads, cancellation, and empty client IDs.

## Testing and Validation

Check backend syntax:

```powershell
cd "C:\Users\Gulab Jangid\Desktop\Obliq"
python -m py_compile agent.py main.py tools.py
```

Check the cached data loader and tool behavior:

```powershell
python -c "import asyncio; import tools; first = asyncio.run(tools.load_data(force_reload=True)); second = asyncio.run(tools.load_data()); assert first is second; print('cache check passed')"
```

Check the frontend production build:

```powershell
cd "C:\Users\Gulab Jangid\Desktop\Obliq\Frontend"
npm run build
```

Run frontend linting:

```powershell
npm run lint
```

For a manual end-to-end check:

1. Start the backend on port `8000`.
2. Start the frontend on port `3000`.
3. Enter a known client ID such as `101`.
4. Confirm the trace appears and the outcome panel renders.
5. Click **Approve & Dispatch Reminder** and confirm the local success alert.
6. Try an unknown client ID such as `999` and confirm the frontend reports the `404` response.

## Regenerating Mock Data

`Genarateata.py` can create a new randomized dataset:

```powershell
cd "C:\Users\Gulab Jangid\Desktop\Obliq"
python Genarateata.py
```

This overwrites `data.json`. Restart the backend or call `load_data(force_reload=True)` after changing the file so the in-memory cache is refreshed.
 simple: the agent may coordinate actions, but factual compliance information must come from the validated local tools.
