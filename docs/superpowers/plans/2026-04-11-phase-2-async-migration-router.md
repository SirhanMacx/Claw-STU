# Phase 2 Implementation Plan: Router + Async Migration + Live-Content Relocation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the provider layer to async (`httpx.AsyncClient`-backed), introduce a `ModelRouter` with a fallback chain that resolves per-TaskKind provider selection from `AppConfig`, and relocate `LiveContentGenerator` from `clawstu/curriculum/live_generator.py` to `clawstu/orchestrator/live_content.py` — fixing the curriculum→orchestrator import-DAG violation (spec §4.1 "B2 fix").

**Architecture:** Async cascades only as far as it needs to. The four network providers, `EchoProvider`, `ReasoningChain`, and `LiveContentGenerator` become async. `SessionRunner` and FastAPI handlers **stay sync** because they do not currently call into the orchestrator — that cascade lands in Phase 5 when live content wires into the session loop. `ModelRouter` is stateless and holds the resolved `{TaskKind → provider instance}` map at construction time, falling through `AppConfig.fallback_chain` to `EchoProvider` as the last-resort floor. `test_hierarchy.py` AST-walks `clawstu/` to enforce the §4.1 import DAG so any future phase that introduces a layering violation fails at commit time.

**Tech Stack:** `httpx.AsyncClient` (timeout=30.0), pytest-asyncio with `asyncio_mode = "auto"` (already configured), Python 3.11+ `async def`, mypy --strict (CI-enforced), `ast.parse` for the hierarchy guard.

---

## Baseline (confirmed before this plan was written)

- **HEAD:** `2ead114` — Phase 1 fully complete, pushed, CI green.
- **Tests:** 156 passing, 1.14s runtime, 85.52% coverage.
- **mypy:** `--strict` clean on 43 source files.
- **Ruff:** clean.
- **`pyproject.toml`:** already declares `asyncio_mode = "auto"` + `pytest-asyncio>=0.23` in dev deps + `httpx>=0.27,<1.0` in runtime deps.
- **`SessionRunner` does NOT call the orchestrator** (verified via grep: zero `ReasoningChain`/`LiveContentGenerator`/`_provider`/`.complete(` references in `clawstu/engagement/session.py`). This is load-bearing for Phase 2's scope: the spec's concern about "every FastAPI handler in `clawstu/api/session.py` becomes `async def`" is a **Phase 5** concern, not Phase 2.
- **`LiveContentGenerator` is constructed exactly zero times outside its own module** (verified via grep). `coverage.run.omit` already excludes `clawstu/curriculum/live_generator.py`; after relocation, the omit path updates to the new location AND the coverage floor still applies.

## File Structure Map

### Files created

| File | Purpose |
|---|---|
| `clawstu/orchestrator/router.py` | `ModelRouter` with fallback chain and per-TaskKind resolution |
| `clawstu/orchestrator/live_content.py` | **Moved** from `clawstu/curriculum/live_generator.py`. Pure rename + import rewrite + async conversion. |
| `tests/test_router.py` | `ModelRouter` contract tests: construction, per-task resolution, fallback chain ending at Echo, errors on empty chain |
| `tests/test_live_content.py` | **Moved** from the (implicit) `tests/test_live_generator.py` — a new file that didn't exist before because live_generator.py was omitted from coverage. Adds tests now because it lives in the orchestrator layer. |
| `tests/test_hierarchy.py` | AST-based import-DAG guard enforcing spec §4.1 |

### Files modified

| File | What changes |
|---|---|
| `clawstu/orchestrator/providers.py` | `LLMProvider.complete` → `async def`. `EchoProvider.complete` → `async def`. |
| `clawstu/orchestrator/provider_ollama.py` | `httpx.Client` → `httpx.AsyncClient`. `complete` → `async def`. `_post` → `async def`. `self._client.post(...)` → `await self._client.post(...)`. |
| `clawstu/orchestrator/provider_anthropic.py` | Same pattern as Ollama. |
| `clawstu/orchestrator/provider_openai.py` | Same pattern. |
| `clawstu/orchestrator/provider_openrouter.py` | Same pattern. |
| `clawstu/orchestrator/chain.py` | `ReasoningChain.run_template` and `.ask` → `async def`. `self._provider.complete(...)` → `await ...`. Constructor takes `router: ModelRouter` instead of `provider: LLMProvider` (Task 9, after router lands). |
| `clawstu/orchestrator/__init__.py` | Export `ModelRouter`. Re-export `LiveContentGenerator` from its new location. |
| `clawstu/curriculum/__init__.py` | Remove `LiveContentGenerator` export (if any) and any re-export of `live_generator`. |
| `pyproject.toml` | Update `[tool.coverage.run] omit` to reference the new path. Remove the old one once the file is gone. |
| `tests/conftest.py` | Add `async_router_for_testing(provider)` fixture. |
| `tests/test_orchestrator.py` | `def test_*` → `async def test_*` for the 2 tests that call `provider.complete` or `chain.run_template`/`chain.ask`. `SycophantProvider.complete` → `async def`. Replace `provider=EchoProvider()` with `router=async_router_for_testing(EchoProvider())`. |
| `tests/test_provider_ollama.py` | Tests that call `provider.complete(...)` become `async def` and `await` the call. `httpx.Client(transport=transport)` → `httpx.AsyncClient(transport=transport)`. |
| `tests/test_provider_anthropic.py` | Same. |
| `tests/test_provider_openai.py` | Same. |
| `tests/test_provider_openrouter.py` | Same. |

### Files NOT modified in Phase 2 (deferred)

| File | Why not |
|---|---|
| `clawstu/engagement/session.py` | Does not currently call the orchestrator. Phase 5 wires live content + flips runner methods to async. |
| `clawstu/api/session.py` | Handlers are sync; they only touch `SessionRunner` (sync). Phase 5 flips them when the runner flips. |
| `clawstu/cli.py` | No provider calls in Phase 1. |
| `clawstu/assessment/`, `clawstu/curriculum/content.py`, `clawstu/curriculum/pathway.py` | Deterministic; no LLM calls. |
| `clawstu/profile/`, `clawstu/safety/` | Deterministic; stay sync per §4.2.1.a. |

---

## Task 0: Baseline verification

**Files:** none modified.

- [ ] **Step 1:** Confirm the repo is in the expected Phase-1 state.

Run these in parallel:
```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
git log --oneline -1
/tmp/claw-stu-venv/bin/python -m pytest -q
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
grep -n asyncio_mode pyproject.toml
grep -rn "ReasoningChain\|LiveContentGenerator\|_provider" clawstu/engagement/session.py || echo "session.py clean"
```

Expected:
- `git log`: HEAD is `2ead114` ("fix(test): strip ANSI...") or later.
- `pytest -q`: 156 passed.
- `mypy clawstu`: no issues in 43 source files.
- `ruff`: All checks passed.
- `asyncio_mode`: `asyncio_mode = "auto"` present.
- `session.py clean` printed (meaning grep found nothing).

If any of these fail, stop and report — Phase 2 cannot start from a broken baseline.

---

## Task 1: Flip `LLMProvider` protocol + `EchoProvider` + `ReasoningChain` + `LiveContentGenerator` to async

**Rationale:** These four pieces MUST move atomically. The protocol change forces `EchoProvider`, `ReasoningChain`, and `LiveContentGenerator` to update in lockstep because they're all on the same type bus. The 4 network providers (Tasks 2-5) are structurally independent — mypy only enforces `LLMProvider` compliance when a concrete provider is passed to a `LLMProvider`-annotated site, and in Phase 1 the only such sites are `ReasoningChain.__init__` and `LiveContentGenerator.__init__`, both of which only receive `EchoProvider` in test code. **After this task:** the 4 network providers are still sync and still pass their own tests; they're just no longer structurally substitutable for `LLMProvider` until Tasks 2-5 flip them.

**Files:**
- Modify: `clawstu/orchestrator/providers.py`
- Modify: `clawstu/orchestrator/chain.py`
- Modify: `clawstu/curriculum/live_generator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test that proves the flip happened.**

Append to `tests/test_orchestrator.py`:

```python
import inspect


class TestAsyncProtocol:
    """The LLMProvider.complete method must be declared async.

    Phase 2 hard contract (spec §4.2.1.a): every provider call is
    awaited, so both the Protocol and every concrete provider must
    declare `async def complete`. This test pins the contract against
    future regressions.
    """

    def test_echo_provider_complete_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(EchoProvider.complete), (
            "EchoProvider.complete must be declared `async def` "
            "per spec §4.2.1.a"
        )
```

- [ ] **Step 2: Run and confirm it fails.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_orchestrator.py::TestAsyncProtocol -v
```

Expected: **FAIL** — `EchoProvider.complete` is not a coroutine yet.

- [ ] **Step 3: Flip `LLMProvider.complete` and `EchoProvider.complete` in `clawstu/orchestrator/providers.py`.**

Edit `clawstu/orchestrator/providers.py`:

Change the `LLMProvider` Protocol's `complete` from:
```python
    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """Synchronous completion. Raises `ProviderError` on failure."""
        ...
```
to:
```python
    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
        """Asynchronous completion. Raises `ProviderError` on failure.

        Phase 2 (spec §4.2.1.a) flipped this to `async def`. All
        concrete providers use `httpx.AsyncClient` and every call
        site must `await` the result.
        """
        ...
```

