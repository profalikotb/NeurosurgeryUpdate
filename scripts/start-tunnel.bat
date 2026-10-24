@echo off
REM Quick Cloudflare tunnel to the local backend, for testing a Vercel frontend.
REM The printed https://....trycloudflare.com URL changes every run: put it in Vercel's BACKEND_URL and redeploy.
REM For a stable URL use Tailscale Funnel or a named Cloudflare tunnel (docs\VERCEL.md).
where cloudflared >nul 2>&1 || (
  echo cloudflared not found. Install with:  winget install --id Cloudflare.cloudflared
  exit /b 1
)
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000
