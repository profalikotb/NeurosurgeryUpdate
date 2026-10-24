# Deploying the frontend on Vercel

Vercel can host **only the `frontend` folder**. The backend must keep running on the Windows PC that holds
the books: it needs `D:\Telegram books`, a persistent index on disk and long-running scan workers, none of
which exist on serverless hosts. Vercel reaches the PC through a tunnel.

```
Phone / laptop ──HTTPS + password──► Vercel (Next.js) ──HTTPS + API token──► Tunnel ──► PC: FastAPI 127.0.0.1:8000 ──► D:\Telegram books
```

## Why the deployment returned `500 FUNCTION_INVOCATION_FAILED`

One of these, from most to least likely:

1. **The project root was the repository root or `backend`**, so Vercel built or ran the Python backend as a
   serverless function, which cannot work. Since this fix, the backend answers 503 with an explanation on Vercel.
2. **`BACKEND_URL` was unset or `http://127.0.0.1:8000`.** On Vercel that is the Vercel machine itself.
3. **Forwarded `content-length` from a compressing tunnel** corrupted proxied responses. Fixed in the proxy.

## Steps

### 1. Expose the backend from the PC (choose one)

**Tailscale Funnel (recommended: free, stable URL, no domain needed)**

1. Install Tailscale on the PC (<https://tailscale.com/download/windows>) and sign in.
2. Allow Funnel for the tailnet (admin console, Access controls, enable *Funnel*).
3. In a terminal on the PC, with the backend running:
   ```powershell
   tailscale funnel --bg 8000
   tailscale funnel status
   ```
   Copy the `https://<pc-name>.<tailnet>.ts.net` URL.

**Cloudflare Tunnel**

- Quick test (URL changes every run): `scripts\start-tunnel.bat`. Copy the `https://….trycloudflare.com` URL.
- Permanent: a named tunnel on your own domain (`cloudflared tunnel create academy`, then a route to
  `http://127.0.0.1:8000`). Optionally add Cloudflare Access in front of it.

The backend stays bound to 127.0.0.1; only the tunnel connects to it. Every API call still requires the token.

### 2. Configure the Vercel project

| Setting | Value |
|---|---|
| Root Directory | `frontend` (**Project, Settings, General, Root Directory**) |
| Framework | Next.js (auto-detected; `frontend/vercel.json` pins it) |
| Node.js version | 20.x or 22.x |

Environment variables (Production and Preview):

| Name | Value |
|---|---|
| `BACKEND_URL` | the tunnel URL from step 1, with no trailing slash |
| `ACADEMY_API_TOKEN` | exactly the value in `backend\.env` on the PC |
| `ACADEMY_UI_PASSWORD` | a strong password. **Required**: without it the site shows a setup notice |
| `ACADEMY_UI_USER` | optional, default `prof` |

Redeploy after changing variables (**Deployments, ⋯, Redeploy**).

### 3. Check

- Open the Vercel URL. The browser asks for the user name and password.
- The sidebar footer shows *OCR available / Keyword search*. If it shows *The backend is not responding*,
  the line below it gives the exact reason:

| Message | Fix |
|---|---|
| BACKEND_URL points to localhost | Set the tunnel URL in Vercel, then redeploy |
| Backend unreachable / timed out | The PC is asleep, the backend is not running, or the tunnel is stopped |
| rejected the API token | Make `ACADEMY_API_TOKEN` identical on both sides |

## Limits of remote use

- The PC must be awake with backend and tunnel running. Disable sleep, or set a wake schedule.
- Scans should be started from the PC, or left to the nightly scheduled scan. Remote scanning works, but closing
  the browser does not stop a scan.
- **Open original** streams the whole book through Vercel and may hit the 60 s function limit for very large
  PDFs. Page images and the extracted text work normally.
- Folder browsing over the tunnel reveals directory names on the PC. It is protected by both the UI password
  and the API token, but keep both secret.
