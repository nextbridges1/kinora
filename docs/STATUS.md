# Status: what works and what doesn't

*Updated: 7 October 2026, end of Stage A build.*

## Verified

- 21 automated tests pass. They cover:
  - session isolation between browsers
  - duplicate-send protection
  - context not leaking between sessions
  - message, audio and turn limits
  - per-browser and global daily allowances
  - rate limiting
  - allowance refund on provider failure
  - audio format and empty-audio checks
  - speech caching
  - companion instructions never reaching the browser
  - demo labelling
- The server starts, serves the app, and completes a demo conversation over real HTTP.
- The installed OpenAI SDK (3.25.0) accepts every parameter Kinora uses.
- All text colour pairs meet WCAG AA contrast in light and dark themes.

## Built but not yet verified live (needs an API key)

- Real replies from `gpt-6-luna`, and Mira following her instructions
- Transcription with `gpt-transcribe`
- Spoken replies and voice previews with `gpt-4o-mini-tts`
- Real response times
- Recording in each browser. Chrome/Edge/Firefox record WebM and Safari records MP4; both are accepted formats, but they haven't been tested on real devices.

## Known limitations

- **Usage counters live in memory.** They reset when the server restarts. That's fine for a private prototype, but they need a database before anyone else uses the app.
- **The recording duration counted against allowances comes from the browser.** The server also caps the file size and the counted seconds, but a modified browser could under-report. Fix this in Stage B by measuring duration server-side.
- **Leaving a reply mid-way:** "End session" stops waiting for the reply and discards it, but the request to OpenAI still finishes (and is billed). Cancelling server-side requests isn't supported in this setup.
- **No accounts:** sessions are tied to an anonymous browser cookie.
- **`/api/admin/usage` has no password.** That's safe only because the server listens on 127.0.0.1. Add authentication before any deployment.
- Fonts load from Google Fonts. Offline, the app falls back to system fonts.
- Portraits are temporary placeholders.
- Sunny and Rowan were enabled early, at your request, on the same pipeline as Mira. Tests confirm each one gets its own instructions. How their conversations actually feel still needs testing with a real key.

## Privacy, as actually implemented

- Conversations exist only in server memory until you end them, leave them idle for 60 minutes, or the server stops.
- Raw audio is forwarded to OpenAI for transcription and is never written to disk.
- Requests to OpenAI use `store: false` for replies. OpenAI still processes the data under its own API data policy. Kinora does not claim zero retention.
- Logs record event types, timings and token counts, never message text.
- The API key is read only by the server, from `.env`, which `.gitignore` excludes.
