# Cloud mode: books from Google Drive, no PC

Optional add-on to the easy cloud setup (`SETUP-CLOUD.md`). With it, books placed in one Google Drive folder are
indexed automatically, so you no longer upload them one by one.

```
iPhone / any browser ──password──► Render (website + backend + index on disk) ──read-only──► Google Drive folder
```

The backend runs on a small cloud server (Render), reads your books from **one shared Google Drive folder**,
keeps the index on its own disk, and re-checks the folder every 90 seconds. A book you upload to that folder,
even from your phone, becomes searchable with page citations a few minutes later. The literature updates run
on the server too, so they continue when your PC is off.

**Cost:** nothing extra. The Google Drive API is free.

**Access:** the server gets read-only access to the one folder you share with it, and nothing else in your
Drive. It never modifies or deletes your files.

Allow about 15 minutes. A computer is easier for Part A.

---

## Part A: Google Cloud service account (once, about 10 minutes)

1. Open <https://console.cloud.google.com> and sign in with any Google account.
2. Top bar, **project picker, New project**. Name it `Neurosurgery Academy`, then **Create**, and select it.
3. Menu **APIs & Services, Library**. Search for **Google Drive API**, open it, and click **Enable**.
4. Menu **IAM & Admin, Service Accounts, Create service account**.
   - Name: `academy-drive-reader`. Click **Create and continue**.
   - Skip the role and user-access steps, then click **Done**.
5. Open the new service account, go to the **Keys** tab, choose **Add key, Create new key, JSON**, then **Create**.
   A `.json` file downloads. **Keep it private**: it is the password to the shared folder.
6. Copy the service account's e-mail address. It looks like
   `academy-drive-reader@neurosurgery-academy-123456.iam.gserviceaccount.com`.

> If key creation is blocked by an "organization policy" (Workspace accounts only), use a personal Gmail account
> for this project, or ask your Workspace admin to allow service-account keys.

## Part B: Google Drive folder (2 minutes)

1. In Google Drive, create a folder, for example **Neurosurgery Books**.
2. **Move** your books into it, for example *Greenbergs Handbook of Neurosurgery*. Sub-folders are fine.
   Use *Move*, not *Add shortcut*: a shortcut to a file outside the shared folder cannot be read.
3. On the folder, choose **Share**, paste the service account e-mail, set it to **Viewer**, untick *Notify people*,
   then **Share**. Drive warns that the address is outside your organisation; that is expected.
4. Choose **Share, Copy link**. You will paste this link into the app in Part E.

## Part C: connect the key to your server

This assumes the site is already running on Render (see `SETUP-CLOUD.md`).

1. In Render, open the **neurosurgery-academy** service and go to **Environment, Secret Files, Add Secret File**.
   - **Filename:** `google-service-account.json` (exactly).
   - **Contents:** open the JSON key from Part A in a text editor, copy everything, and paste it.
   - Click **Save Changes**. The service redeploys in about 3 minutes.
2. In the app, open **My Neurosurgery Library**. The box **Add a Google Drive folder** now shows the
   service account e-mail. Paste the folder link from B4 and tap **Add Drive folder**.

## Day-to-day use

- **Add a book:** upload it into the shared folder from Drive on your phone. It is indexed automatically within
  about 2–3 minutes; you can follow progress in *My Neurosurgery Library*.
- **Remove a book:** delete it from the folder. It leaves the search results at the next check. A Drive outage
  never deletes anything from the index.
- **Rename or move within the folder:** detected automatically, with no re-indexing.
- **Open in Google Drive:** a book's page in the app links to the original file in Drive.

## Troubleshooting

| Message | Fix |
|---|---|
| *Google Drive is not configured on this server* | Secret file missing or misnamed. It must be `google-service-account.json`; redeploy afterwards |
| *The folder is not shared with …iam.gserviceaccount.com* | Share the folder with that exact address (Part B3) |
| *This link points to a file, not a folder* | Paste the folder's link, not a book's link |
| *Google rejected the service-account key* | The key was deleted in Google Cloud. Create a new JSON key and replace the secret file |
| *Shortcut … is not shared* | Move the real file into the shared folder instead of adding a shortcut |
| Disk full | Render, Disks: increase the size (it can grow, not shrink) |

Google Docs, Sheets and Slides files have no downloadable file and are skipped. Use *File, Download, PDF*, then
upload the PDF to the folder.

### Alternative to the secret file

Instead of the secret file, set an environment variable `ACADEMY_GDRIVE_SERVICE_ACCOUNT_JSON` containing the key,
either the JSON text itself or the JSON encoded in base64.
