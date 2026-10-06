# Putting Kinora online (Render)

The result is a permanent link like `https://kinora-xxxx.onrender.com` that anyone can open.

## One-time setup

1. **GitHub account:** sign up at https://github.com (free).
2. **Empty repository:** on GitHub click **+ → New repository**. Name it `kinora` and choose **Private**. Don't add a README, .gitignore or licence. Click **Create repository** and copy its address (`https://github.com/<you>/kinora.git`).
3. **Upload the code** (in PowerShell, in the project folder):
   ```powershell
   & "C:\Program Files\Git\cmd\git.exe" remote add origin https://github.com/<you>/kinora.git
   & "C:\Program Files\Git\cmd\git.exe" push -u origin main
   ```
   A browser window asks you to sign in to GitHub the first time.
4. **Render account:** sign up at https://render.com with **Sign in with GitHub**. The free plan doesn't need a card.
5. **Create the service:** in Render, click **New → Blueprint**, pick the `kinora` repository, and click **Apply**.
   - When it asks for `OPENAI_API_KEY`, leave it **empty** for demo mode.
   - When it asks for `KINORA_ACCESS_CODE`, leave it empty for an open link, or type a code testers must enter.
6. Wait for the build to finish (2–5 minutes). Your link appears at the top of the service page.

## Updating the site later

After changes, run:
```powershell
& "C:\Program Files\Git\cmd\git.exe" add -A
& "C:\Program Files\Git\cmd\git.exe" commit -m "Describe the change"
& "C:\Program Files\Git\cmd\git.exe" push
```
Render redeploys automatically.

## Adding the OpenAI key later

Go to Render → **kinora** → **Environment**, set `OPENAI_API_KEY`, and save. Render restarts the service, and the badge changes to **Connected**.
**Set `KINORA_ACCESS_CODE` at the same time**, otherwise anyone with the link spends your credit. Also set a monthly budget in your OpenAI account.

## Free plan behaviour

- The service sleeps after about 15 minutes without visitors. The next visitor waits 30–60 seconds while it wakes up.
- A restart clears conversations and the daily usage counters. Nothing is stored permanently.
- The microphone works because Render serves the site over HTTPS.

## Usage report

`GET /api/admin/usage` with the header `X-Admin-Token: <value>` returns today's totals. Render generated the token; you'll find it under **Environment → KINORA_ADMIN_TOKEN**.
