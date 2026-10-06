# Staged implementation checklist

## Stage A — working private prototype (current)

- [x] Design foundation: tokens, light/dark themes, contrast checked (all text pairs ≥ 4.5:1)
- [x] Responsive home, companion details and conversation room
- [x] Mira, defined in central config
- [x] Real text conversation through the OpenAI Responses API *(code done; needs your API key to verify live)*
- [x] Record-and-reply voice input with transcript review *(needs key to verify live)*
- [x] Spoken replies with stop, replay, mute and end-session *(needs key to verify live)*
- [x] Temporary in-memory session context (no persistence)
- [x] Loading, error and recovery states (retry, edit, text fallback)
- [x] Server-side rate limit, size limits, recording limit, turn limit, per-browser and global daily allowances
- [x] Duplicate-send protection (request IDs), stale-response protection, no automatic provider retries
- [x] Labelled demo mode and static interface preview
- [x] Focused tests: 21 passing
- [ ] **Live verification with a real API key** (you: add key, then run the manual checks in README §3)
- [ ] Latency measurement on real calls (the server logs `reply ms=` for each reply)

## Stage B — three-companion beta

- [x] Enable Sunny and Rowan *(done early; test their behaviour with a real key)*
- [x] Full companion dashboard: animated home, situation cards, showcases
- [ ] Conversation preferences: Just listen / Help me think / Keep it light
- [ ] Voice previews on the dashboard (code exists; check them with a key)
- [ ] Optional accounts + saved history with an on/off control
- [ ] Rename, delete and filter history; account deletion
- [ ] Persistent usage counters and a cost dashboard
- [ ] Simple feedback (thumbs plus an optional note, with no conversation content by default)
- [ ] Companion handover: start fresh, or share a summary you approve and can edit
- [ ] Authorization tests between accounts

## Stage C — release preparation

- [ ] Plans and transparent allowances
- [ ] Payments, suited to your business location
- [ ] Security review, privacy policy and terms
- [ ] Support and account management
- [ ] Optional memory with view, edit and delete, plus explicit approval
- [ ] Production monitoring and deployment docs

## Stage D — later (not now)

Realtime voice, more companions, more languages, saved reflections, animated avatars.
