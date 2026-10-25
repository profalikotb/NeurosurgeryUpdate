"use client";
import { useRef, useState } from "react";
import { API } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Item = { name: string; pct: number; state: "queued" | "uploading" | "done" | "error"; msg?: string };
const ACCEPT = ".pdf,.epub,.docx,.txt,.md,.mobi,.fb2,application/pdf,application/epub+zip";

const CHUNK = 8 * 1024 * 1024; // 8 MB parts: flat server memory, and a dropped connection only repeats one part

type PartResult = { status: number; body: { detail?: unknown; received?: number; filename?: string; job_id?: number | null } };

function sendPart(url: string, blob: Blob, onProgress: (loaded: number) => void): Promise<PartResult> {
  // XMLHttpRequest (not fetch) because it reports upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("content-type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded);
    xhr.onload = () => {
      let body = {};
      try {
        body = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* not json */
      }
      resolve({ status: xhr.status, body });
    };
    xhr.onerror = () => reject(new Error("network"));
    xhr.send(blob);
  });
}

function detailText(d: unknown): string {
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  return "Upload failed";
}

async function put(file: File, onProgress: (pct: number) => void): Promise<{ filename: string; job_id: number | null }> {
  const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
  const base = `${API}/library/upload?filename=${encodeURIComponent(file.name)}&upload_id=${id}`;
  let offset = 0;
  let failures = 0;
  for (;;) {
    const end = Math.min(offset + CHUNK, file.size);
    const final = end >= file.size;
    let res: PartResult;
    try {
      res = await sendPart(`${base}&offset=${offset}&final=${final}`, file.slice(offset, end), (loaded) =>
        onProgress(Math.min(99, Math.round(((offset + loaded) / Math.max(file.size, 1)) * 100))),
      );
    } catch {
      if (++failures > 5) throw new Error("Network error: the upload was interrupted. Try again on a stable connection.");
      await new Promise((r) => setTimeout(r, 1500 * failures));
      continue; // retry the same part; the server tells us where to resume if it already has it
    }
    if (res.status === 409 && res.body.detail && typeof res.body.detail === "object") {
      offset = Number((res.body.detail as { received?: number }).received ?? offset);
      continue;
    }
    if (res.status === 401) throw new Error("Session expired: reload the page and sign in again.");
    if (res.status < 200 || res.status >= 300) throw new Error(detailText(res.body.detail));
    failures = 0;
    if (final) {
      onProgress(100);
      return { filename: res.body.filename || file.name, job_id: res.body.job_id ?? null };
    }
    offset = end;
  }
}

export default function UploadBooks({ onUploaded }: { onUploaded: () => void }) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const busy = items.some((i) => i.state === "uploading" || i.state === "queued");

  const start = async (files: FileList | null) => {
    if (!files?.length) return;
    const list = Array.from(files);
    setItems(list.map((f) => ({ name: f.name, pct: 0, state: "queued" })));
    for (let k = 0; k < list.length; k++) {
      const upd = (patch: Partial<Item>) => setItems((xs) => xs.map((x, i) => (i === k ? { ...x, ...patch } : x)));
      upd({ state: "uploading" });
      try {
        await put(list[k], (pct) => upd({ pct }));
        upd({ state: "done", pct: 100 });
        onUploaded();
      } catch (e) {
        upd({ state: "error", msg: (e as Error).message });
      }
    }
    if (input.current) input.current.value = "";
  };

  return (
    <div className="rounded-md border border-teal/30 bg-teal-50/60 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-ink">{t.upload_title}</h3>
          <p className="mt-0.5 text-sm text-text-2">{t.upload_hint}</p>
        </div>
        <button className="btn-teal shrink-0 px-5 py-2.5" disabled={busy} onClick={() => input.current?.click()}>
          {busy ? t.uploading : t.upload_button}
        </button>
        <input ref={input} type="file" accept={ACCEPT} multiple className="hidden" onChange={(e) => start(e.target.files)} />
      </div>
      {items.length > 0 && (
        <ul className="mt-3 space-y-2">
          {items.map((it, i) => (
            <li key={i} className="text-sm">
              <div className="flex items-baseline gap-2">
                <span className="ltr min-w-0 flex-1 truncate" dir="ltr">{it.name}</span>
                <span className={`shrink-0 text-xs ${it.state === "error" ? "text-danger" : it.state === "done" ? "text-teal-600" : "text-text-2"}`}>
                  {it.state === "done" ? t.upload_done : it.state === "error" ? t.upload_failed : `${it.pct}%`}
                </span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-white">
                <div className={`h-full ${it.state === "error" ? "bg-danger" : "bg-teal"}`} style={{ width: `${it.state === "error" ? 100 : it.pct}%` }} />
              </div>
              {it.msg && <p className="mt-1 text-xs text-danger">{it.msg}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