Change `EchoProvider.complete` from `def` to `async def`. The body stays identical — it's still a pure in-memory operation — but the signature is:
```python
    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> LLMResponse:
```

Also update `EchoProvider`'s class docstring's second paragraph to mention the async protocol.

- [ ] **Step 4: Flip `ReasoningChain.run_template` and `.ask` in `clawstu/orchestrator/chain.py`.**

Edit `clawstu/orchestrator/chain.py`:

Change `def run_template(...)` to `async def run_template(...)` and `response: LLMResponse = self._provider.complete(...)` to `response: LLMResponse = await self._provider.complete(...)`.

Change `def ask(...)` to `async def ask(...)` and `response = self._provider.complete(...)` to `response = await self._provider.complete(...)`.

Keep `ReasoningChain.__init__` signature unchanged for now (`provider: LLMProvider`). Task 9 flips it to take `router: ModelRouter`.

- [ ] **Step 5: Flip `LiveContentGenerator` methods in `clawstu/curriculum/live_generator.py`.**

Edit `clawstu/curriculum/live_generator.py`:

Change the signatures of `generate_pathway`, `generate_block`, `generate_check`, and `_ask_json` from `def` to `async def`.

Change `response = self._provider.complete(...)` in `_ask_json` to `response = await self._provider.complete(...)`.

In `generate_pathway`, `generate_block`, and `generate_check`, the call path is:
```python
payload = self._ask_json(system=..., user=...)
```
This becomes:
```python
payload = await self._ask_json(system=..., user=...)
```

The offline branches (`if isinstance(self._provider, EchoProvider): ...`) are pure in-memory operations — they stay sync. The `async def` wrapper is what matters; the method itself can return via either branch.

**Do NOT** flip the helper functions `_offline_pathway`, `_offline_block`, `_offline_check`, or `_require_str` — they are pure data manipulation and stay sync.

**Do NOT** flip `_SafetyGate.check_strings` — it's pure python and stays sync.

Keep the `LiveContentGenerator.__init__` signature unchanged (`provider: LLMProvider`). Task 10 flips it to take `router: ModelRouter`.

- [ ] **Step 6: Update `tests/test_orchestrator.py` so existing tests call the new async API.**

The existing test class `TestEchoProvider` has two tests that call `provider.complete(...)` synchronously:
```python
def test_returns_echo_of_last_user_message(self) -> None:
    ...
    response = provider.complete(system="sys", messages=[LLMMessage(role="user", content="hello")])
    ...

def test_requires_user_message(self) -> None:
    ...
    with pytest.raises(ProviderError):
        provider.complete(system="sys", messages=[])
```

Flip both to `async def` and `await` the call:
```python
async def test_returns_echo_of_last_user_message(self) -> None:
    ...
    response = await provider.complete(system="sys", messages=[LLMMessage(role="user", content="hello")])
    ...

async def test_requires_user_message(self) -> None:
    ...
    with pytest.raises(ProviderError):
        await provider.complete(system="sys", messages=[])
```

`TestReasoningChain.test_chain_runs_template_and_returns_text` calls `chain.run_template(...)`. Flip the test to `async def` and `await` it:
```python
async def test_chain_runs_template_and_returns_text(self) -> None:
    chain = ReasoningChain(provider=EchoProvider())
    out = await chain.run_template(
        "socratic_continuation",
        user_input="",
        template_vars={...},
    )
    ...
```

`TestReasoningChain.test_chain_rewrites_outbound_sycophancy` has an inline `SycophantProvider` stub with a sync `complete` method. Flip that too:
```python
class SycophantProvider:
    name = "sycophant"

    async def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> object:
        from clawstu.orchestrator.providers import LLMResponse
        return LLMResponse(
            text="Great question! You're so smart.",
            provider=self.name,
            model="sycophant-0",
        )
```

And flip the test method:
```python
async def test_chain_rewrites_outbound_sycophancy(self) -> None:
    chain = ReasoningChain(provider=SycophantProvider())
    out = await chain.ask("anything")
    ...
```

**Note on `SycophantProvider` signature:** the existing test's stub also needs `model: str | None = None` added to match Task 9 of Phase 1 — the Phase 1 widening should already have touched this file. Double-check; if it's missing, add it.

- [ ] **Step 7: Run the target tests.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_orchestrator.py -v
```

Expected: all tests pass including `TestAsyncProtocol::test_echo_provider_complete_is_coroutine`.

- [ ] **Step 8: Run the full suite.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest -q
```

Expected: **156 - 4 + 1 = 153 tests passing.**

Wait — that math needs to be correct. Let me count:
- 156 baseline
- +1 new test (`test_echo_provider_complete_is_coroutine`)
- Tests migrated from sync→async: 2 in `TestEchoProvider`, 2 in `TestReasoningChain`. These are NOT new tests — they're the same tests flipped — so no count change.

Expected: **157 passed** (156 + 1).

**If the count is 153 or anything else unexpected, STOP.** The async flip may have broken test collection. Check that `asyncio_mode = "auto"` is still set and that `pytest-asyncio` is installed in the venv.

- [ ] **Step 9: Run mypy + ruff.**

```bash
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
```

Expected: both clean.

**Why mypy stays clean:** the 4 concrete network providers do NOT explicitly inherit from `LLMProvider` (they duck-type the protocol), and nothing in Phase 1 does `x: LLMProvider = OllamaProvider(...)` — the only `LLMProvider`-annotated sites are `chain.py:31` (`provider: LLMProvider`) and `live_generator.py:193` (`provider: LLMProvider`), and both are flipped atomically in this task. So mypy has no "does OllamaProvider satisfy async LLMProvider?" check to run during the intermediate state.

**If mypy fails anyway,** do NOT add `# type: ignore` — that would violate the Phase 1 zero-type-ignore invariant. Stop, report the exact errors, and diagnose the unexpected site.

- [ ] **Step 10: Commit.**

```bash
git add clawstu/orchestrator/providers.py clawstu/orchestrator/chain.py clawstu/curriculum/live_generator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): flip LLMProvider + EchoProvider + ReasoningChain + LiveContentGenerator to async

Spec §4.2.1.a: every code path that touches a provider is async.
This commit flips the atomic core:
- LLMProvider.complete Protocol -> async def
- EchoProvider.complete -> async def (body unchanged — pure Python)
- ReasoningChain.run_template / .ask -> async def (+ await provider.complete)
- LiveContentGenerator.generate_pathway / generate_block / generate_check / _ask_json -> async def

Tests flip in lockstep:
- TestEchoProvider tests -> async def
- TestReasoningChain tests + inline SycophantProvider.complete -> async def
- New TestAsyncProtocol::test_echo_provider_complete_is_coroutine
  uses inspect.iscoroutinefunction to pin the contract against regression

The four concrete network providers (Ollama / Anthropic / OpenAI /
OpenRouter) are still sync at this point. Tasks 2-5 flip them using
httpx.AsyncClient in lockstep with their own test files. Until then
they are structurally NOT substitutable for LLMProvider, but nothing
in the Phase 1 codebase type-annotates them that way so mypy remains
clean.

SessionRunner and api/session.py handlers are NOT flipped in this
commit — they do not call the orchestrator in Phase 1. That cascade
is a Phase 5 concern.

Test count: 157 passed (156 + 1 new). mypy --strict clean. Ruff clean."
```

---

## Task 2: Flip `OllamaProvider` to `httpx.AsyncClient` + `async def`

**Files:**
- Modify: `clawstu/orchestrator/provider_ollama.py`
- Modify: `tests/test_provider_ollama.py`

- [ ] **Step 1: Write the failing contract test.**

Add this test to `tests/test_provider_ollama.py` near the top (after imports, before `_make_provider`):

```python
import inspect

from clawstu.orchestrator.provider_ollama import OllamaProvider as _OP


def test_ollama_complete_is_async() -> None:
    assert inspect.iscoroutinefunction(_OP.complete), (
        "OllamaProvider.complete must be async def per Phase 2"
    )
```

- [ ] **Step 2: Confirm it fails.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_ollama.py::test_ollama_complete_is_async -v
```

Expected: FAIL.

- [ ] **Step 3: Flip `OllamaProvider` to async.**

Edit `clawstu/orchestrator/provider_ollama.py`. The changes are mechanical:

1. Change `client: httpx.Client | None = None` to `client: httpx.AsyncClient | None = None` in `__init__`.
2. Change `self._client = client or httpx.Client(timeout=timeout)` to `self._client = client or httpx.AsyncClient(timeout=timeout)`.
3. Change `def complete(...)` to `async def complete(...)`.
4. Change `body = self._post(payload)` to `body = await self._post(payload)`.
5. Change `def _post(...)` to `async def _post(...)`.
6. Change `http_response = self._client.post(...)` to `http_response = await self._client.post(...)`.
7. Keep `_build_payload` and `_parse_body` sync — they are pure data operations.

- [ ] **Step 4: Flip all `test_provider_ollama.py` tests to async.**

Every existing test that calls `provider.complete(...)` becomes `async def test_*` and `await provider.complete(...)`.

Every `_make_provider` call site must supply an `httpx.AsyncClient`:
```python
def _make_provider(transport: httpx.MockTransport) -> OllamaProvider:
    client = httpx.AsyncClient(transport=transport)
    return OllamaProvider(
        base_url="http://localhost:11434",
        api_key=None,
        client=client,
    )
