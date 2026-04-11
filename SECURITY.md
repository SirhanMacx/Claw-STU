# Security & Privacy

Claw-STU is a local-first tool designed for learners. Your data stays on your
machine. There are no ads, no data sales, no third-party behavioral tracking
— ever.

## Data Residency

- **Learner profiles, sessions, and brain pages** are saved to `~/.claw-stu/`
  on YOUR machine (or the machine you run `clawstu serve` on)
- **SQLite database** at `~/.claw-stu/claw-stu.db` holds structured state:
  learners, sessions, observation events, ZPD estimates, modality outcomes,
  knowledge graph triples, misconception tallies, scheduler run history
- **Brain pages** live as markdown files under `~/.claw-stu/brain/` with a
  hashed subdirectory per learner so the on-disk layout doesn't leak
  learner IDs if the directory is ever browsed or tarred
- **ONNX MiniLM embeddings model** is cached at
  `~/.claw-stu/models/all-MiniLM-L6-v2/` after first download
- **Nothing is uploaded to our servers** — we don't have servers
- The only external calls are to the LLM provider YOU configure (Ollama
  local or cloud, Anthropic, OpenAI, OpenRouter)

## API Key Storage

- API keys are stored in `~/.claw-stu/secrets.json` with `0600` file
  permissions (owner-only access) on macOS and Linux
- **Windows does not enforce POSIX permissions.** On Windows, Claw-STU
  logs a warning on first load and suggests protecting `~/.claw-stu/` via
  NTFS ACLs or a user-only profile location
- On macOS, keys can optionally use the system Keychain via
  `pip install clawstu[keyring]` (post-Phase-1)
- Keys are **never** logged, transmitted, or included in generated output
- Keys in environment variables override file-based keys

## Student Data

- The learner profile is **owned by the student**. It is portable,
  exportable, and deletable on demand.
- Profiles can be exported via `clawstu profile export <learner_id>`
  and re-imported on another machine with `clawstu profile import`
- The profile contains observational data (modality preferences, pacing,
  misconceptions, ZPD estimates) — **never** names, emails, birth dates,
  photos, or physical-location data
- The age bracket (early elementary / late elementary / middle /
  early high / late high / adult) is the only age-related field. Exact
  age is never stored.
- **No raw student utterances appear in log output.** Every structured
  log event uses a hashed `learner_id` and `session_id`. If you ever see
  PII in a log, report it as a P0 bug.

## Crisis Events

Crisis events (self-harm, abuse disclosure, acute distress) are **not**
persisted to any brain page, session page, or structured log payload
beyond a single event line: `{event: "crisis_detected", kind,
session_id_hash, learner_id_hash}`. No raw text, no `MisconceptionPage`,
no `SessionPage` body, no wiki entry.

This is intentional. SOUL.md §5 says Stuart surfaces human resources and
steps out of the teach loop. Preserving a detailed record of the specific
words a student typed during a crisis would create a PII retention hazard
we refuse to accept. An implementer who is tempted to "make the wiki
complete" by adding a crisis entry should not — the omission is the
design.

## Compliance

- **FERPA compatible** — no educational records are transmitted or
  aggregated. The profile stays on the learner's machine.
- **COPPA compatible** — no personal information is collected from
  children. The learner ID is a free-text field chosen by the user; we
  recommend a pseudonym.
- **GDPR compatible** — local-first architecture with no data collection.
  The right to be forgotten is satisfied by deleting `~/.claw-stu/` or
  the specific learner subdirectory under `~/.claw-stu/brain/<hash>/`.
- **State education data laws** — check your state's requirements for
  AI tools in education. Claw-STU does not send student data to third
  parties, but your deployment context may impose additional obligations.

## Content Safety

- **Age-appropriate content filter** is applied on every outbound string
  before it reaches the student. Deterministic keyword blocklist with
  age-bracket-specific extensions. A generated block that fails the
  filter is rejected and regenerated, not silently emitted.
- **Outbound boundary enforcer** strips sycophancy ("great question!"),
  emotional claims ("I'm proud of you"), and praise of innate ability
  before they reach the student. Stuart praises effort and strategy,
  never innate intelligence.
- **Inbound safety gate** scans every student-text entry point (calibration
  answer, check answer, free-form Socratic dialogue, student-shared
  source capture) before the evaluator or orchestrator sees it.
- **Crisis detection** is regex-based and deliberately broad. A false
  positive is a pause in a learning session. A false negative is a
  child in pain being told to analyze a primary source. We tune for
  over-escalation.

## LLM Provider Privacy

When you configure an LLM provider, learner prompts are sent to that
provider's API. Consider the following:

- **Ollama (local)** — nothing leaves your machine. Preferred for
  privacy-sensitive deployments.
- **Ollama (cloud)** — requests go to Ollama's infrastructure under
  their privacy policy.
- **Anthropic** — requests go to Anthropic's API under their privacy
  policy. Anthropic does not train on API inputs.
- **OpenAI** — requests go to OpenAI's API under their privacy policy.
  OpenAI does not train on API inputs by default.
- **OpenRouter** — requests go to whichever upstream provider you
  configure (GLM, Mistral, etc.) under that provider's policy.

Claw-STU never sends the raw learner profile to a provider. Only the
compiled-truth subset of brain context needed to ground the current
generation is included in the system prompt, bounded to ~3KB. See the
design spec `docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md`
§4.3.5 for the full context-assembly contract.

## Reporting Security Issues

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: `jon.anthony.maccarello@gmail.com` with subject line
"SECURITY: [brief description]"

We will respond within 48 hours and work with you to address the issue
before any public disclosure.

For **child safety issues** specifically (e.g., a crisis-detection false
negative, an age-inappropriate content filter bypass, a session flow
that exposes PII), use subject line "SAFETY: [brief description]" and
we will treat it as a P0.

If you find a crisis-detection false negative, **do not include the
triggering text in the email**. A description of the pattern is enough.
