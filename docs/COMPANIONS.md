# Changing companions, portraits and voices

Everything about a companion lives in **`config/companions.json`**. Restart the server after editing it.

## Fields

| Field | Shown to users? | Purpose |
|---|---|---|
| `id` | in URLs | Short lowercase name. Don't change it once people use the app. |
| `available` | yes | `true` lets people start conversations. `false` shows the card as "coming later". |
| `available_note` | yes | Label shown when unavailable. |
| `name`, `role`, `description` | yes | Card text. |
| `purpose`, `style`, `scope` | yes | Details page. |
| `opening` | yes | First message in every new conversation. |
| `accent` | yes | `sage`, `amber` or `slate` (colours are in `web/styles.css`). |
| `portrait`, `portrait_alt` | yes | Image path inside `web/`, plus the text screen readers announce. |
| `voice.id` | no | OpenAI voice name (list below). |
| `voice.label` | yes | Plain description, e.g. "Warm and calm". |
| `voice.instructions` | no | How the voice should sound (tone, pace). |
| `voice.preview_text` | heard | What the voice preview says. |
| `instructions` | **never** | Personality and behaviour rules sent to the model. Kept on the server. |

The shared rules every companion follows (safety, honesty about being AI, no pressure to stay) are in `server/policy.py`. Edit those with care.

## Portraits

- Current portraits are **temporary** illustrations made for this project.
- To replace one, put the new image in `web/portraits/` (square, at least 800×800 px, face centred in the upper half, same crop for all three), and update `portrait` and `portrait_alt`.
- Use only artwork you made, commissioned or licensed. Don't use photos of real people without a model release, and don't imitate celebrities.

## Voices

Built-in voices for `gpt-4o-mini-tts` (checked October 2026):
`alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse, marin, cedar`.

- Current mapping: Mira → `marin`, Sunny → `coral`, Rowan → `cedar`.
- `voice.instructions` changes the tone of a voice, but it can't make a new voice. Two companions on the same voice will still sound like the same speaker.
- After changing a voice, listen to its preview (Companion details → Play voice preview). Previews are cached in `.cache/voice-previews/` and regenerate automatically when the voice or text changes.
- Check https://developers.openai.com/api/docs/guides/text-to-speech for the current list before switching.
