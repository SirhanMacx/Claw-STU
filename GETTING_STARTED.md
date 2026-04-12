# Getting Started in 5 Minutes

No technical background needed. If you can install a Python package, you can run Stuart.

## 1. Install (1 minute)

Open your terminal and run:

```bash
pip install clawstu
```

Requires Python 3.11 or later.

## 2. First Run (1 minute)

```bash
clawstu setup
```

Stuart walks you through setup:

- **Pick a provider**: Ollama (free, runs locally), Anthropic, OpenAI, or OpenRouter.
- **Enter your API key**: One time only. Stored in `~/.claw-stu/secrets.json` with restricted file permissions.

The easiest free path is local Ollama:

```bash
brew install ollama
ollama pull llama3.2
clawstu setup   # pick "ollama"
```

For higher-quality output, use an Anthropic or OpenAI API key (pay per use).

## 3. Start a Learning Session (2 minutes)

```bash
clawstu learn
```

Stuart asks your name, age, and what you want to learn. Then it runs one adaptive session:

1. **Calibrate** -- 3-5 diagnostic questions to figure out what you already know.
2. **Teach** -- one focused learning block, adapted to your level.
3. **Check** -- a constructed-response question (not multiple choice).
4. **Adapt** -- advance, re-teach via a different approach, or deepen with extension material.
5. **Close** -- a summary and an updated learner profile.

The next time you show up, Stuart remembers what you knew and what was shaky.

## 4. Check Your Progress

```bash
clawstu progress       # ZPD per domain, modality mix, session count
clawstu history        # list of past sessions
clawstu review         # concepts due for spaced review
```

## 5. Ask a Quick Question

```bash
clawstu ask "What caused the French Revolution?"
```

One-shot Socratic answer outside of a structured session. If you have a learner profile, Stuart adapts the answer to your level.

## 6. Start the Web API (Optional)

```bash
clawstu serve
```

Opens a FastAPI server at `http://localhost:8000` with interactive API docs at `/docs` and a web UI at the root. The embedded scheduler runs overnight tasks (dream cycle, spaced review, ZPD refresh) in the same process.

## 7. Self-Diagnosis

```bash
clawstu doctor          # check config, providers, SQLite, embeddings
clawstu doctor --ping   # also test provider reachability
```

---

## What's Next?

- **Export your profile**: `clawstu profile export <name> --out profile.tar.gz`
- **Import on another machine**: `clawstu profile import profile.tar.gz`
- **Read your concept wiki**: `clawstu wiki <concept>`
- **Resume a warm-start session**: `clawstu resume <name>`

## Need Help?

- [FEATURES.md](FEATURES.md) -- what Stuart can do
- [SECURITY.md](SECURITY.md) -- privacy and data handling
- [SOUL.md](SOUL.md) -- Stuart's identity and behavioral constraints
- [GitHub Issues](https://github.com/SirhanMacx/Claw-STU/issues)
- [GitHub Discussions](https://github.com/SirhanMacx/Claw-STU/discussions)
