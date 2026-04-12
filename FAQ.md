# Claw-STU FAQ

Frequently asked questions from learners and parents.

---

## Does it work offline?

Yes. If you use a local LLM through Ollama, Stuart runs entirely on your machine with no internet connection required. Install Ollama, pull a model, set your provider to `ollama` in setup, and everything works offline.

Cloud providers (Anthropic, OpenAI, OpenRouter) require internet access to reach their APIs, but all your data still stays local.

---

## Is my data private?

Yes. Stuart is local-first by design:

- Your learner profile, brain pages, and session history live in `~/.claw-stu/` on your machine.
- API keys are stored with owner-only file permissions.
- Nothing is uploaded to any server -- there are no Claw-STU servers.
- The only external network calls go to the LLM provider you choose, and only the prompt text is sent.
- No telemetry, no tracking, no data collection.

For full details, see [SECURITY.md](SECURITY.md).

---

## How much does it cost?

Stuart itself is free and open-source. The only cost is the LLM provider you choose:

| Provider | Cost | Notes |
|----------|------|-------|
| **Ollama** (local) | Hardware only | Runs on your own machine. 16 GB+ RAM recommended. |
| **Anthropic** (Claude) | Pay-per-use | Highest quality. A typical session costs a few cents. |
| **OpenAI** (GPT-4o) | Pay-per-use | Similar pricing. Free tier available with rate limits. |
| **OpenRouter** | Pay-per-use | Access to many models through one API key. |

---

## What topics can it teach?

Anything. Stuart generates learning content on any topic -- history, science, math, language, philosophy, art, technology, and more. The quality depends on the underlying LLM, but the adaptive loop (calibrate, teach, check, adapt) works for any subject.

Stuart ships with seed content for US History (Declaration of Independence) for testing and demos, but the live content generator handles any topic.

---

## How does it know my level?

Stuart observes. It never asks you to self-report your learning style or skill level. Instead:

- **Calibration questions** at the start of each session test what you already know.
- **Response accuracy** on check-for-understanding questions determines your complexity tier.
- **Response timing** provides signals about confidence and engagement.
- **Modality success rates** track which teaching approaches work for you.
- **Misconception tracking** records specific concepts you got wrong and monitors improvement over time.

All of this is stored in your learner profile, which grows across sessions.

---

## What's a "modality"?

A teaching approach. Stuart uses seven:

1. **Text reading** -- structured text explanation
2. **Primary source** -- analysis of original documents, data, or artifacts
3. **Socratic dialogue** -- guided questioning that leads you to the answer
4. **Interactive scenario** -- role-play, simulation, or decision-making exercise
5. **Visual/spatial** -- diagrams, maps, timelines, spatial reasoning
6. **Worked example** -- step-by-step solution walkthrough
7. **Inquiry/project** -- open-ended investigation or creative task

When you get a check wrong, Stuart re-teaches using a different modality than the one that failed. This is a foundational invariant tested in the codebase.

---

## Can I export my data?

Yes. Your profile is portable and owned by you:

```bash
clawstu profile export <name> --out profile.tar.gz
```

This creates a tarball with your learner profile and brain pages. Import it on another machine:

```bash
clawstu profile import profile.tar.gz
```

You can also delete your data at any time by removing `~/.claw-stu/`.

---

## Is it safe for kids?

Stuart has safety built in at every layer:

- **Age-appropriate content filter** -- deterministic keyword blocklist applied on every outbound string, calibrated by age bracket.
- **Crisis detection** -- if a student expresses self-harm, abuse, or acute distress, Stuart immediately pauses the session and surfaces crisis resources (988 Suicide & Crisis Lifeline, Crisis Text Line, Childhelp National Child Abuse Hotline).
- **Boundary enforcement** -- Stuart does not say "I'm proud of you" or "I'm worried about you." It does not simulate emotional intimacy.
- **Inbound safety gate** -- every student text entry is scanned before processing.

Stuart is a cognitive tool, not a friend, therapist, or authority figure.

---

## What models work best?

| Model | Provider | Quality | Best For |
|-------|----------|---------|----------|
| Claude Sonnet | Anthropic | Highest | Best overall quality, nuanced explanations |
| GPT-4o | OpenAI | Very Good | Reliable, widely available |
| Llama 3.2 | Ollama (local) | Good | Free, runs offline, lighter hardware |

Start with Claude or GPT-4o for the best experience. Switch to a local model once you are comfortable and want to eliminate API costs.

---

## How do I update?

```bash
pip install --upgrade clawstu
```

Your data and configuration are preserved across updates.

---

## Where do I get help?

- [Getting Started](GETTING_STARTED.md) -- first-time setup
- [Features](FEATURES.md) -- what Stuart can do
- [Security](SECURITY.md) -- privacy and data handling
- [GitHub Issues](https://github.com/SirhanMacx/Claw-STU/issues) -- report bugs
- [GitHub Discussions](https://github.com/SirhanMacx/Claw-STU/discussions) -- ask questions

---
