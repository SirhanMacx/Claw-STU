# Configuration Resolution

Claw-STU resolves configuration in a fixed three-step cascade. The first
value found wins.

## Loading Order

| Priority | Source                           | Example                          |
|----------|----------------------------------|----------------------------------|
| 1        | Environment variables            | `export ANTHROPIC_API_KEY=sk-…`  |
| 2        | `~/.claw-stu/secrets.json`       | `{"anthropic_api_key": "sk-…"}`  |
| 3        | Built-in defaults                | Auth mode `enforce`, port 8000   |

Environment variables always override the secrets file, which always
overrides defaults.

## Auth Modes

Set via `CLAW_STU_AUTH_MODE` (env) or `auth_mode` (secrets.json).

| Mode       | Behavior                                                    |
|------------|-------------------------------------------------------------|
| `enforce`  | Requires a pre-shared Bearer token. Rejects unauthenticated requests with 401. Production default. |
| `generate` | Server generates a token on first startup and prints it to stdout. Useful for single-user deployments. |
| `dev`      | No authentication. All requests accepted. Never use in production. |

## Provider API Keys

Each LLM provider is activated by setting its key:

| Env Var               | Provider    | Notes                              |
|-----------------------|-------------|------------------------------------|
| `ANTHROPIC_API_KEY`   | Anthropic   | Claude models                      |
| `OPENAI_API_KEY`      | OpenAI      | GPT models                         |
| `GOOGLE_API_KEY`      | Google      | Gemini models                      |
| `OLLAMA_BASE_URL`     | Ollama      | Default `http://localhost:11434`    |
| `OPENROUTER_API_KEY`  | OpenRouter  | Multi-provider router              |

If no provider key is set, Claw-STU falls back to the deterministic
`EchoProvider` (no network calls, useful for testing).

## Data Directory

`CLAW_STU_DATA_DIR` controls where profiles, sessions, and brain pages
are stored. Defaults to `~/.claw-stu/`.

## Comparison with Claw-ED

Claw-ED uses a 5-step resolution chain (env vars, keyring, secrets.json,
config.json, defaults) because it manages teacher OAuth tokens and
per-transport credentials. Claw-STU intentionally keeps a simpler 3-step
chain since it has no OAuth requirement and targets single-learner
deployments.
