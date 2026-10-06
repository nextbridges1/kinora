# Kinora

*Choose the conversation you need.* A web app where adults talk with an AI companion by text or recorded voice.

**Current stage: A, the working private prototype.** One companion (Mira), real text chat, record-and-reply voice, spoken replies. Without an API key it runs in a clearly labelled **demo mode**.

---

## 1. Run it on your computer

You need **Python 3.10 or newer**. This machine already has Python 3.13.

**Easiest way:** double-click `start.bat`.
On the first run it installs everything (a minute or two). Then open **http://127.0.0.1:8000** in Chrome, Edge, Firefox or Safari.

**Same thing in a terminal** (PowerShell, inside this folder):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

Stop the server with **Ctrl+C**. The app is only reachable from your own computer.

## 2. Connect OpenAI (turns demo mode off)

Real replies and voices need an **OpenAI API account with billing**. A ChatGPT Plus/Pro subscription does **not** include API usage.

1. Sign in at https://platform.openai.com, add a payment method under **Billing**, and set a monthly **usage limit** there as a backstop.
2. Create a key at https://platform.openai.com/api-keys.
3. In this folder, copy `.env.example` and rename the copy to `.env`.
4. Open `.env` in Notepad and paste your key after `OPENAI_API_KEY=` (no quotes, no spaces).
5. Save, then restart the server. The badge at the top changes from **Demo mode** to **Connected**.

Keep the key only in `.env`. Never paste it into chat, email, or screenshots. If it leaks, delete it on the API keys page and create a new one.

## 3. Test it

**Automatic tests** (free, no API calls):

```powershell
.\.venv\Scripts\python.exe -m pytest
```

**By hand, after connecting:**

1. Start a conversation with Mira and type something specific ("A client rewrote my whole proposal an hour before the meeting"). Check that Mira refers to the details and asks one question at most.
2. Say "I just want to vent". Check that Mira doesn't jump to advice.
3. Press **Record**, speak, press **Stop recording**. Check the transcription, then press **Send**. The reply should be read aloud.
4. While it speaks, press **Stop audio** (or Esc). It should stop immediately. Press **Replay** to hear it again (no extra cost).
5. Block the microphone in the browser's site settings and reload. Typing should still work, and you should see a clear message.
6. Press **End session**, then **End and clear**. The transcript is wiped.

## 4. Where things live

| What | Where |
|---|---|
| Companion names, descriptions, openings, voices, instructions | `config/companions.json` (see `docs/COMPANIONS.md`) |
| Shared conversation and safety rules | `server/policy.py` |
| Limits, models, allowances | `.env` (see `.env.example`) |
| OpenAI calls and demo stand-in | `server/ai_provider.py` |
| Web pages, styles, browser logic | `web/` |
| Portraits | `web/portraits/` |
| Product brief, stage checklist, status | `docs/` |

## 5. Shareable interface preview

`python scripts/build_preview.py` creates `preview/kinora.html`, a static copy that never contacts OpenAI and uses labelled placeholder replies. It's useful for showing the design to others.

## Troubleshooting

- **"python is not recognized"**: reinstall Python from python.org and tick **Add python.exe to PATH**.
- **Port 8000 already in use**: change `--port 8000` to `--port 8010` (in `start.bat` too) and open that address.
- **Badge still says Demo mode**: the file must be named exactly `.env`, not `.env.txt`. In File Explorer, turn on **View → File name extensions** to check.
- **"The OpenAI account is out of credit"**: add credit under Billing on the OpenAI platform.
- **No voice on iPhone/Safari**: tap **Play** on the reply. Safari sometimes blocks audio that wasn't started by a tap.
