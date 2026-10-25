"use client";
import Link from "next/link";
import { useState } from "react";
import { api, type Publication } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const LEVEL_STYLE: Record<number, string> = {
  1: "bg-teal-50 text-teal-600",
  2: "bg-deep-50 text-deep",
  3: "bg-deep-50 text-deep-600",
  4: "bg-surface text-text-2",
  5: "bg-surface text-text-2",
};

const STOP = new Set("a an and the of in on for with to from versus vs by at as is are or its their after during under".split(" "));
function keyTerms(title: string): string {
  return title
    .replace(/[^\p{L}\p{N}\s-]/gu, " ")
    .split(/\s+/)
    .filter((w) => w.length > 3 && !STOP.has(w.toLowerCase()))
    .slice(0, 6)
    .join(" ");
}

export function PubCard({ p, onChange }: { p: Publication; onChange?: (p: Publication) => void }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const link = p.links.doi || p.links.pubmed || p.links.pmc || p.links.europepmc || undefined;

  const patch = async (body: Record<string, boolean>) => {
    setBusy("patch");
    try {
      onChange?.(await api<Publication>(`/literature/publications/${p.id}`, { method: "PATCH", json: body }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const addToLibrary = async () => {
    setBusy("lib");
    setErr(null);
    try {
      const r = await api<{ path: string }>(`/literature/publications/${p.id}/add-to-library`, { method: "POST" });
      onChange?.({ ...p, library_path: r.path, saved: 1 });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className={`panel p-4 sm:p-5 ${p.retracted ? "border-danger/40" : ""}`}>
      <div className="ltr flex flex-wrap items-center gap-1.5 text-xs" dir="ltr">
        {p.retracted ? <span className="chip bg-danger-50 text-danger">{t.retracted}</span> : null}
        {p.design && (
          <span className={`chip ${p.level ? LEVEL_STYLE[p.level] : "bg-surface text-text-2"}`} title={p.design_basis || undefined}>
            {p.design}
            {p.level ? <span className="font-normal opacity-75"> · {t.level} {p.level}</span> : null}
          </span>
        )}
        {p.is_oa ? <span className="chip bg-teal-50 text-teal-600">{t.open_access}</span> : null}
        {!p.reviewed ? <span className="chip bg-amber-50 text-amber">{t.new_badge}</span> : null}
        {p.topics?.map((tp) => (
          <span key={tp} className="chip bg-surface text-text-3">{tp}</span>
        ))}
      </div>
      <h3 className="ltr mt-2 text-[1.02rem] font-semibold leading-snug text-ink" dir="ltr">
        {link ? (
          <a href={link} target="_blank" rel="noreferrer" className="hover:text-deep hover:underline">{p.title}</a>
        ) : p.title}
      </h3>
      <p className="ltr mt-1 text-sm text-text-2" dir="ltr">
        {p.journal && <span className="font-medium text-text">{p.journal}</span>}
        {p.pub_date && <span> · {fmtDate(p.pub_date)}</span>}
        {p.authors && <span className="text-text-3"> · {p.authors.length > 120 ? `${p.authors.slice(0, 120)}…` : p.authors}</span>}
      </p>
      <details className="mt-2 group">
        <summary className="cursor-pointer text-sm text-deep hover:underline">{t.abstract}</summary>
        <p className="passage ltr mt-2 text-[0.97rem]" dir="ltr">{p.abstract || t.no_abstract}</p>
      </details>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="ltr text-text-3" dir="ltr">
          {p.pmid && <>PMID {p.pmid} </>}
          {p.doi && <>· DOI {p.doi}</>}
        </span>
        <span className="flex-1" />
        {p.links.pubmed && <a className="btn-ghost px-2.5 py-1 text-xs" href={p.links.pubmed} target="_blank" rel="noreferrer">PubMed</a>}
        {p.links.doi && <a className="btn-ghost px-2.5 py-1 text-xs" href={p.links.doi} target="_blank" rel="noreferrer">DOI</a>}
        {p.is_oa && p.links.pmc ? <a className="btn-ghost px-2.5 py-1 text-xs" href={p.links.pmc} target="_blank" rel="noreferrer">{t.full_text}</a> : null}
        <Link className="btn-ghost px-2.5 py-1 text-xs" href={`/search?q=${encodeURIComponent(keyTerms(p.title))}`}>{t.search_books_topic}</Link>
        {p.is_oa && p.oa_pdf_url ? (
          p.library_path ? (
            <span className="chip bg-teal-50 text-teal-600">{t.added_library}</span>
          ) : (
            <button className="btn-teal px-2.5 py-1 text-xs" disabled={busy !== null} onClick={addToLibrary}>
              {busy === "lib" ? "…" : t.add_library}
            </button>
          )
        ) : null}
        <button className="btn-primary px-2.5 py-1 text-xs" disabled={busy !== null} onClick={() => patch({ reviewed: !p.reviewed })}>
          {p.reviewed ? t.reviewed : t.mark_reviewed}
        </button>
      </div>
      {err && <p className="mt-2 text-xs text-danger">{err}</p>}
    </article>
  );
}
