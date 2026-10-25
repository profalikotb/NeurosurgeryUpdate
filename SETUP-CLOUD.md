# Easy cloud setup: 3 steps, phone-friendly

One website at one address, protected by your password. Your books are uploaded from the iPhone, which can pick
them straight from Google Drive. No PC, no Vercel, no Google Cloud setup.

**Cost:** Render *Starter* (about US$7/month) plus a 10 GB disk (about US$2.50/month). The disk keeps your books
and the index permanently.

## Step 1: GitHub (the code)

Your repository `profalikotb/NeurosurgeryUpdate` must contain these at the top level:
`Dockerfile`, `render.yaml`, `start.sh`, `backend/`, `frontend/`.

- **Easiest:** install the Claude GitHub app on the repository
  (<https://github.com/apps/claude/installations/select_target>) and Claude uploads it for you.
- **Or:** delete the old files, then upload the contents of `NeurosurgeryUpdate-Easy.zip` (Add file, Upload files).

## Step 2: Render (the server, about 5 minutes)

1. Open <https://dashboard.render.com> and choose **Sign in with GitHub**.
2. **New +, Blueprint**, then pick **NeurosurgeryUpdate** (allow Render to see it if asked).
3. Render shows **neurosurgery-academy** (Frankfurt, 10 GB disk). It asks for one value:
   **ACADEMY_UI_PASSWORD**. Type the password you want for the site.
4. Click **Apply** and add a payment card when asked.
5. Wait for **Live**. The first build takes 8–12 minutes; later updates take about 3.
   Your address appears at the top, for example `https://neurosurgery-academy.onrender.com`.

## Step 3: Use it

1. Open the address on the iPhone. User name: **prof**; password: the one from step 2.
2. Optional: **Share, Add to Home Screen** makes it open like an app.
3. **My Neurosurgery Library, Upload book.** In the picker tap **Browse**, then **Google Drive** (or iCloud
   Drive / On My iPhone), and choose the book. You can select several at once.
4. A progress bar shows the upload. Indexing follows automatically: about a minute for a 1,000-page book.
   Uploads resume by themselves if the connection drops.

That's all. **Latest Neurosurgery Updates** fills itself within a few minutes and refreshes daily.

## Good to know

- **Change the password:** Render, service, **Environment**, edit `ACADEMY_UI_PASSWORD`, then **Save**.
- **Remove a book:** open it in the app and choose **Delete this book**. Your copy in Google Drive is untouched.
- **Disk full:** Render, service, **Disks**, increase the size. It can grow but not shrink.
- **Updates to the app:** every change pushed to GitHub redeploys automatically. Your books and index are kept.
- **Old Vercel project:** no longer needed. You can delete it in Vercel, Project, Settings.
- **Optional automatic Drive syncing:** possible later without reinstalling; see `docs/CLOUD_DRIVE.md`.
