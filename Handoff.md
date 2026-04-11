Claw-STU: Vision & Handoff Document
Author: SirhanMacx
Date: April 2026
Status: Pre-development — Vision & Architecture
Sister Project: Claw-ED (teacher-facing agent)
What This Document Is
This is a handoff document for initializing Claw-STU development via Claude Code. It
describes the vision, pedagogical philosophy, architectural approach, and minimum viable
product for a new open-source project. The developer (human or AI) reading this should be
able to understand why this project exists, what it does, and how to begin building it.
The Problem
The traditional education pipeline — K-12 → college → career → taxpayer — is structurally
dependent on the existence of jobs at the end. As AI systems increasingly perform
knowledge work at or above human capability, this pipeline is breaking. The institution of
school, as currently designed, is a career-preparation system for careers that may not exist
within a decade.
Meanwhile, the craft of education — teaching humans how to think, reason, evaluate
evidence, tolerate ambiguity, and adapt to novel situations — has never been more
important. The gap between “school” and “education” is about to become the central
design problem of the 21st century.
Claw-STU exists to serve the learner directly, independent of any institution. It is not a
tutoring bot. It is not a content delivery system. It is a personal learning agent that
understands how an individual student learns and adapts to them continuously.
The Name
Claw-STU — the student-facing counterpart to Claw-ED (the teacher-facing agent)
Stuart — the friendly name / persona of the agent
STU — backronym TBD (Student Thinking Utility, Student Tutoring Unit, etc.)
Dimension Claw-ED Claw-STU
User Teacher Student
Core model Pedagogical fingerprint Learner profile
Input Curriculum files, lesson
plans
Student interactions, responses,
preferences
Output Lessons in teacher’s voice Personalized learning pathways
Design goal Amplify the teacher Grow with the student
Institutional
dependency
Moderate (aligned to
standards) None (portable, personal)
Relationship to Claw-ED
Claw-ED ingests a teacher’s curriculum files, extracts a pedagogical fingerprint, and
generates lessons in that teacher’s voice. It answers the question: “How does this teacher
teach?”
Claw-STU inverts this. It observes a student’s interactions, builds a learner profile, and
delivers instruction calibrated to that student’s patterns. It answers the question: “How does
this student learn?”
Claw-ED’s architecture (FastAPI, three-document lesson bundle, SOUL.md identity system,
LLM orchestration) serves as a blueprint, not a codebase to fork. Claw-STU should learn
from Claw-ED’s strengths and avoid its known issues (swallowed exceptions, circular
imports, oversized functions identified in the technical audit).
Pedagogical Philosophy
These principles come from nine years of classroom teaching (Global History I & II, US
History, grades 8–10) and are non-negotiable in the design:
1. Zone of Proximal Development (ZPD) — Always
Vygotsky’s ZPD is the core instructional principle. Claw-STU must always operate in the
space between what the student can do independently and what they can do with support.
Too easy = disengagement. Too hard = frustration and shutdown. The agent must
continuously calibrate.
2. Differentiation Is Not Optional
Students learn differently. This is not a platitude — it is an observable, measurable reality.
Claw-STU must support at minimum three tiers of complexity (approaching, meeting,
exceeding standard) and multiple modalities:
Text-based readings and primary source analysis
Interactive games and simulations
Video content (curated, not generated)
Visual/spatial tasks (timelines, maps, graphic organizers)
Discussion/Socratic dialogue
Project-based / inquiry-driven exploration
The student doesn’t choose their modality from a menu. The agent observes which
modalities produce engagement and comprehension, and adapts.
3. Check for Understanding — Then Proceed
No forward progress without verification. This mirrors the Danielson framework’s emphasis
on formative assessment. Claw-STU must:
Embed checks for understanding at natural breakpoints
Use varied assessment formats (not just multiple choice)
Distinguish between recall and understanding
Use CRQ-style (Constructed Response Question) formats that require evidence-based
reasoning
Never mistake “the student clicked through it” for “the student learned it”
4. Primary Sources Over Summaries
When dealing with history, social studies, humanities, or any domain where interpretation
matters, the agent should surface primary sources and teach the student to analyze them —
not just deliver pre-digested conclusions. The HAPP framework (Historical context,
Audience, Purpose, Point of view) is a strong default model for source analysis.
5. The Agent Is Not the Teacher
Claw-STU does not replace human relationships. It is a cognitive tool. It should never
simulate emotional intimacy, claim to care about the student, or position itself as a friend or
confidant. It is honest, helpful, and warm — but it is a tool. If a student expresses distress,
the agent surfaces appropriate human resources. Period.
The Learner Profile
The learner profile is Claw-STU’s equivalent of Claw-ED’s pedagogical fingerprint. It is the
core data model. It must capture:
Cognitive Patterns
Modality preferences — Does this student engage more deeply with text, visuals,
interactive elements, or dialogue? (Observed, not self-reported.)
Pacing — How quickly does the student move through new material? How much
repetition do they need?
Complexity tolerance — Where is their current ZPD boundary? How does it shift across
domains?
Error patterns — What kinds of mistakes does the student consistently make? Are they
conceptual, procedural, or attentional?
Scaffolding response — When the agent provides support, what kind of support
works? (Hints? Worked examples? Analogies? Reframing?)
Engagement Signals
Session duration and drop-off patterns — When do they lose focus?
Voluntary exploration — Do they follow tangents? Ask unprompted questions?
Challenge-seeking vs. challenge-avoidant — Do they lean into difficulty or retreat?
Response latency — How long do they think before answering? (Fast ≠ good. Slow ≠
bad.)
Knowledge State
Concept graph — What has the student demonstrated understanding of? What’s
shaky? What’s untouched?
Misconceptions — Actively tracked and flagged for targeted intervention
Transfer ability — Can the student apply a concept in a new context, or only in the
context where it was taught?
What the Profile Is NOT
It is not a gradebook
It is not a behavior tracker
It is not a diagnostic label
It is not shared with anyone without the student’s (and, for minors, guardian’s) explicit
consent
It is owned by the student, portable, exportable, and deletable
Guardrails
Claw-STU is designed for young learners. Safety is not a feature — it is the foundation.
Hard Constraints
Age-appropriate content only. The agent must maintain awareness of the learner’s
age and never surface content inappropriate for that age.
No emotional manipulation. The agent does not guilt, shame, pressure, or emotionally
coerce. Motivation is intrinsic, facilitated by appropriate challenge and genuine
progress.
No data exploitation. The learner profile exists to serve the learner. It is never sold,
shared with advertisers, or used for any purpose other than improving that student’s
learning experience.
No unsupervised contact simulation. The agent does not roleplay as a peer, friend,
romantic interest, or authority figure. It is a learning tool.
Mandatory human escalation. If a student expresses self-harm ideation, abuse, or
crisis, the agent immediately surfaces appropriate resources and does not attempt to
counsel.
Transparency. The student can always ask “why did you show me this?” and get an
honest answer about how the learner profile influenced the decision.
Soft Constraints
Encourage productive struggle, but recognize the line between struggle and frustration
Praise effort and strategy, not innate ability (growth mindset framing)
When the student is wrong, treat it as information, not failure
Periodic “meta-learning” moments: Help the student understand how they learn, not just
what they learn
Technical Architecture (Proposed)
Stack
Backend: FastAPI (consistent with Claw-ED, proven for LLM orchestration)
LLM integration: Modular provider interface (Anthropic, OpenAI, local models via
Ollama)
Learner profile storage: Local-first (SQLite or JSON), with optional encrypted sync
Frontend: Web-based, mobile-responsive (students are on phones and iPads)
Content generation: LLM-driven, but with human-curated source libraries and quality
filters
Assessment engine: Separate module for generating, administering, and evaluating
checks for understanding
Core Modules
claw-stu/
├── SOUL.md ├── HEARTBEAT.md # Agent identity and behavioral constraints
# Runtime health and self-monitoring
├── src/
│ ├── profile/ # Learner profile engine
│ │ ├── observer.py # Interaction analysis and pattern extraction
│ │ ├── model.py # Learner profile data structures
│ │ ├── zpd.py # Zone of proximal development calibration
│ │ └── export.py # Profile portability (export/import)
│ ├── curriculum/ # Content and pathway management
│ │ ├── pathway.py # Adaptive learning pathway generation
│ │ ├── content.py # Content selection and modality matching
│ │ ├── sources.py # Primary source library integration
│ │ └── standards.py # Optional standards alignment (NYS, Common Core, etc.)
│ ├── assessment/ # Check-for-understanding engine
│ │ ├── generator.py # Question/task generation
│ │ ├── evaluator.py # Response evaluation (not just right/wrong)
│ │ ├── crq.py # Constructed response question handling
│ │ └── feedback.py # Formative feedback generation
│ ├── engagement/ # Session management and engagement tracking
│ │ ├── session.py # Session lifecycle management
│ │ ├── signals.py # Engagement signal processing
│ │ └── modality.py # Modality selection and rotation
│ ├── safety/ # Guardrail enforcement
│ │ ├── content_filter.py # Age-appropriate content filtering
│ │ ├── escalation.py # Crisis detection and human escalation
│ │ └── boundaries.py # Interaction boundary enforcement
│ ├── orchestrator/ # LLM orchestration layer
│ │ ├── providers.py # Multi-provider LLM interface
│ │ ├── prompts.py # Prompt templates and management
│ │ └── chain.py # Multi-step reasoning chains
│ └── api/ # FastAPI routes
│ ├── session.py # Session endpoints
│ ├── profile.py # Learner profile endpoints
│ └── admin.py # Guardian/admin endpoints
├── tests/ # Test suite (aim for >80% coverage from day one)
├── docs/ # Documentation
└── frontend/ # Web frontend (React or similar)
Lessons from Claw-ED’s Audit
The Claw-ED technical audit revealed patterns to avoid:
No swallowed exceptions. Every error must be logged and handled explicitly.
No circular imports. Module dependencies must be strictly hierarchical.
Function size discipline. No function over ~50 lines. Break complex logic into
composable units.
Test-first development. Claw-ED’s high test coverage was a strength. Claw-STU
should match or exceed it.
Explicit over clever. Claw-ED’s three-document bundle pipeline worked because it was
straightforward. Resist the urge to over-architect.
Minimum Viable Product (MVP)
What Claw-STU Does on Day One for One Student
The MVP is a single learning session that adapts in real time.
1. 2. 3. 4. 5. 6. Onboarding: Student provides age and selects a topic of interest (or a specific
subject/standard). No login required for first use. Minimal friction.
Initial calibration: The agent presents a short, varied-format diagnostic (3–5 questions
across difficulty levels) to establish a rough ZPD baseline.
First learning block: Based on calibration, the agent delivers a ~10-minute learning
block in the modality most likely to engage. This could be:
A primary source with guided analysis questions
An interactive scenario or simulation prompt
A short reading with embedded comprehension checks
A Socratic dialogue where the agent asks questions and the student reasons
through them
Check for understanding: A CRQ-style assessment that requires the student to
construct a response, not just select an answer.
Adaptation: Based on the check, the agent either:
Advances to the next concept (student demonstrated understanding)
Re-teaches via a different modality (student struggled)
Deepens the current concept with extension material (student exceeded
expectations)
Session close: Brief summary of what was covered, what went well, what to revisit. The
learner profile is updated.
What it does NOT do in MVP:
Games or simulations (post-MVP feature)
Video integration (post-MVP)
Multi-subject support (start with one domain — US History or Global History)
Guardian dashboard (post-MVP)
Claw-ED integration / teacher handoff (post-MVP, but architecturally planned for)
Open Source Commitment
Claw-STU is open source by conviction, not convenience.
If the thesis is correct — that educational institutions will face existential pressure within 5–
10 years — then a proprietary learning platform dies with its funding. An open-source one
survives because the community carries it. Every family, every homeschool co-op, every
community organization, every kid with a phone and an internet connection should be able
to run Stuart.
License: MIT or Apache 2.0 (TBD, but must be maximally permissive)
Future Vision (Post-MVP)
In rough priority order:
1. Game and simulation engine — Interactive learning experiences (Jeopardy-style
review, timeline challenges, map exploration, escape rooms, etc.). Claw-ED’s game-type
reference library transfers directly.
2. 3. 4. 5. 6. 7. Multi-domain support — Expand beyond history into science, math, ELA, and other
subjects
Guardian dashboard — Age-appropriate transparency for parents/guardians about
what the student is learning and how they’re progressing. NOT a surveillance tool.
Claw-ED ↔ Claw-STU handoff — A teacher using Claw-ED can optionally share
curriculum with a student’s Claw-STU instance, creating a hybrid human-AI learning
environment
Peer learning — Facilitate connections between students working on similar topics (with
robust safety architecture)
Lifelong portability — The learner profile grows with the student from childhood
through adulthood. Stuart at 12 and Stuart at 30 are the same agent, evolved.
Offline-first mode — For students without reliable internet access, core functionality
runs locally
A Note on Why This Matters
This project is being built by a public school teacher with nine years in the classroom who
believes two things simultaneously:
1. The institution of school, as currently structured, is unlikely to survive the economic
disruption that AI is about to cause.
2. The work of education — helping humans learn to think — has never been more
important.
Claw-STU is not an attempt to accelerate the death of school. It is an attempt to make sure
that when the institution fails, the learner doesn’t fail with it.
Every kid deserves a Stuart.
Getting Started (For Claude Code)
1. Initialize the repo structure as outlined above
2. Begin with SOUL.md — define Stuart’s identity, voice, and behavioral constraints
3. Build the learner profile data model ( src/profile/model.py )
4. Build the ZPD calibration engine ( src/profile/zpd.py )
5. Build a minimal session loop: onboard → calibrate → teach → assess → adapt
6. Write tests concurrently with every module
7. Stand up a minimal FastAPI server with session endpoints
8. Iterate from there
The first test that should pass: Given a student who answers a calibration question
incorrectly, the agent re-teaches via a different modality than the one that failed.
“The precedent you set here determines how things are done tomorrow.”