```

**For the auth-header test (`test_ollama_with_api_key_sets_authorization_header`)**, the inline `httpx.Client(transport=httpx.MockTransport(handler))` also becomes `httpx.AsyncClient(transport=...)`.

**For every `provider.complete(...)` call in a test, wrap it in `await`:**
```python
async def test_ollama_happy_path() -> None:
    ...
    response = await provider.complete(
        system="You are Stuart.",
        messages=[LLMMessage(role="user", content="Hello?")],
        max_tokens=256,
        temperature=0.3,
        model="llama3.2",
    )
    ...
```

Every test function declaration changes `def test_*` → `async def test_*`.

- [ ] **Step 5: Run the Ollama suite.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_provider_ollama.py -v
```

Expected: **9 passed** (8 existing + 1 new contract test).

- [ ] **Step 6: Full suite + gates.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest -q
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
```

Expected: **158 passed** (157 + 1). Mypy clean. Ruff clean.

- [ ] **Step 7: Commit.**

```bash
git add clawstu/orchestrator/provider_ollama.py tests/test_provider_ollama.py
git commit -m "feat(orchestrator): flip OllamaProvider to httpx.AsyncClient + async def

Mechanical flip: httpx.Client -> httpx.AsyncClient, def -> async def,
self._client.post(...) -> await self._client.post(...).

Defense-in-depth isinstance guards from Phase 1 are preserved
verbatim. _build_payload and _parse_body stay sync (pure data).

Test file flipped to async def test_* with await on every
provider.complete(...) call. MockTransport wiring now goes through
httpx.AsyncClient(transport=...) instead of httpx.Client.

New contract test: test_ollama_complete_is_async pins the method
to inspect.iscoroutinefunction so a future regression is loud.

Test count: 158 passed."
```

---

## Task 3: Flip `AnthropicProvider` to async

**Files:**
- Modify: `clawstu/orchestrator/provider_anthropic.py`
- Modify: `tests/test_provider_anthropic.py`

Same pattern as Task 2. The structural changes are:

- [ ] **Step 1:** Add a `test_anthropic_complete_is_async` contract test using `inspect.iscoroutinefunction(AnthropicProvider.complete)`.
- [ ] **Step 2:** Run and confirm fail.
- [ ] **Step 3:** Flip `provider_anthropic.py`: `httpx.Client` → `httpx.AsyncClient`, `def complete` → `async def complete`, `def _post` → `async def _post`, `self._client.post(...)` → `await self._client.post(...)`, `body = self._post(...)` → `body = await self._post(...)`.
- [ ] **Step 4:** Flip `test_provider_anthropic.py` tests to `async def` and `await`. Switch `_make_provider` to build `httpx.AsyncClient`.
- [ ] **Step 5:** Run `pytest tests/test_provider_anthropic.py -v` → 6 passed (5 existing + 1 new).
- [ ] **Step 6:** Run full suite — **159 passed** (158 + 1). mypy + ruff clean.
- [ ] **Step 7:** Commit:
```bash
git add clawstu/orchestrator/provider_anthropic.py tests/test_provider_anthropic.py
git commit -m "feat(orchestrator): flip AnthropicProvider to httpx.AsyncClient + async def

Same mechanical flip as Task 2 Ollama:
- httpx.Client -> httpx.AsyncClient
- def -> async def on complete and _post
- await on the outgoing post call and on _post from complete

Defense-in-depth guards unchanged. _build_payload / _parse_body stay sync.
Test file flipped to async def test_* + await.
New test_anthropic_complete_is_async pins the contract.

Test count: 159 passed."
```

---

## Task 4: Flip `OpenAIProvider` to async

**Files:**
- Modify: `clawstu/orchestrator/provider_openai.py`
- Modify: `tests/test_provider_openai.py`

Same pattern as Tasks 2-3.

- [ ] **Step 1:** Add `test_openai_complete_is_async` contract test.
- [ ] **Step 2:** Confirm fail.
- [ ] **Step 3:** Flip `provider_openai.py` (6 changes: `httpx.Client` → `httpx.AsyncClient` twice, `async def complete`, `async def _post`, `await self._client.post`, `await self._post(payload)`).
- [ ] **Step 4:** Flip `test_provider_openai.py`: `async def test_*`, `await provider.complete(...)`, `httpx.AsyncClient(transport=...)`.
- [ ] **Step 5:** `pytest tests/test_provider_openai.py -v` → 5 passed (4 + 1).
- [ ] **Step 6:** Full suite — **160 passed**. mypy + ruff clean.
- [ ] **Step 7:** Commit:
```bash
git add clawstu/orchestrator/provider_openai.py tests/test_provider_openai.py
git commit -m "feat(orchestrator): flip OpenAIProvider to httpx.AsyncClient + async def

Same pattern as Tasks 2-3. New test_openai_complete_is_async pins
the contract. Test count: 160 passed."
```

---

## Task 5: Flip `OpenRouterProvider` to async

**Files:**
- Modify: `clawstu/orchestrator/provider_openrouter.py`
- Modify: `tests/test_provider_openrouter.py`

Same pattern.

- [ ] **Step 1:** Add `test_openrouter_complete_is_async` contract test.
- [ ] **Step 2:** Confirm fail.
- [ ] **Step 3:** Flip `provider_openrouter.py`. Note: `HTTP-Referer` and `X-Title` headers stay in `_post` unchanged.
- [ ] **Step 4:** Flip `test_provider_openrouter.py` same way.
- [ ] **Step 5:** `pytest tests/test_provider_openrouter.py -v` → 5 passed.
- [ ] **Step 6:** Full suite — **161 passed**. mypy + ruff clean.
- [ ] **Step 7:** Commit:
```bash
git add clawstu/orchestrator/provider_openrouter.py tests/test_provider_openrouter.py
git commit -m "feat(orchestrator): flip OpenRouterProvider to httpx.AsyncClient + async def

Same pattern. HTTP-Referer and X-Title attribution headers unchanged.
New test_openrouter_complete_is_async pins the contract.

Test count: 161. All four network providers are now async. The
provider layer is fully async across the LLMProvider protocol."
```

---

## Task 6: Create `clawstu/orchestrator/router.py` with `ModelRouter`

**Files:**
- Create: `clawstu/orchestrator/router.py`
- Create: `tests/test_router.py`

**Design (from spec §4.2.3):**
- `ModelRouter` is stateless. It holds a `dict[TaskKind, tuple[LLMProvider, str]]` resolved at construction time from an `AppConfig` and a dict `{name: LLMProvider}` of available providers.
- `for_task(kind: TaskKind) -> tuple[LLMProvider, str]` returns the primary `(provider, model)` for that task.
- Fallback chain: if the primary is unreachable OR construction of that provider failed, falls through `AppConfig.fallback_chain` in order, ending at `EchoProvider`.
- **Reachability is NOT checked at router construction time** — it's checked lazily at `for_task` call time by testing `provider is not None`. (Real network health checks are a Phase 2 extension: Task 17 of Phase 1 deferred real doctor `--ping` to Phase 2. In Phase 2, the router only knows about presence/absence of API keys, not whether the server is up. Reachability probing happens at `doctor --ping` time using actual requests.)

The `ModelRouter` is constructed with:
```python
ModelRouter(
    config: AppConfig,
    providers: dict[str, LLMProvider],  # name -> instance
)
```

`providers` is a dict from provider name (e.g., "ollama") to a live instance. Providers whose `api_key` is missing in config are simply absent from the dict — the router notices and falls through.

- [ ] **Step 1: Write the failing tests.**

Create `tests/test_router.py`:

```python
"""ModelRouter — per-TaskKind resolution + fallback chain tests."""
from __future__ import annotations

import pytest

from clawstu.orchestrator.config import AppConfig, TaskRoute
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter, RouterConstructionError
from clawstu.orchestrator.task_kinds import TaskKind


def _echo() -> EchoProvider:
    return EchoProvider()


def test_router_resolves_every_task_to_a_provider() -> None:
    """Every TaskKind must resolve to some (provider, model)."""
    cfg = AppConfig()
    providers: dict[str, LLMProvider] = {"echo": _echo()}
    router = ModelRouter(config=cfg, providers=providers)
    for kind in TaskKind:
        provider, model = router.for_task(kind)
        assert provider is not None
        assert isinstance(model, str) and model


