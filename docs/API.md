# Claw-STU HTTP API Reference

Base URL: `http://localhost:8000`

Start the server: `clawstu serve`

---

## Health

### GET /health

Health check alias. Returns system status.

**Response (200):**

| Field            | Type           | Description                     |
|------------------|----------------|---------------------------------|
| status           | string         | `"ok"` or `"degraded"`          |
| version          | string         | Package version                 |
| invariants       | object         | System invariant checks         |
| active_sessions  | int            | Number of cached sessions       |

---

## Sessions

### POST /sessions

Create a new learning session (onboard a learner).

**Request:**

| Field      | Type   | Required | Description                                    |
|------------|--------|----------|------------------------------------------------|
| learner_id | string | yes      | Learner name or ID (1-128 chars)               |
| age        | int    | yes      | Learner age (5-120)                            |
| domain     | string | yes      | Subject domain (see Domain enum below)         |
| topic      | string | no       | Free-text topic (max 200 chars)                |

**Domain enum:** `us_history`, `global_history`, `civics`, `ela`, `science`, `math`, `other`

**Response (201):**

| Field             | Type   | Description                        |
|-------------------|--------|------------------------------------|
| session_id        | string | UUID of the new session            |
| phase             | string | Current session phase              |
| calibration_items | array  | Assessment items for calibration   |

---

### GET /sessions/{session_id}

Fetch current session state.

**Response (200):** Full `Session` model.

---

### POST /sessions/{session_id}/calibration-answer

Submit an answer to a calibration question.

**Request:**

| Field           | Type   | Required | Description                      |
|-----------------|--------|----------|----------------------------------|
| item_id         | string | yes      | Assessment item ID               |
| response        | string | yes      | Student's answer text            |
| latency_seconds | float  | no       | Time taken to answer             |

**Response (200):**

| Field     | Type    | Description                            |
|-----------|---------|----------------------------------------|
| correct   | bool    | Whether the answer was correct         |
| score     | float   | Numeric score (0.0-1.0)               |
| phase     | string  | Current session phase                  |
| crisis    | bool    | Crisis detection flag                  |
| resources | string  | Crisis resources (if crisis=true)      |

---

### POST /sessions/{session_id}/finish-calibration

Transition from calibration to teaching phase.

**Response (200):**

| Field     | Type   | Description                              |
|-----------|--------|------------------------------------------|
| directive | object | Next teaching directive                  |
| session   | object | Updated session state                    |

---

### POST /sessions/{session_id}/next

Request the next teaching or checking directive.

**Response (200):**

| Field     | Type   | Description                              |
|-----------|--------|------------------------------------------|
| directive | object | Next directive (block, check, or close)  |
| session   | object | Updated session state                    |

---

### POST /sessions/{session_id}/check-answer

Submit an answer to a check-for-understanding question.

**Request:**

| Field           | Type   | Required | Description                      |
|-----------------|--------|----------|----------------------------------|
| item_id         | string | yes      | Assessment item ID               |
| response        | string | yes      | Student's answer text            |
| latency_seconds | float  | no       | Time taken to answer             |

**Response (200):** Same shape as `/next` (directive + session).

---

### POST /sessions/{session_id}/socratic

Ad-hoc student question within a session.

**Request:**

| Field         | Type   | Required | Description                       |
|---------------|--------|----------|-----------------------------------|
| student_input | string | yes      | Question text (1-2000 chars)      |

**Response (200):**

| Field     | Type   | Description                              |
|-----------|--------|------------------------------------------|
| response  | string | Socratic response text                   |
| phase     | string | Current session phase                    |
| crisis    | bool   | Crisis detection flag                    |
| resources | string | Crisis resources (if crisis=true)        |

---

### POST /sessions/{session_id}/close

Close the session and receive a summary.

**Response (200):**

| Field   | Type   | Description           |
|---------|--------|-----------------------|
| summary | string | Session summary text  |

---

## Quick Ask

### POST /api/ask

One-shot Socratic Q&A -- no session required. Used by the Chrome extension.

**Request:**

| Field    | Type   | Required | Description                         |
|----------|--------|----------|-------------------------------------|
| question | string | yes      | Question text (1-2000 chars)        |

**Response (200):**

