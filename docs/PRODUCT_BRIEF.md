# Kinora — product brief

**Tagline:** Choose the conversation you need.

**What it is:** a mobile-friendly web app where adults pick an AI companion and talk by text or recorded voice, to vent, celebrate, chat lightly or think something through. It's about conversation, listening and perspective. It isn't a productivity tool, a coding assistant or therapy.

**First audience (a hypothesis to test):** adults who work or study alone, such as freelancers, remote workers and creators.

**Companions** (defined in `config/companions.json`):

| | Role | Voice | Accent |
|---|---|---|---|
| Mira | Thoughtful listener: vent, hard days, mixed feelings | `marin`, warm and calm | sage |
| Sunny | Cheerful conversationalist: good news, light chat | `coral`, friendly and lively | amber |
| Rowan | Perspective partner: decisions, work tensions | `cedar`, steady and thoughtful | slate blue |

All companions share one model, plus a shared conversation and safety policy (`server/policy.py`), and each has its own instructions.

**Principles**
- Every companion and voice is labelled as AI.
- Users keep control: brevity, ending, what's saved.
- Never optimise for dependence or time spent.
- Never present demo or placeholder features as working.
- Be honest about data: what's stored, what goes to the provider.

**Voice approach:** record-and-reply (record → transcribe → review → reply → speak). It is not a live call. The provider layer is separate, so Realtime speech-to-speech can be added later.

**Pilot questions:** do the personalities feel different? Does "just listen" actually avoid advice? Is the voice natural, and are the delays acceptable? Do people come back on their own? Why choose this over a general chatbot? What does a session really cost?