def test_router_prefers_primary_provider_when_available() -> None:
    """If ollama is configured and available, SOCRATIC_DIALOGUE goes there."""
    cfg = AppConfig()  # primary_provider="ollama" by default
    ollama = _echo()  # stand-in for an OllamaProvider
    providers: dict[str, LLMProvider] = {
        "ollama": ollama,
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert provider is ollama
    assert model == "llama3.2"  # from _default_task_routing()


def test_router_falls_through_when_primary_missing() -> None:
    """If ollama is not in providers, SOCRATIC falls through to the next
    provider in the fallback_chain that IS in providers."""
    cfg = AppConfig()  # fallback chain: ollama -> openai -> anthropic -> openrouter
    openai_provider = _echo()
    providers: dict[str, LLMProvider] = {
        "openai": openai_provider,
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    provider, _model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert provider is openai_provider


def test_router_falls_through_to_echo_as_last_resort() -> None:
    """If none of the fallback_chain providers are available, echo is
    the guaranteed last-resort floor."""
    cfg = AppConfig()
    echo = _echo()
    providers: dict[str, LLMProvider] = {"echo": echo}
    router = ModelRouter(config=cfg, providers=providers)
    provider, _model = router.for_task(TaskKind.BLOCK_GENERATION)
    assert provider is echo


def test_router_raises_when_no_provider_at_all() -> None:
    """If neither any fallback provider nor echo is provided, the
    router refuses to construct — an empty router is always a bug."""
    cfg = AppConfig()
    with pytest.raises(RouterConstructionError, match="echo"):
        ModelRouter(config=cfg, providers={})


def test_router_uses_task_model_not_provider_default() -> None:
    """The model returned by for_task comes from AppConfig.task_routing,
    NOT from the provider's own default."""
    cfg = AppConfig()
    providers: dict[str, LLMProvider] = {
        "openrouter": _echo(),
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    _provider, model = router.for_task(TaskKind.BLOCK_GENERATION)
    assert model == "z-ai/glm-4.5-air"  # from spec §4.2.4


def test_router_honors_custom_task_routing_override() -> None:
    """If AppConfig.task_routing is overridden, the router respects it."""
    from clawstu.orchestrator.config import TaskRoute

    cfg = AppConfig(
        task_routing={
            **AppConfig().task_routing,
            TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
                provider="openai",
                model="gpt-4o-mini",
            ),
        },
    )
    providers: dict[str, LLMProvider] = {
        "openai": _echo(),
        "echo": _echo(),
    }
    router = ModelRouter(config=cfg, providers=providers)
    _provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
    assert model == "gpt-4o-mini"
```

- [ ] **Step 2: Run and confirm all 7 tests fail.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_router.py -v
```

Expected: `ImportError: cannot import name 'ModelRouter' from 'clawstu.orchestrator.router'` — the module doesn't exist yet.

- [ ] **Step 3: Create `clawstu/orchestrator/router.py`.**

```python
"""ModelRouter — per-TaskKind provider + model resolution.

Stateless. Holds a resolved map from `TaskKind` to `(LLMProvider,
model_name)` at construction time. Falls through `AppConfig.fallback_chain`
if the primary provider for a task is not in the supplied providers dict,
ending at `EchoProvider` as a guaranteed last-resort floor.

Reachability probing (can the server actually be reached?) is NOT done
here — that's `clawstu doctor --ping`'s job. The router only knows
about presence/absence of a provider in the `providers` dict, which
callers build from `load_config()` results (missing api_key => missing
provider).
"""
from __future__ import annotations

from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.task_kinds import TaskKind


class RouterConstructionError(RuntimeError):
    """Raised when the router cannot be constructed.

    Currently the only way this fires is if `providers` does not contain
    an `"echo"` entry. Echo is the fallback-chain floor; without it, any
    task whose fallback chain exhausts has nowhere to go and the router
    would silently fail at `for_task` time. Loud-fail at construction.
    """


class ModelRouter:
    """Stateless resolver: TaskKind -> (LLMProvider, model_name).

    Construction resolves every TaskKind to the first provider in its
    fallback chain that is actually available. The resolved map is
    cached for the lifetime of the router.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        providers: dict[str, LLMProvider],
    ) -> None:
        if "echo" not in providers:
            raise RouterConstructionError(
                "ModelRouter requires an 'echo' provider as the "
                "fallback-chain floor; got providers: "
                f"{sorted(providers.keys())}"
            )
        self._resolved: dict[TaskKind, tuple[LLMProvider, str]] = {}
        for kind, route in config.task_routing.items():
            provider, model = self._resolve_one(
                primary=(route.provider, route.model),
                fallback_chain=config.fallback_chain,
                providers=providers,
            )
            self._resolved[kind] = (provider, model)

    def for_task(self, kind: TaskKind) -> tuple[LLMProvider, str]:
        """Return the resolved (provider, model) for this task kind.

        Always succeeds — every TaskKind is resolved at construction
        time and cached. An unknown TaskKind raises KeyError, which is
        a programmer error (every enum value must be in the routing
        table by spec §4.2.4).
        """
        return self._resolved[kind]

    def _resolve_one(
        self,
        *,
        primary: tuple[str, str],
        fallback_chain: tuple[str, ...],
        providers: dict[str, LLMProvider],
    ) -> tuple[LLMProvider, str]:
        """Walk primary -> fallback_chain -> echo, returning the first
        provider that exists in `providers`.

        Preserves the primary's model name when the primary is available.
        When we fall through to a chain provider, we still use the task's
        configured model (which may or may not be valid for that
        provider — but the router is not in the business of validating
        model strings against provider capabilities; that's the provider's
        job at `.complete()` time).
        """
        primary_name, primary_model = primary
        if primary_name in providers:
            return providers[primary_name], primary_model
        for name in fallback_chain:
            if name == primary_name:
                continue  # already tried
            if name in providers:
                return providers[name], primary_model
        # Last-resort floor: echo is guaranteed to be present by
        # construction-time check in __init__.
        return providers["echo"], primary_model
```

- [ ] **Step 4: Run the router tests.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_router.py -v
```

Expected: **7 passed.**

- [ ] **Step 5: Full suite + gates.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest -q
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
```

Expected: **168 passed** (161 + 7 new). Mypy clean. Ruff clean.

- [ ] **Step 6: Commit.**

```bash
git add clawstu/orchestrator/router.py tests/test_router.py
git commit -m "feat(orchestrator): add ModelRouter with fallback chain (spec §4.2.3)

ModelRouter resolves per-TaskKind (provider, model) pairs at
construction time from AppConfig + a dict of available providers.
Stateless afterwards; for_task() is a pure dict lookup.

Fallback chain walks AppConfig.fallback_chain in order, ending at
'echo' as the guaranteed last-resort floor. If echo is missing from
the providers dict, construction fails loud via
RouterConstructionError — an empty router is always a bug.

Reachability probing is NOT done here (that's doctor --ping in
Phase 2 extension). The router only knows presence/absence of a
provider in the supplied dict. Callers build that dict from
load_config() based on which api_key fields are populated.

7 tests cover: every TaskKind resolves, primary preferred when
available, fallback walks the chain, echo floor works, empty
providers raises, task model (not provider default) is returned,
custom task_routing overrides respected.

Test count: 168 passed."
```

---

## Task 7: Add `async_router_for_testing` fixture to `tests/conftest.py`

**Files:**
- Modify: `tests/conftest.py`

**Rationale:** Tasks 9 and 10 flip `ReasoningChain.__init__` and `LiveContentGenerator.__init__` to take `router: ModelRouter` instead of `provider: LLMProvider`. Every existing test that constructs these by passing an `EchoProvider` needs a trivial one-line wrapper. The fixture centralizes that.

- [ ] **Step 1: Append the fixture.**

Append to `tests/conftest.py`:

```python
from clawstu.orchestrator.config import AppConfig
from clawstu.orchestrator.providers import EchoProvider, LLMProvider
from clawstu.orchestrator.router import ModelRouter


def async_router_for_testing(
    provider: LLMProvider | None = None,
) -> ModelRouter:
    """One-liner router wrapping a single provider.

    Every task in the routing table resolves to the same provider,
    because the fallback chain collapses to echo. This is exactly
    what a test that used to say `provider=EchoProvider()` wants.

    Callers pass an EchoProvider (or any async LLMProvider) and get
    back a ModelRouter they can drop into ReasoningChain or
    LiveContentGenerator.
    """
    echo = provider if isinstance(provider, EchoProvider) else EchoProvider()
    providers: dict[str, LLMProvider] = {"echo": echo}
    if provider is not None and not isinstance(provider, EchoProvider):
        # Register the custom provider under a synthetic name so the
        # router can pick it up via the fallback chain if the caller
        # overrides AppConfig.fallback_chain accordingly. Default
        # config's chain is ollama/openai/anthropic/openrouter, so a
        # SycophantProvider-style stub needs to be registered by name.
        providers[provider.name] = provider
    return ModelRouter(config=AppConfig(), providers=providers)
```

**Note on the helper's name-based registration:** this is deliberately permissive — any provider object with a `name` attribute can be registered. The helper doesn't try to be clever about mapping it to the default chain; tests that need a non-Echo provider to win the router resolution should override `AppConfig.fallback_chain` explicitly.

- [ ] **Step 2: Smoke-test the fixture.**

```bash
/tmp/claw-stu-venv/bin/python -c "
from tests.conftest import async_router_for_testing
from clawstu.orchestrator.providers import EchoProvider
from clawstu.orchestrator.task_kinds import TaskKind

router = async_router_for_testing()
provider, model = router.for_task(TaskKind.SOCRATIC_DIALOGUE)
assert isinstance(provider, EchoProvider)
print('OK:', model)
"
```

Expected: `OK: llama3.2` (the default model for SOCRATIC_DIALOGUE, returned even though the actual provider is Echo because of fallback).

- [ ] **Step 3: Full suite still green.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest -q
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
```

Expected: **168 passed**. Mypy clean. Ruff clean.

- [ ] **Step 4: Commit.**

```bash
git add tests/conftest.py
git commit -m "test(conftest): add async_router_for_testing helper

One-liner wrapper that builds a ModelRouter containing a single
EchoProvider as the fallback-chain floor. Any test that used to
say ReasoningChain(provider=EchoProvider()) can now say
ReasoningChain(router=async_router_for_testing()) once Tasks 9-10
flip the constructors.

Returns a router built from AppConfig defaults — so for_task()
returns the spec §4.2.4 model strings, which is exactly what
tests want to assert against.

Test count unchanged: 168 passed."
```

---

## Task 8: Flip `ReasoningChain.__init__` to take `router: ModelRouter`

**Files:**
- Modify: `clawstu/orchestrator/chain.py`
- Modify: `tests/test_orchestrator.py`

**Rationale:** Now that the router exists and the fixture is ready, `ReasoningChain` can stop taking a raw provider. It takes a router and calls `router.for_task(kind)` to get the provider + model for each call. For MVP, `run_template` defaults to `TaskKind.SOCRATIC_DIALOGUE` (that's what templates like `socratic_continuation` are for) and `ask` also defaults there. Per-call overrides are not in scope for Phase 2 — they're a Phase 5 concern once the router is wired into the full session loop.

- [ ] **Step 1: Write the failing test.**

Append to `tests/test_orchestrator.py` inside `TestReasoningChain`:

```python
async def test_chain_accepts_router_argument(self) -> None:
    """Phase 2: ReasoningChain(router=...) is the new construction form."""
    from tests.conftest import async_router_for_testing

    chain = ReasoningChain(router=async_router_for_testing())
    out = await chain.run_template(
        "socratic_continuation",
        user_input="",
        template_vars={
            "concept": "c",
            "tier": "meeting",
            "student_utterance": "because",
        },
    )
    assert isinstance(out, str) and out
```

- [ ] **Step 2: Run and confirm fail.**

Expected: `TypeError: ReasoningChain.__init__() got an unexpected keyword argument 'router'`.

- [ ] **Step 3: Flip `ReasoningChain.__init__` and the two methods.**

Edit `clawstu/orchestrator/chain.py`:

Change imports:
```python
from clawstu.orchestrator.prompts import PromptLibrary
from clawstu.orchestrator.providers import LLMMessage, LLMResponse, ProviderError
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
from clawstu.safety.boundaries import BoundaryEnforcer
```

Change `__init__`:
```python
def __init__(
    self,
    *,
    router: ModelRouter,
    prompts: PromptLibrary | None = None,
    boundaries: BoundaryEnforcer | None = None,
) -> None:
    self._router = router
    self._prompts = prompts or PromptLibrary()
    self._boundaries = boundaries or BoundaryEnforcer()
```

Change `run_template` to resolve via the router:
```python
async def run_template(
    self,
    template_name: str,
    *,
    user_input: str,
    template_vars: dict[str, object] | None = None,
    task_kind: TaskKind = TaskKind.SOCRATIC_DIALOGUE,
) -> str:
    """Render a template, call the provider resolved for `task_kind`,
    filter the output. See spec §4.2.3 for routing semantics.
    """
    template = self._prompts.get(template_name)
    rendered = template.render(**(template_vars or {}))
    messages = [LLMMessage(role="user", content=rendered)]
    provider, model = self._router.for_task(task_kind)
    try:
        response: LLMResponse = await provider.complete(
            system=self._prompts.soul_system(),
            messages=messages,
            model=model,
        )
    except ProviderError:
        raise
    text = response.text
    violation = self._boundaries.scan_outbound(text)
    if violation is not None:
        return self._boundaries.restate(violation)
    return text
```

Change `ask` similarly:
```python
async def ask(
    self,
    user_input: str,
    *,
    task_kind: TaskKind = TaskKind.SOCRATIC_DIALOGUE,
) -> str:
    """Run an ad-hoc prompt. Used by free-form Socratic dialogue."""
    messages = [LLMMessage(role="user", content=user_input)]
    provider, model = self._router.for_task(task_kind)
    try:
        response = await provider.complete(
            system=self._prompts.soul_system(),
            messages=messages,
            model=model,
        )
    except ProviderError:
        raise
    violation = self._boundaries.scan_outbound(response.text)
    if violation is not None:
        return self._boundaries.restate(violation)
    return response.text
```

- [ ] **Step 4: Migrate existing `test_orchestrator.py` tests to use `async_router_for_testing`.**

The two pre-existing `TestReasoningChain` tests currently say:
```python
chain = ReasoningChain(provider=EchoProvider())
chain = ReasoningChain(provider=SycophantProvider())
```

The first becomes:
```python
from tests.conftest import async_router_for_testing
...
chain = ReasoningChain(router=async_router_for_testing())
```

The second needs the `SycophantProvider` stub to be wrapped via the helper so it reaches the router's fallback chain. Since `async_router_for_testing` currently routes everything via Echo when given a non-Echo provider unless the fallback_chain is overridden, the cleanest thing for this test is to **construct the router manually**:

```python
async def test_chain_rewrites_outbound_sycophancy(self) -> None:
    class SycophantProvider:
        name = "sycophant"

        async def complete(
            self,
            *,
            system: str,
            messages: list[LLMMessage],
            max_tokens: int = 1024,
            temperature: float = 0.2,
            model: str | None = None,
        ) -> object:
            from clawstu.orchestrator.providers import LLMResponse
            return LLMResponse(
                text="Great question! You're so smart.",
                provider=self.name,
                model="sycophant-0",
            )

    from clawstu.orchestrator.config import AppConfig
    from clawstu.orchestrator.providers import EchoProvider
    from clawstu.orchestrator.router import ModelRouter

    # Override the routing table so SOCRATIC_DIALOGUE routes to the
    # sycophant provider, with Echo still present as the floor.
    from clawstu.orchestrator.config import TaskRoute
    from clawstu.orchestrator.task_kinds import TaskKind

    defaults = AppConfig().task_routing
    cfg = AppConfig(
        task_routing={
            **defaults,
            TaskKind.SOCRATIC_DIALOGUE: TaskRoute(
                provider="sycophant", model="sycophant-0"
            ),
        },
        fallback_chain=("sycophant", "echo"),
    )
    router = ModelRouter(
        config=cfg,
        providers={"sycophant": SycophantProvider(), "echo": EchoProvider()},
    )

    chain = ReasoningChain(router=router)
    out = await chain.ask("anything")
    assert "great question" not in out.lower()
    assert "smart" not in out.lower()
```

This is wordier than the old test but expresses the contract precisely: a sycophant-providing router still gets its outbound filtered.

- [ ] **Step 5: Run target test file.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_orchestrator.py -v
```

Expected: all tests pass including the new `test_chain_accepts_router_argument`.

- [ ] **Step 6: Full suite + gates.**

Expected: **169 passed** (168 + 1 new). Mypy clean. Ruff clean.

- [ ] **Step 7: Commit.**

```bash
git add clawstu/orchestrator/chain.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): ReasoningChain takes ModelRouter instead of LLMProvider

Spec §4.2.3: ReasoningChain.__init__ now takes router: ModelRouter.
run_template and ask accept an optional task_kind: TaskKind argument
(defaults to SOCRATIC_DIALOGUE) and resolve the provider + model
via router.for_task(task_kind) on each call.

The per-call model parameter is passed through to provider.complete,
respecting the per-TaskKind model selection from AppConfig.task_routing.

Existing tests migrated:
- test_chain_runs_template_and_returns_text: now constructs
  ReasoningChain(router=async_router_for_testing()).
- test_chain_rewrites_outbound_sycophancy: builds an explicit
  ModelRouter with a SycophantProvider registered and fallback
  chain overridden to (sycophant, echo).

Test count: 169 passed."
```

---

## Task 9: Flip `LiveContentGenerator.__init__` to take `router: ModelRouter`

**Files:**
- Modify: `clawstu/curriculum/live_generator.py`
- Create: `tests/test_live_content.py` (new test file — Phase 1 didn't have one because the module was omitted from coverage)
- Modify: `pyproject.toml` (remove the omit for the old live_generator.py path; Task 10 will re-add it for the new location — but wait, we're moving in Task 10, so the omit stays during Task 9 and gets updated in Task 10)

**Rationale:** Same pattern as Task 8 for ReasoningChain. The generator takes a router and resolves per-method TaskKinds: `generate_pathway` → PATHWAY_PLANNING, `generate_block` → BLOCK_GENERATION, `generate_check` → CHECK_GENERATION. `_ask_json` takes an explicit `task_kind` argument.

- [ ] **Step 1: Create `tests/test_live_content.py`.**

```python
"""LiveContentGenerator — Phase 2 router-based tests.

These tests exercise the EchoProvider offline fallback path, which
lets us verify the generator's full contract without a network. The
LLM-backed path (production providers) is tested by the provider-
specific test files (test_provider_ollama etc.) — LiveContentGenerator
just glues prompts + the router together.
"""
from __future__ import annotations

import pytest

from clawstu.assessment.generator import AssessmentType
from clawstu.curriculum.live_generator import LiveContentGenerator
from clawstu.curriculum.topic import Topic
from clawstu.profile.model import AgeBracket, ComplexityTier, Domain, Modality
from tests.conftest import async_router_for_testing


@pytest.fixture
def topic() -> Topic:
    return Topic.from_student_input(
        "The French Revolution", domain=Domain.GLOBAL_HISTORY
    )


async def test_generate_pathway_returns_concepts(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    pathway = await gen.generate_pathway(
        topic=topic, age_bracket=AgeBracket.MIDDLE, max_concepts=3
    )
    assert len(pathway) == 3
    assert all(isinstance(c, str) and c for c in pathway)


async def test_generate_block_returns_learning_block(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    block = await gen.generate_block(
        topic=topic,
        concept="french_revolution_overview",
        modality=Modality.TEXT_READING,
        tier=ComplexityTier.MEETING,
        age_bracket=AgeBracket.MIDDLE,
    )
    assert block.title
    assert block.body
    assert block.estimated_minutes > 0
    assert block.domain is Domain.GLOBAL_HISTORY


async def test_generate_check_returns_crq(topic: Topic) -> None:
    gen = LiveContentGenerator(router=async_router_for_testing())
    check = await gen.generate_check(
        topic=topic,
        concept="french_revolution_overview",
        tier=ComplexityTier.MEETING,
        modality=Modality.TEXT_READING,
        age_bracket=AgeBracket.MIDDLE,
    )
    # The offline stub returns a crq by default.
    assert check.type is AssessmentType.CRQ
    assert check.prompt
    assert check.rubric is not None and len(check.rubric) >= 1
```

- [ ] **Step 2: Run and confirm tests fail.**

Expected: `TypeError: LiveContentGenerator.__init__() got an unexpected keyword argument 'router'`.

- [ ] **Step 3: Flip `LiveContentGenerator.__init__` in `clawstu/curriculum/live_generator.py`.**

Edit `clawstu/curriculum/live_generator.py`:

Add imports:
```python
from clawstu.orchestrator.router import ModelRouter
from clawstu.orchestrator.task_kinds import TaskKind
```

Keep the existing `providers` import line. `LLMProvider` stays imported because `_ask_json` takes it as an explicit parameter type now, and `EchoProvider`, `LLMMessage`, and `ProviderError` are all still used inside the class body.

Change `__init__`:
```python
def __init__(
    self,
    router: ModelRouter,
    *,
    safety: _SafetyGate | None = None,
) -> None:
    self._router = router
    self._safety = safety or _SafetyGate()
```

**Note on the EchoProvider offline stub:** the generator currently does `isinstance(self._provider, EchoProvider)` to decide whether to use the offline stub. After the router flip, we need to check whether the provider that the router returns for the current task is Echo. The cleanest way is to resolve at the top of each `generate_*` method and pass the resolved provider to `_ask_json`:

```python
async def generate_pathway(
    self,
    *,
    topic: Topic,
    age_bracket: AgeBracket,
    max_concepts: int = 4,
) -> tuple[str, ...]:
    provider, model = self._router.for_task(TaskKind.PATHWAY_PLANNING)
    if isinstance(provider, EchoProvider):
        concepts = _offline_pathway(topic)[:max_concepts]
    else:
        user = (
            f"Student topic: {topic.raw}\n"
            f"Age bracket: {age_bracket.value}\n"
            f"Maximum concepts: {max_concepts}"
        )
        payload = await self._ask_json(
            system=_PATHWAY_SYSTEM,
            user=user,
            provider=provider,
            model=model,
        )
        raw_concepts = payload.get("concepts")
        if not isinstance(raw_concepts, list) or not raw_concepts:
            raise LiveGenerationError(
                f"pathway response missing 'concepts': {payload!r}"
            )
        concepts = [str(c) for c in raw_concepts][:max_concepts]

    if not concepts:
        raise LiveGenerationError("pathway generator produced no concepts")
    return tuple(concepts)
```

Similar edits for `generate_block` (uses `TaskKind.BLOCK_GENERATION`) and `generate_check` (uses `TaskKind.CHECK_GENERATION`).

Change `_ask_json` to take an explicit provider + model:

```python
async def _ask_json(
    self,
    *,
    system: str,
    user: str,
    provider: LLMProvider,
    model: str,
) -> dict[str, Any]:
    """Ask the provided provider for a JSON object and parse it strictly."""
    try:
        response = await provider.complete(
            system=system,
            messages=[LLMMessage(role="user", content=user)],
            model=model,
        )
    except ProviderError as exc:
        raise LiveGenerationError(f"provider failed: {exc}") from exc
    # ...rest of body unchanged
```

**Re-import `LLMProvider`** at the top since we now reference it as a parameter type on `_ask_json`.

- [ ] **Step 4: Run the new test file.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_live_content.py -v
```

Expected: **3 passed.**

- [ ] **Step 5: Full suite + gates.**

Expected: **172 passed** (169 + 3). Mypy clean. Ruff clean.

- [ ] **Step 6: Remove the coverage omit entry for live_generator.py.**

Edit `pyproject.toml`. The current omit block is:
```toml
[tool.coverage.run]
branch = true
source = ["clawstu"]
omit = [
    # live_generator.py is LLM-backed and will be relocated to
    # clawstu/orchestrator/live_content.py in Phase 2 (per
    # docs/superpowers/specs/2026-04-11-claw-stu-providers-memory-proactive-design.md
    # §4.1). Its tests land in that phase against the new location.
    "clawstu/curriculum/live_generator.py",
]
```

Since we just added tests that cover the module, the omit entry can be removed entirely. **BUT** — the file is going to move in Task 10, so removing the omit now creates a short-lived gap. Better: keep the omit during Task 9, and remove+update in Task 10 when the relocation happens.

**Decision:** leave the omit alone in this task. Task 10 handles it.

- [ ] **Step 7: Verify coverage is still above 80% with the omit in place.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest --cov=clawstu --cov-report=term 2>&1 | tail -5
```

Expected: `Required test coverage of 80.0% reached.` with total around 85%+.

- [ ] **Step 8: Commit.**

```bash
git add clawstu/curriculum/live_generator.py tests/test_live_content.py
git commit -m "feat(curriculum): LiveContentGenerator takes ModelRouter

Spec §4.2.3 + §4.4.1: the generator now resolves per-method TaskKinds
via the router. generate_pathway uses PATHWAY_PLANNING, generate_block
uses BLOCK_GENERATION, generate_check uses CHECK_GENERATION. _ask_json
takes an explicit provider + model pair so the task->provider mapping
is decided at the top of each generate_* method.

The offline EchoProvider fallback still works: isinstance check on
the router-resolved provider picks up Echo automatically. Tests
use async_router_for_testing() which collapses to Echo by default,
so the offline path is exercised end-to-end without a network.

tests/test_live_content.py is new — Phase 1 had no tests for
live_generator.py because it was omitted from coverage pending this
relocation. The 3 new tests cover the three generate_* methods.

Test count: 172 passed."
```

---

## Task 10: Move `clawstu/curriculum/live_generator.py` → `clawstu/orchestrator/live_content.py`

**Files:**
- Rename: `clawstu/curriculum/live_generator.py` → `clawstu/orchestrator/live_content.py`
- Modify: `clawstu/orchestrator/__init__.py` (add re-export)
- Modify: `clawstu/curriculum/__init__.py` (remove any live_generator re-export — Phase 1 review confirmed there wasn't one, but double-check)
- Modify: `tests/test_live_content.py` (update import)
- Modify: `pyproject.toml` (remove the old coverage omit, which is no longer needed now that tests exist)

**Rationale:** Spec §4.1 "B2 fix" — `curriculum` is a lower layer than `orchestrator`, so having `curriculum/live_generator.py` import from `clawstu.orchestrator.providers` is a layering violation. Moving it to `clawstu/orchestrator/live_content.py` fixes the hierarchy.

- [ ] **Step 1: Physical move via `git mv`.**

```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
git mv clawstu/curriculum/live_generator.py clawstu/orchestrator/live_content.py
```

- [ ] **Step 2: Update the import in `tests/test_live_content.py`.**

Change:
```python
from clawstu.curriculum.live_generator import LiveContentGenerator
```
to:
```python
from clawstu.orchestrator.live_content import LiveContentGenerator
```

- [ ] **Step 3: Update `clawstu/orchestrator/__init__.py` to export `LiveContentGenerator`.**

Add `from clawstu.orchestrator.live_content import LiveContentGenerator, LiveGenerationError` and add both to `__all__`.

Also remove any reference to these in `clawstu/curriculum/__init__.py` (verify with grep; Phase 1 review confirmed none exist, but double-check).

- [ ] **Step 4: Check for internal imports inside the moved file.**

The moved file still imports from `clawstu.curriculum.content` (`LearningBlock`), `clawstu.curriculum.topic` (`Topic`), and `clawstu.assessment.generator` (`AssessmentItem`, `AssessmentType`). These are all "orchestrator imports from a lower layer" which the §4.1 DAG allows for orchestrator targeting curriculum and assessment (see Task 11's `_ALLOWED` table — it's the authoritative layer table for this phase and it explicitly includes both `"curriculum"` and `"assessment"` under `"orchestrator"`'s allowed set).

**Note on spec §4.1 prose wording:** spec §4.1 point 7 reads "`orchestrator` imports from `safety`, `profile`, `memory`, `curriculum`" and does not literally list `assessment`, but the moved file needs `AssessmentItem` as a return type from `generate_check`, and Task 11's hierarchy table correctly includes assessment. Treat the Task 11 `_ALLOWED` table as authoritative. File a spec erratum in a follow-up task.

Verify the actual imports:
```bash
grep -n "^from clawstu\|^import clawstu" clawstu/orchestrator/live_content.py
```

Expected imports (all legal per Task 11's `_ALLOWED` table):
- `clawstu.assessment.generator` (AssessmentItem, AssessmentType)
- `clawstu.curriculum.content` (LearningBlock)
- `clawstu.curriculum.topic` (Topic)
- `clawstu.orchestrator.providers` — same layer, fine
- `clawstu.orchestrator.router`, `clawstu.orchestrator.task_kinds` — same layer, fine
- `clawstu.profile.model`
- `clawstu.safety.boundaries`, `clawstu.safety.content_filter`

If any import is outside this list, it's a layering violation. Flag and fix before Task 11 runs.

- [ ] **Step 5: Update `pyproject.toml` coverage omit.**

Remove the `"clawstu/curriculum/live_generator.py"` entry from `[tool.coverage.run] omit` since:
1. The file no longer exists under that path.
2. The moved file `clawstu/orchestrator/live_content.py` now has tests (`tests/test_live_content.py`).

The resulting omit block should be empty or removed entirely. Keep the bracket structure:
```toml
[tool.coverage.run]
branch = true
source = ["clawstu"]
```

(No `omit` line needed if there's nothing to omit.)

- [ ] **Step 6: Run the migrated tests.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_live_content.py -v
```

Expected: **3 passed.**

- [ ] **Step 7: Full suite + gates.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest -q
/tmp/claw-stu-venv/bin/python -m mypy clawstu
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
```

Expected: **172 passed**. Mypy clean. Ruff clean.

**If mypy flags a circular import** (`clawstu.orchestrator.live_content` → `clawstu.curriculum.content` → `clawstu.orchestrator.*`), that's a sign of a hidden back-edge. Fix with a `TYPE_CHECKING` guard on the curriculum side or by restructuring the imports.

- [ ] **Step 8: Verify coverage is still healthy without the omit.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest --cov=clawstu --cov-report=term 2>&1 | grep -E "live_content|TOTAL"
```

Expected: `live_content.py` has some coverage (the 3 new tests exercise the `generate_*` methods via the Echo path) and TOTAL is ≥80%. The LLM-backed branches inside each `generate_*` are still uncovered but those are deferred to Phase 5 when mocked providers drive the tests.

**If coverage drops below 80%,** STOP. You may need to either:
(a) add more tests to `tests/test_live_content.py`, or
(b) re-add a narrow omit pattern that excludes only the LLM-backed branches (ugly — prefer option a), or
(c) lower the coverage floor (not recommended).

- [ ] **Step 9: Commit.**

```bash
git mv-add (already done via git mv)
git add clawstu/orchestrator/__init__.py clawstu/orchestrator/live_content.py tests/test_live_content.py pyproject.toml
git commit -m "refactor: move LiveContentGenerator curriculum -> orchestrator (§4.1 B2 fix)

Spec §4.1: curriculum must not import from orchestrator. Moving
LiveContentGenerator to clawstu/orchestrator/live_content.py fixes
the layering violation (curriculum.live_generator was importing
clawstu.orchestrator.providers, reversing the DAG).

Pure rename + re-export from clawstu.orchestrator.__init__. The
class body is unchanged from Task 9. Coverage omit entry removed
because tests/test_live_content.py now exercises the module.

Test count: 172 passed. mypy --strict clean. Ruff clean.
Coverage still >= 80%."
```

---

## Task 11: Add `tests/test_hierarchy.py` — AST-based import DAG guard

**Files:**
- Create: `tests/test_hierarchy.py`

**Rationale:** Spec §4.1 defines the authoritative import DAG. A machine-enforced check prevents any future phase from accidentally violating it. Uses `ast.parse` + `ast.walk` to extract every `from clawstu.X import ...` and `import clawstu.X` statement, then asserts the source layer's allowed-import set contains the target layer.

- [ ] **Step 1: Write the test.**

Create `tests/test_hierarchy.py`:

```python
"""Import DAG guard — enforces spec §4.1 layering across clawstu/.

Every import statement inside `clawstu/` is parsed via ast.parse and
checked against the authoritative layer dependency table below. A
violation in ANY file (existing or future) fails this test, catching
layer leaks at commit time.

Layer dependency table (authoritative, matches spec §4.1):

    Layer           Allowed import targets
    safety          stdlib, pydantic
    profile         stdlib, pydantic, safety
    memory          stdlib, pydantic, safety, profile
    curriculum      stdlib, pydantic, safety, profile, memory
    assessment      stdlib, pydantic, safety, profile, memory
    engagement      stdlib, pydantic, safety, profile, memory,
                    curriculum, assessment
    orchestrator    stdlib, pydantic, safety, profile, memory,
                    curriculum, assessment
    persistence     stdlib, pydantic
    api             any of the above
    scheduler       stdlib, pydantic, orchestrator, memory,
                    persistence, engagement

`cli` is an `api`-like top layer and may import from everything.
"""
from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterable

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CLAWSTU = _REPO_ROOT / "clawstu"

# Layer -> set of allowed layer targets.
_ALLOWED: dict[str, frozenset[str]] = {
    "safety": frozenset(),
    "profile": frozenset({"safety"}),
    "memory": frozenset({"safety", "profile"}),
    "curriculum": frozenset({"safety", "profile", "memory"}),
    "assessment": frozenset({"safety", "profile", "memory"}),
    "engagement": frozenset(
        {"safety", "profile", "memory", "curriculum", "assessment"}
    ),
    "orchestrator": frozenset(
        {"safety", "profile", "memory", "curriculum", "assessment"}
    ),
    "persistence": frozenset(),
    "api": frozenset(
        {
            "safety",
            "profile",
            "memory",
            "curriculum",
            "assessment",
            "engagement",
            "orchestrator",
            "persistence",
        }
    ),
    "scheduler": frozenset(
        {"orchestrator", "memory", "persistence", "engagement"}
    ),
    # cli is effectively api-layer (top); allow everything.
    "_cli": frozenset(
        {
            "safety",
            "profile",
            "memory",
            "curriculum",
            "assessment",
            "engagement",
            "orchestrator",
            "persistence",
            "api",
            "scheduler",
        }
    ),
}


def _layer_of(relpath: pathlib.Path) -> str:
    """Given a path relative to clawstu/, return its layer name.

    clawstu/orchestrator/config.py -> "orchestrator"
    clawstu/cli.py                 -> "_cli"
    """
    parts = relpath.parts
    if parts[0] == "cli.py":
        return "_cli"
    if len(parts) < 2:
        return parts[0].replace(".py", "")
    return parts[0]


def _iter_clawstu_imports(tree: ast.AST) -> Iterable[str]:
    """Yield target layers imported from this AST."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.startswith("clawstu.") or mod == "clawstu":
                rest = mod[len("clawstu.") :] if mod != "clawstu" else ""
                yield rest.split(".")[0] if rest else ""
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("clawstu.") or alias.name == "clawstu":
                    rest = (
                        alias.name[len("clawstu.") :]
                        if alias.name != "clawstu"
                        else ""
                    )
                    yield rest.split(".")[0] if rest else ""


def test_every_clawstu_import_respects_the_layering_dag() -> None:
    """For every .py under clawstu/, check its imports against _ALLOWED."""
    violations: list[str] = []
    for py_file in _CLAWSTU.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(_CLAWSTU)
        source_layer = _layer_of(rel)
        if source_layer not in _ALLOWED:
            # Unknown layer — skip (e.g., top-level __init__.py).
            continue
        allowed = _ALLOWED[source_layer]
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for target in _iter_clawstu_imports(tree):
            if not target:
                continue
            if target == source_layer:
                continue  # intra-layer imports are always fine
            if target not in allowed:
                violations.append(
                    f"{rel}: '{source_layer}' cannot import "
                    f"'clawstu.{target}' "
                    f"(allowed: {sorted(allowed)})"
                )
    assert not violations, (
        "Layering violations detected:\n  " + "\n  ".join(violations)
    )


def test_layer_dag_is_acyclic() -> None:
    """Sanity check the table itself has no cycles."""
    def _reaches(start: str, target: str, seen: set[str] | None = None) -> bool:
        seen = seen or set()
        if start in seen:
            return False
        seen.add(start)
        for next_layer in _ALLOWED.get(start, frozenset()):
            if next_layer == target:
                return True
            if _reaches(next_layer, target, seen):
                return True
        return False

    for layer in _ALLOWED:
        assert not _reaches(layer, layer), f"cycle detected at layer {layer}"
```

- [ ] **Step 2: Run it.**

```bash
/tmp/claw-stu-venv/bin/python -m pytest tests/test_hierarchy.py -v
```

Expected: **2 passed.**

**If there are violations:** the test will list them. Each violation points at a real layering bug. Fix it before proceeding (the Task 10 move should have fixed the only known one — `curriculum` importing `orchestrator`).

- [ ] **Step 3: Full suite + gates.**

Expected: **174 passed** (172 + 2 new). Mypy clean. Ruff clean.

- [ ] **Step 4: Commit.**

```bash
git add tests/test_hierarchy.py
git commit -m "test(hierarchy): AST-based import DAG guard (spec §4.1)

Walks every .py under clawstu/ with ast.parse, extracts all
'from clawstu.X import ...' statements, and asserts each target
layer is in the source layer's _ALLOWED set. The _ALLOWED table
mirrors the spec §4.1 authoritative DAG.

Also asserts the _ALLOWED table itself is acyclic as a
sanity check.

Catches layering violations at commit time. The Task 10 move of
live_generator.py from curriculum -> orchestrator was the only
known violation before this guard existed; running this test
against pre-Task-10 code would have caught it mechanically.

Test count: 174 passed."
```

---

## Task 12: Final regression + push + CI verification

**Files:** none modified.

- [ ] **Step 1: Full test run with coverage.**

```bash
cd /Users/mind_uploaded_crustacean/Projects/Claw-STU
/tmp/claw-stu-venv/bin/python -m pytest --cov=clawstu --cov-report=term
```

Expected:
- **174 tests passing** (counting baseline 156 + 18 new from Tasks 1-11: 1 + 1 + 1 + 1 + 1 + 7 + 1 + 3 + 2 = 18).
- **Coverage ≥ 80%**, ideally higher than the 85% Phase-1 baseline because `live_content.py` is now tested.
- Runtime under 3 seconds.

Record the actual count. If anything is off, diagnose before pushing.

- [ ] **Step 2: Lint + type check.**

```bash
/tmp/claw-stu-venv/bin/python -m ruff check clawstu tests
/tmp/claw-stu-venv/bin/python -m mypy clawstu
```

Expected: both clean on all ~45 source files.

- [ ] **Step 3: Verify the installed CLI still works.**

```bash
/tmp/claw-stu-venv/bin/clawstu --help
/tmp/claw-stu-venv/bin/clawstu doctor
```

Expected: help text + config summary. Both commands should still work — neither one went async in Phase 2, they're sync wrappers.

- [ ] **Step 4: Verify the import DAG guard catches the known-old violation** (sanity check).

```bash
# Temporarily create a violation and confirm the test catches it.
echo "from clawstu.orchestrator.providers import EchoProvider" >> clawstu/safety/boundaries.py
/tmp/claw-stu-venv/bin/python -m pytest tests/test_hierarchy.py -v 2>&1 | tail -15
# Expected: FAIL with a violation message
git checkout clawstu/safety/boundaries.py
/tmp/claw-stu-venv/bin/python -m pytest tests/test_hierarchy.py -v 2>&1 | tail -5
# Expected: 2 passed
```

This proves the test actually works. If the temporary violation doesn't trigger a failure, the test is broken and needs to be fixed.

- [ ] **Step 5: Phase 2 boundary marker commit.**

```bash
git commit --allow-empty -m "chore: Phase 2 complete — router + async migration + live-content relocation

Cumulative changes since the Phase 2 start:
- clawstu/orchestrator/providers.py: LLMProvider.complete Protocol and
  EchoProvider.complete flipped to async def
- clawstu/orchestrator/provider_ollama.py: httpx.Client -> httpx.AsyncClient
  + async def on complete and _post, await on every outgoing call
- clawstu/orchestrator/provider_anthropic.py: same
- clawstu/orchestrator/provider_openai.py: same
- clawstu/orchestrator/provider_openrouter.py: same
- clawstu/orchestrator/chain.py: ReasoningChain takes ModelRouter, both
  methods are async def, resolve provider+model via router.for_task
- clawstu/orchestrator/router.py: NEW — ModelRouter with fallback chain,
  guaranteed EchoProvider floor, RouterConstructionError for empty cases
- clawstu/orchestrator/live_content.py: MOVED from curriculum/live_generator.py
  per spec §4.1 B2 fix, flipped to async, takes ModelRouter
- clawstu/orchestrator/__init__.py: exports ModelRouter +
  LiveContentGenerator + LiveGenerationError from new location
- tests/test_router.py: NEW — 7 tests covering resolution, fallback, floor
- tests/test_live_content.py: NEW — 3 tests covering generate_* methods
- tests/test_hierarchy.py: NEW — AST-based §4.1 import DAG guard,
  2 tests (one for actual violations, one for DAG acyclicity)
- tests/conftest.py: async_router_for_testing helper
- tests/test_orchestrator.py: existing tests flipped to async def + await,
  ReasoningChain construction migrated to router, new SycophantProvider
  variant uses an explicit ModelRouter with fallback override
- tests/test_provider_{ollama,anthropic,openai,openrouter}.py: all flipped
  to async def test_* + await + httpx.AsyncClient
- pyproject.toml: coverage omit entry for live_generator.py removed
  (the file is gone; tests exist for the new location)

SessionRunner and api/session.py handlers remain sync. The async
cascade into session + API handlers is a Phase 5 concern, when live
content actually wires into the session loop.

Test count: 174 passing (up from 156 Phase-1 baseline, +18 new).
Coverage: XX% (was 85.52%). Ruff clean. mypy --strict clean on all
source files. Runtime: under 3 seconds for the full suite.
Zero # type: ignore comments in shipped code."
```

- [ ] **Step 6: Push.**

```bash
git push origin main
```

- [ ] **Step 7: Verify CI goes green.**

```bash
sleep 45 && gh run list --limit 1
```

Expected: `completed  success  chore: Phase 2 complete ...` on main.

If CI fails, diagnose via `gh run view <run_id> --log-failed | tail -80`. The most likely failure modes:
- Python 3.11 async behavior diff (CI runs 3.11 + 3.12 matrix)
- pytest-asyncio version mismatch between local venv and CI's fresh install
- Coverage floor regression if any file dropped below expected

Fix forward with a new commit; do NOT claim Phase 2 done until CI is green.

---

## Post-phase checklist

- [ ] All 12 task blocks have their checkboxes checked.
- [ ] `pytest -q` passes in under 3 seconds.
- [ ] Coverage is ≥ 80% (ideally higher than Phase 1's 85.52% because live_content.py is now tested).
- [ ] `ruff check clawstu tests` is clean.
- [ ] `mypy clawstu` is clean on all source files.
- [ ] `clawstu --help` and `clawstu doctor` still work from the installed editable.
- [ ] `tests/test_hierarchy.py` passes (both the violation check AND the acyclicity check).
- [ ] `from clawstu.orchestrator import ModelRouter, LiveContentGenerator` works.
- [ ] No `# type: ignore` comments added in this phase (preserve the Phase 1 invariant).
- [ ] CI is green on the latest `main` commit (Python 3.11 + 3.12 matrix).
- [ ] Phase 2 commit boundary marker on `main`.

## Known deferrals (documented for Phase 3+)

- **`SessionRunner` stays sync.** The runner does not call the orchestrator in Phase 1 or Phase 2. Phase 5 flips it to async when it first calls `LiveContentGenerator` for a free-text topic.
- **`api/session.py` handlers stay sync.** Same reason — they only delegate to the sync runner. Phase 5 flips them.
- **`SessionRunner` does not yet accept a `ModelRouter | None`.** That's a Phase 5 addition when the runner needs a router for its first `LiveContentGenerator` call.
- **`doctor --ping` still prints `DEFERRED`.** Phase 2 does NOT wire real reachability checks into doctor. The router's fallback-chain-by-presence approach is sufficient for now; real network probing is a separate concern. A future task (Phase 2.5 or Phase 3 extension) will add an async probe loop in `doctor` that calls each configured provider's `.complete()` with a tiny test prompt and logs the result.
- **No retries.** The spec says "Retries are handled by ModelRouter, not the provider itself." Phase 2 implements the router but not the retry policy. Retry-on-ProviderError-with-backoff lands in Phase 2.5 or Phase 6 when the scheduler needs it.
- **Scheduler task signatures (`Callable[..., Awaitable[TaskReport]]`)** are not defined in Phase 2. Scheduler lands in Phase 6.

## What makes this plan different from Phase 1

Phase 1 was additive: new modules, new tests, new CLI. Phase 2 is **rewriting the existing orchestrator layer in place** while keeping the test suite green. That requires atomic commits for the async flip (Task 1 touches 4 production files + 1 test file), careful mypy protocol reasoning for the mid-task intermediate state (Task 1 leaves the 4 network providers structurally non-compliant until Tasks 2-5 finish), and strict adherence to the topological order: providers → chain/live_content → router → chain-with-router → relocation.

The `test_hierarchy.py` guard (Task 11) is a permanent investment: every phase after this one will benefit from machine-enforced layering.
