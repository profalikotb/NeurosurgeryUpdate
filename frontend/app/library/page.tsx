"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Doc, type Folder, type Job } from "@/lib/api";
import { docTitle, fmtDateTime, fmtNum, fmtSize } from "@/lib/format";
import { statusLabel, useI18n } from "@/lib/i18n";
import { ErrorNote, StatusChip } from "@/components/bits";
import UploadBooks from "@/components/Upload";

export default function LibraryPage() {
  const { t } = useI18n();
  const [folders, setFolders] = useState<Folder[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const loadFolders = useCallback(() => api<Folder[]>("/folders").then(setFolders).catch((e) => setErr(e.message)), []);

  // Pick up jobs started elsewhere: automatic indexing, the CLI, another tab.
  const watchingId = job?.status === "running" ? job.id : null;
  useEffect(() => {
    loadFolders();
  }, [loadFolders]);
  useEffect(() => {
    if (watchingId) return;
    const look = () =>
      api<{ active: number | null }>("/jobs")
        .then((r) => {
          if (r.active) api<Job>(`/jobs/${r.active}`).then(setJob);
        })
        .catch(() => {});
    look();
    const id = setInterval(look, 10000);
    return () => clearInterval(id);
  }, [watchingId]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    const id = setInterval(async () => {
      try {
        const j = await api<Job>(`/jobs/${job.id}`);
        setJob(j);
        if (j.status !== "running") {
          loadFolders();
          setRefreshKey((k) => k + 1);
        }
      } catch {
        /* transient */
      }
    }, 1000);
    return () => clearInterval(id);
  }, [job, loadFolders]);

  const scan = async (force = false, folderIds?: number[]) => {
    setErr(null);
    try {
      const r = await api<{ job_id: number }>("/scan", { method: "POST", json: { force_reindex: force, folder_ids: folderIds } });
      setJob(await api<Job>(`/jobs/${r.job_id}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const running = job?.status === "running";
  const [uploadsOn, setUploadsOn] = useState(false);
  const followUpload = () => {
    setRefreshKey((k) => k + 1);
    loadFolders();
    api<{ active: number | null }>("/jobs")
      .then((r) => {
        if (r.active) api<Job>(`/jobs/${r.active}`).then(setJob);
      })
      .catch(() => {});
  };
  useEffect(() => {
    api<{ uploads_enabled?: boolean }>("/status").then((s) => setUploadsOn(!!s.uploads_enabled)).catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <section>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="h1 flex-1">{t.nav_library}</h1>
          <button className="btn-ghost" disabled={running || !folders.length} onClick={() => confirm(t.rescan_force + "?") && scan(true)}>
            {t.rescan_force}
          </button>
          <button className="btn-primary" disabled={running || !folders.length} onClick={() => scan(false)}>
            {t.scan_all}
          </button>
        </div>
        {err && <div className="mt-4"><ErrorNote msg={err} /></div>}
        {uploadsOn && (
          <div className="mt-4">
            <UploadBooks onUploaded={followUpload} />
          </div>
        )}
        {job && <JobPanel job={job} onCancel={() => api(`/jobs/${job.id}/cancel`, { method: "POST" }).catch(() => {})} />}
        <Folders folders={folders} onChange={loadFolders} disabled={running} onScan={(id) => scan(false, [id])} />
      </section>
      <Documents refreshKey={refreshKey} />
    </div>
  );
}

function JobPanel({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const { t } = useI18n();
  const p = job.progress as Record<string, number | string | undefined>;
  const running = job.status === "running";
  const phase = String(p.phase || "");
  let pct = 0;
  if (phase === "hashing" && p.to_hash) pct = (Number(p.hashed) / Number(p.to_hash)) * 100;
  if (phase === "indexing" && p.to_index) {
    const within = p.pages ? Number(p.page) / Number(p.pages) : 0;
    pct = ((Number(p.indexed || 0) + within) / Number(p.to_index)) * 100;
  }
  if (!running) pct = 100;
  const summary = ["new", "changed", "moved", "duplicates", "missing", "unchanged"]
    .filter((k) => p[`files_${k}`] !== undefined)
    .map((k) => `${k} ${p[`files_${k}`]}`)
    .join(", ");
  const errors = job.log.split("\n").filter((l) => /ERROR|Cannot|failed|not reachable/i.test(l)).slice(-6);
  return (
    <div className="panel mt-4 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <strong className="text-ink">{running ? t.scanning : job.status}</strong>
        <span className="text-text-2">{phase}</span>
        {p.current && <span className="ltr min-w-0 flex-1 truncate text-text-3" dir="ltr">{String(p.current)}</span>}
        {running && (
          <button className="btn-ghost px-3 py-1 text-xs" onClick={onCancel}>
            {t.cancel}
          </button>
        )}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface">
        <div className={`h-full rounded-full transition-[width] ${job.status === "failed" ? "bg-danger" : "bg-teal"}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <p className="mt-2 text-xs text-text-2">
        {p.discovered !== undefined && <>discovered {String(p.discovered)}. </>}
        {summary}
        {p.to_index !== undefined && <>. indexed {String(p.indexed ?? 0)}/{String(p.to_index)}</>}
      </p>
      {errors.length > 0 && (
        <pre className="ltr mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-danger-50 p-2 text-xs text-danger" dir="ltr">
          {errors.join("\n")}
        </pre>
      )}
    </div>
  );
}

type DriveStatus = { configured: boolean; error: string | null; service_account_email: string | null; local_folders_enabled: boolean; uploads_enabled?: boolean };

function Folders({ folders, onChange, disabled, onScan }: { folders: Folder[]; onChange: () => void; disabled: boolean; onScan: (id: number) => void }) {
  const { t, lang } = useI18n();
  const [path, setPath] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [drive, setDrive] = useState<DriveStatus | null>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api<DriveStatus>("/gdrive/status").then(setDrive).catch(() => {});
  }, []);

  const addDrive = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await api("/gdrive/folders", { method: "POST", json: { link } });
      setLink("");
      onChange();
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const copyEmail = async () => {
    if (!drive?.service_account_email) return;
    try {
      await navigator.clipboard.writeText(drive.service_account_email);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  const showLocal = drive ? drive.local_folders_enabled : true;

  const add = async (e?: React.FormEvent, p = path) => {
    e?.preventDefault();
    setErr(null);
    try {
      await api("/folders", { method: "POST", json: { path: p } });
      setPath("");
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const remove = async (f: Folder) => {
    if (!confirm(t.remove_folder_confirm)) return;
    try {
      await api(`/folders/${f.id}`, { method: "DELETE" });
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const toggle = async (f: Folder) => {
    await api(`/folders/${f.id}`, { method: "PATCH", json: { enabled: !f.enabled } }).catch(() => {});
    onChange();
  };

  return (
    <div className="panel mt-5 p-5">
      <h2 className="h2">{t.folders}</h2>
      {folders.length === 0 && (
        <p className="mt-2 text-sm text-text-2">{showLocal ? t.empty_folders : drive?.uploads_enabled ? t.empty_uploads : t.empty_drive}</p>
      )}
      <ul className="mt-3 divide-y divide-rule">
        {folders.map((f) => (
          <li key={f.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-4">
            <div className="min-w-0 flex-1">
              <p className="ltr truncate text-sm font-medium text-ink" dir="ltr" title={f.path}>
                {f.source === "gdrive" ? (
                  <a href={f.web_link || undefined} target="_blank" rel="noreferrer" className="hover:text-deep hover:underline">{f.label}</a>
                ) : showLocal ? f.path : f.label}
              </p>
              <p className="mt-0.5 text-xs text-text-2">
                {fmtNum(f.indexed || 0)} / {fmtNum(f.documents)} {t.documents.toLowerCase()}
                {f.errors ? <span className="text-danger"> · {f.errors} {statusLabel[lang].error}</span> : null}
                {" · "}
                {t.last_scan}: {fmtDateTime(f.last_scan_at, lang)}
                {!f.reachable && <span className="ms-2 chip bg-danger-50 text-danger">{t.unreachable}</span>}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-text-2">
              <input type="checkbox" className="h-4 w-4 accent-teal" checked={!!f.enabled} onChange={() => toggle(f)} disabled={disabled} />
              {t.enabled}
            </label>
            <button className="btn-ghost px-3 py-1 text-xs" disabled={disabled || !f.reachable} onClick={() => onScan(f.id)}>
              {t.scan_one}
            </button>
            <button className="btn-danger px-3 py-1 text-xs" disabled={disabled} onClick={() => remove(f)}>
              {t.remove}
            </button>
            </div>
          </li>
        ))}
      </ul>
      {drive?.configured && (
        <div className="mt-4 rounded-md border border-rule bg-surface p-4">
          <h3 className="text-sm font-semibold text-ink">{t.drive_add_title}</h3>
          <ol className="mt-2 list-decimal space-y-1 ps-5 text-sm text-text-2">
            <li>{t.drive_step1}</li>
            <li>
              {t.drive_step2}{" "}
              <button type="button" onClick={copyEmail} className="ltr break-all font-medium text-deep underline" dir="ltr">
                {drive.service_account_email}
              </button>{" "}
              <span className="text-xs text-teal-600">{copied ? t.copied : ""}</span>
            </li>
            <li>{t.drive_step3}</li>
          </ol>
          <form onSubmit={addDrive} className="mt-3 flex flex-col gap-2 sm:flex-row">
            <input className="input ltr flex-1" dir="ltr" value={link} onChange={(e) => setLink(e.target.value)}
              placeholder="https://drive.google.com/drive/folders/…" aria-label={t.drive_link} />
            <button className="btn-primary" disabled={!link.trim() || busy}>{busy ? "…" : t.drive_add}</button>
          </form>
        </div>
      )}
      {drive && !drive.configured && !showLocal && !drive.uploads_enabled && <div className="mt-4"><ErrorNote msg={drive.error || t.drive_not_configured} /></div>}
      {showLocal && <form onSubmit={add} className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input className="input ltr flex-1" dir="ltr" value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\Telegram books\Notebooklm books" aria-label={t.folder_path} />
        <button type="button" className="btn-ghost" onClick={() => setBrowsing(true)}>
          {t.browse}
        </button>
        <button className="btn-primary" disabled={!path.trim()}>
          {t.add_folder}
        </button>
      </form>}
      {err && <div className="mt-3"><ErrorNote msg={err} /></div>}
      {browsing && <FolderBrowser onClose={() => setBrowsing(false)} onPick={(p) => (setBrowsing(false), add(undefined, p))} />}
    </div>
  );
}

function FolderBrowser({ onClose, onPick }: { onClose: () => void; onPick: (p: string) => void }) {
  const { t } = useI18n();
  const [data, setData] = useState<{ path: string | null; parent: string | null; dirs: { name: string; path: string }[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const dlg = useRef<HTMLDialogElement>(null);
  const open = (p?: string | null) =>
    api<typeof data>(`/fs/browse${p ? `?path=${encodeURIComponent(p)}` : ""}`).then((d) => (setData(d), setErr(null))).catch((e) => setErr(e.message));
  useEffect(() => {
    dlg.current?.showModal();
    open();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <dialog ref={dlg} onClose={onClose} className="w-[min(40rem,94vw)] rounded-xl border border-rule p-0 backdrop:bg-ink/50">
      <div className="border-b border-rule px-5 py-3">
        <p className="ltr truncate text-sm font-medium" dir="ltr">{data?.path || "/"}</p>
      </div>
      <ul className="max-h-[50vh] overflow-y-auto p-2">
        {data?.path && (
          <li>
            <button className="w-full rounded px-3 py-2 text-start text-sm text-deep hover:bg-surface" onClick={() => open(data.parent)}>
              ↑ {t.up}
            </button>
          </li>
        )}
        {data?.dirs.map((d) => (
          <li key={d.path}>
            <button className="ltr w-full truncate rounded px-3 py-2 text-start text-sm hover:bg-surface" dir="ltr" onClick={() => open(d.path)}>
              {d.name}
            </button>
          </li>
        ))}
      </ul>
      {err && <div className="px-5"><ErrorNote msg={err} /></div>}
      <div className="flex justify-end gap-2 border-t border-rule px-5 py-3">
        <button className="btn-ghost" onClick={() => dlg.current?.close()}>
          {t.cancel}
        </button>
        <button className="btn-primary" disabled={!data?.path} onClick={() => data?.path && onPick(data.path)}>
          {t.choose}
        </button>
      </div>
    </dialog>
  );
}

const STATUSES = ["", "indexed", "partial", "ocr_needed", "error", "duplicate", "missing", "pending"];

function Documents({ refreshKey }: { refreshKey: number }) {
  const { t, lang } = useI18n();
  const [items, setItems] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("title");
  const [quality, setQuality] = useState(false);

  useEffect(() => {
    const p = new URLSearchParams({ limit: "500", sort: quality ? "quality" : sort });
    if (status) p.set("status", status);
    if (q) p.set("q", q);
    const h = setTimeout(() => api<{ total: number; items: Doc[] }>(`/documents?${p}`).then((r) => (setItems(r.items), setTotal(r.total))).catch(() => {}), 200);
    return () => clearTimeout(h);
  }, [status, q, sort, quality, refreshKey]);

  return (
    <section>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="h2 flex-1">
          {quality ? t.quality : t.documents} <span className="text-sm font-normal text-text-2">({fmtNum(total)})</span>
        </h2>
        <div className="flex rounded-md border border-rule bg-white p-0.5 text-sm" role="tablist">
          <button role="tab" aria-selected={!quality} className={`rounded px-3 py-1 ${!quality ? "bg-deep text-white" : ""}`} onClick={() => setQuality(false)}>
            {t.documents}
          </button>
          <button role="tab" aria-selected={quality} className={`rounded px-3 py-1 ${quality ? "bg-deep text-white" : ""}`} onClick={() => setQuality(true)}>
            {t.quality}
          </button>
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input className="input flex-1 py-1.5" placeholder={t.find_doc} value={q} onChange={(e) => setQ(e.target.value)} dir="auto" />
        <select className="input py-1.5 sm:w-48" value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t.filter_status}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s ? statusLabel[lang][s] : t.any}
            </option>
          ))}
        </select>
        {!quality && (
          <select className="input py-1.5 sm:w-40" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="title">{t.title}</option>
            <option value="added">{lang === "ar" ? "الأحدث" : "Newest"}</option>
            <option value="pages">{t.pages}</option>
          </select>
        )}
      </div>
      <div className="panel mt-3 overflow-x-auto">
        <table className="w-full min-w-[720px] table-fixed text-sm">
          <colgroup>
            <col className="w-[52%]" />
            <col className="w-[15%]" />
            <col className="w-[9%]" />
            <col className="w-[14%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead className="border-b border-rule bg-surface text-start text-xs text-text-2">
            <tr>
              <th className="px-4 py-2.5 text-start font-medium">{t.title}</th>
              <th className="px-3 py-2.5 text-start font-medium">{t.edition}</th>
              <th className="px-3 py-2.5 text-end font-medium">{t.pages}</th>
              <th className="px-3 py-2.5 text-start font-medium">{t.status}</th>
              <th className="px-3 py-2.5 text-end font-medium">{quality ? (lang === "ar" ? "الجودة" : "Quality") : (lang === "ar" ? "الحجم" : "Size")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {items.map((d) => (
              <tr key={d.id} className="align-top hover:bg-surface/60">
                <td className="max-w-0 px-4 py-2.5">
                  <Link href={`/documents/${d.id}`} className="ltr block truncate font-medium text-ink hover:text-deep" dir="ltr">
                    {docTitle(d)}
                  </Link>
                  <p className="ltr truncate text-xs text-text-3" dir="ltr">{d.filename}</p>
                  {quality && d.quality_notes && <p className="mt-1 whitespace-pre-line text-xs text-text-2">{d.quality_notes}</p>}
                  {d.error && <p className="ltr mt-1 text-xs text-danger" dir="ltr">{d.error}</p>}
                  {d.duplicate_of && <p className="text-xs text-text-3">{t.duplicate_of} #{d.duplicate_of}</p>}
                  {d.possible_duplicate_of && <p className="text-xs text-amber">{t.possible_duplicate} #{d.possible_duplicate_of}</p>}
                </td>
                <td className="ltr whitespace-nowrap px-3 py-2.5 text-text-2" dir="ltr">
                  {d.edition || "—"} {d.year ? `(${d.year})` : ""}
                  {d.metadata_verified ? <span className="ms-1 text-teal-600" title={t.verify_meta}>✓</span> : null}
                </td>
                <td className="px-3 py-2.5 text-end tabular-nums text-text-2">{fmtNum(d.page_count)}</td>
                <td className="px-3 py-2.5"><StatusChip status={d.status} /></td>
                <td className="px-3 py-2.5 text-end tabular-nums text-text-2">{quality ? (d.quality_score ?? "—") : fmtSize(d.size)}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-text-2">{t.no_books}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
