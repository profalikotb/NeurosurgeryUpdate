"use client";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { api, type Citation, type Doc, originalFile, pageImage } from "@/lib/api";
import { docTitle, fmtDateTime, fmtNum } from "@/lib/format";
import { srcLabel, useI18n } from "@/lib/i18n";
import { ErrorNote, PageBadge, StatusChip } from "@/components/bits";

type PageData = { page_index: number; page_count: number; renderable: boolean; text: string; citation: Citation };

export default function DocumentPage() {
  return (
    <Suspense>
      <Viewer />
    </Suspense>
  );
}

function Viewer() {
  const { t, lang } = useI18n();
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const pageIndex = Math.max(0, Number(params.get("page") || 0));
  const hl = useMemo(() => (params.get("hl") || "").split("|").filter(Boolean), [params]);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [page, setPage] = useState<PageData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [printed, setPrinted] = useState("");
  const [showToc, setShowToc] = useState(false);

  const loadDoc = useCallback(() => api<Doc>(`/documents/${id}`).then(setDoc).catch((e) => setErr(e.message)), [id]);
  useEffect(() => {
    loadDoc();
  }, [loadDoc]);
  useEffect(() => {
    setPage(null);
    api<PageData>(`/documents/${id}/pages/${pageIndex}`)
      .then((p) => (setPage(p), setErr(null)))
      .catch((e) => setErr(e.message));
  }, [id, pageIndex]);

  const goto = (i: number) => {
    const p = new URLSearchParams(params.toString());
    p.set("page", String(i));
    router.replace(`/documents/${id}?${p}`, { scroll: false });
  };
  const jumpPrinted = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!printed.trim()) return;
    const r = await api<{ matches: { page_index: number }[] }>(`/documents/${id}/resolve-page?printed=${encodeURIComponent(printed.trim())}`);
    if (r.matches.length) goto(r.matches[0].page_index);
    else setErr(lang === "ar" ? `لا توجد صفحة مطبوعة برقم ${printed}` : `No page is labelled ${printed} in this book.`);
  };

  const count = doc?.page_count || page?.page_count || 0;
  // PDF line breaks are layout, not meaning: join wrapped lines, keep paragraph breaks.
  const highlighted = useMemo(() => highlightText((page?.text || "").replace(/([^\n])\n(?!\n)/g, "$1 "), hl), [page?.text, hl]);

  return (
    <div className="mx-auto max-w-7xl">
      {doc && (
        <header className="flex flex-wrap items-start gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <h1 className="ltr h1 text-xl sm:text-2xl" dir="ltr">
              {docTitle(doc)}
            </h1>
            <p className="ltr mt-1 truncate text-xs text-text-3" dir="ltr" title={doc.path}>
              {doc.source === "gdrive" ? `Google Drive · ${doc.filename}` : doc.path}
            </p>
          </div>
          <StatusChip status={doc.status} />
        </header>
      )}
      {err && <div className="mt-4"><ErrorNote msg={err} /></div>}

      <div className="no-print mt-5 flex flex-wrap items-center gap-2">
        <button className="btn-ghost" disabled={pageIndex <= 0} onClick={() => goto(pageIndex - 1)}>
          {t.prev}
        </button>
        <span className="px-2 text-sm tabular-nums text-text-2">
          PDF {pageIndex + 1} / {fmtNum(count)}
        </span>
        <button className="btn-ghost" disabled={!count || pageIndex >= count - 1} onClick={() => goto(pageIndex + 1)}>
          {t.next}
        </button>
        <form onSubmit={jumpPrinted} className="flex items-center gap-2">
          <input className="input w-24 py-1.5" value={printed} onChange={(e) => setPrinted(e.target.value)} placeholder="p." aria-label={t.go_printed} />
          <button className="btn-ghost">{t.go_printed}</button>
        </form>
        {doc?.toc?.length ? (
          <button className="btn-ghost" onClick={() => setShowToc((s) => !s)} aria-expanded={showToc}>
            {t.contents}
          </button>
        ) : null}
        {doc?.uploaded && (
          <button className="btn-danger" onClick={async () => {
            if (!confirm(t.delete_book_confirm)) return;
            try {
              await api(`/library/upload/${doc.id}`, { method: "DELETE" });
              router.push("/library");
            } catch (e) {
              setErr((e as Error).message);
            }
          }}>
            {t.delete_book}
          </button>
        )}
        <span className="flex-1" />
        {doc && doc.web_link ? (
          <a className="btn-primary" href={doc.web_link} target="_blank" rel="noreferrer">
            {t.open_in_drive}
          </a>
        ) : doc && doc.exists_on_disk ? (
          <a className="btn-primary" href={originalFile(doc.id, doc.ext === ".pdf" ? pageIndex : undefined)} target="_blank" rel="noreferrer">
            {t.open_original}
          </a>
        ) : null}
      </div>

      {showToc && doc?.toc && (
        <nav className="panel mt-3 max-h-80 overflow-y-auto p-3" aria-label={t.contents}>
          <ul className="ltr text-sm" dir="ltr">
            {doc.toc.map((e, i) => (
              <li key={i} style={{ paddingInlineStart: `${(e.level - 1) * 14}px` }}>
                <button className={`w-full truncate rounded px-2 py-1 text-start hover:bg-surface ${e.start_page <= pageIndex && pageIndex <= e.end_page ? "text-deep font-medium" : ""}`} onClick={() => goto(e.start_page)}>
                  {e.title}
                  <span className="ms-2 text-xs text-text-3">PDF {e.start_page + 1}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {page?.renderable !== false && (
          <figure className="panel min-w-0 overflow-hidden bg-surface p-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img key={pageIndex} src={pageImage(Number(id), pageIndex, hl)} alt={`${t.page_image} PDF ${pageIndex + 1}`} className="mx-auto w-full max-w-[820px] bg-white shadow-sm" />
          </figure>
        )}
        <div className="min-w-0 space-y-4">
          {page && (
            <section className="panel p-5">
              <div className="ltr flex flex-wrap items-center gap-2 text-sm" dir="ltr">
                <PageBadge c={page.citation} />
                {page.citation.chapter && <span className="text-text-2">{page.citation.chapter}</span>}
                {page.citation.section && <span className="text-text-3">{page.citation.section}</span>}
              </div>
              <p className="ltr mt-3 rounded-md bg-surface px-3 py-2 font-serif text-sm leading-relaxed" dir="ltr">
                {page.citation.formatted}
              </p>
              <h2 className="mt-4 text-sm font-semibold text-text-2">{t.page_text}</h2>
              <div className="passage ltr mt-2 max-h-[60vh] overflow-y-auto whitespace-pre-line text-[0.98rem]" dir="ltr">
                {highlighted}
              </div>
            </section>
          )}
          {doc && <MetaEditor doc={doc} onSaved={loadDoc} />}
          {doc?.quality_notes && (
            <section className="panel p-5 text-sm">
              <h2 className="font-semibold text-text-2">{t.notes}</h2>
              <ul className="mt-2 list-disc space-y-1 ps-5 text-text-2">
                {doc.quality_notes.split("\n").map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-text-3">
                {fmtNum(doc.page_count)} pages · {fmtNum(doc.chunk_count)} passages · {fmtDateTime(doc.indexed_at, lang)}
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function highlightText(text: string, terms: string[]): React.ReactNode {
  const ts = terms.filter((x) => x.length >= 3);
  if (!ts.length) return text;
  const re = new RegExp(`(${ts.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

const FIELDS = ["title", "authors", "edition", "year", "publisher", "isbn"] as const;

function MetaEditor({ doc, onSaved }: { doc: Doc; onSaved: () => void }) {
  const { t, lang } = useI18n();
  const [vals, setVals] = useState<Record<string, string>>({});
  const [verified, setVerified] = useState(!!doc.metadata_verified);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setVals(Object.fromEntries(FIELDS.map((f) => [f, doc[f] == null ? "" : String(doc[f])])));
    setVerified(!!doc.metadata_verified);
  }, [doc]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("saving");
    setErr(null);
    const body: Record<string, unknown> = { metadata_verified: verified };
    for (const f of FIELDS) {
      const orig = doc[f] == null ? "" : String(doc[f]);
      if (vals[f] !== orig) body[f] = f === "year" ? (vals[f] ? Number(vals[f]) : null) : vals[f];
    }
    try {
      await api(`/documents/${doc.id}`, { method: "PATCH", json: body });
      setState("saved");
      onSaved();
      setTimeout(() => setState("idle"), 1500);
    } catch (e) {
      setErr((e as Error).message);
      setState("idle");
    }
  };

  return (
    <form onSubmit={save} className="panel p-5">
      <h2 className="h2 text-base">{t.metadata}</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => {
          const src = doc[`${f}_src` as keyof Doc] as string | null;
          return (
            <label key={f} className={f === "title" || f === "authors" ? "sm:col-span-2" : ""}>
              <span className="flex items-baseline justify-between text-xs text-text-2">
                {t[f]}
                {src && (
                  <span className={src === "user" ? "text-teal-600" : "text-text-3"}>
                    {t.source_of}: {srcLabel[lang][src] || src}
                  </span>
                )}
              </span>
              <input className="input ltr mt-1 py-1.5" dir="ltr" value={vals[f] || ""} inputMode={f === "year" ? "numeric" : undefined}
                onChange={(e) => setVals((v) => ({ ...v, [f]: e.target.value }))} />
            </label>
          );
        })}
      </div>
      <label className="mt-4 flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1 h-4 w-4 accent-teal" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
        {t.verify_meta}
      </label>
      {err && <div className="mt-3"><ErrorNote msg={err} /></div>}
      <button className="btn-primary mt-4" disabled={state === "saving"}>
        {state === "saved" ? t.saved : t.save}
      </button>
    </form>
  );
}