| Field    | Type   | Description                              |
|----------|--------|------------------------------------------|
| response | string | Socratic response text                   |
| crisis   | bool   | Crisis detection flag                    |

---

## Profile

### GET /profile/{session_id}

Fetch the learner profile for a session.

**Response (200):** Full `LearnerProfile` model.

---

### GET /profile/{session_id}/export

Download the learner profile as JSON.

**Response (200):** JSON file attachment.

---

### DELETE /profile/{session_id}

Delete all data for a session.

**Response (204):** No content.

---

## Learners

### GET /learners/{learner_id}/wiki/{concept}

Render a per-student concept wiki as markdown.

**Response (200):** `text/markdown` content.

Requires `X-Learner-Id` header matching the learner.

---

### POST /learners/{learner_id}/resume

Warm-start from a pre-generated session artifact.

**Response (200):**

| Field      | Type    | Description                           |
|------------|---------|---------------------------------------|
| session_id | string  | New session UUID                      |
| phase      | string  | Session phase (typically `teaching`)  |
| block      | object  | Pre-generated learning block or null  |
| warm_start | bool    | Always true on success                |

**Error (409):** No artifact available -- use `POST /sessions` instead.

Requires `X-Learner-Id` header.

---

### GET /learners/{learner_id}/queue

Forward-looking queue for the learner.

**Response (200):**

| Field            | Type   | Description                          |
|------------------|--------|--------------------------------------|
| learner_id       | string | Learner ID                           |
| pending_reviews  | int    | Concepts due for spaced review       |
| pending_artifact | bool   | Pre-generated session waiting        |
| flagged_gaps     | array  | Flagged gap concepts (future)        |

Requires `X-Learner-Id` header.

---

### POST /learners/{learner_id}/capture

Submit a student-shared primary source.

**Request:**

| Field | Type   | Required | Description                          |
|-------|--------|----------|--------------------------------------|
| title | string | yes      | Source title (1-200 chars)           |
| text  | string | yes      | Source text (1-10000 chars)          |

**Response (201):**

| Field     | Type   | Description                 |
|-----------|--------|-----------------------------|
| source_id | string | Stable slug for the source  |

Requires `X-Learner-Id` header.

---

## Admin

### GET /admin/health

Canonical health check endpoint.

**Response (200):** Same as `GET /health`.

---

### GET /admin/scheduler

Scheduler transparency view: registered tasks and recent runs.

**Response (200):**

| Field       | Type  | Description                            |
|-------------|-------|----------------------------------------|
| tasks       | array | Registered scheduler task specs        |
| job_ids     | array | Active APScheduler job IDs             |
| recent_runs | array | Last 50 run records                    |

---

## WebSocket

### WS /ws/chat

Full session lifecycle over a single WebSocket connection.

**Client messages (JSON):**

| type    | Fields                            | Description                   |
|---------|-----------------------------------|-------------------------------|
| onboard | name, age, topic                  | Start a new session           |
| answer  | text                              | Submit an answer              |
| ready   | (none)                            | Signal readiness for check    |
| close   | (none)                            | Close the session             |

**Server messages (JSON):**

| type     | Fields                            | Description                   |
|----------|-----------------------------------|-------------------------------|
| setup    | topic, age_bracket, provider      | Session created confirmation  |
| block    | title, body, modality, minutes    | Learning block content        |
| check    | prompt, item_id                   | Check-for-understanding       |
| feedback | correct, text                     | Evaluation result             |
| summary  | duration_minutes, blocks          | Session closing summary       |
| error    | message                           | Error message                 |
| crisis   | resources                         | Crisis escalation resources   |

---

## Session Phases

| Phase          | Description                                      |
|----------------|--------------------------------------------------|
| calibrating    | Initial assessment questions                     |
| teaching       | Presenting learning blocks                       |
| checking       | Check-for-understanding in progress              |
| closing        | Session wrapping up                              |
| closed         | Session fully closed                             |
| crisis_pause   | Paused for crisis escalation                     |

---

## Error Responses

All error responses follow the FastAPI standard:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning                                      |
|--------|----------------------------------------------|
| 400    | Validation error or boundary violation        |
| 404    | Session or learner not found                  |
| 409    | Phase conflict (wrong session state)          |
| 422    | Request body validation failure               |
| 503    | Service not ready (brain store, scheduler)    |
