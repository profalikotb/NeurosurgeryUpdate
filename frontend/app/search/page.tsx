"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, type Doc, type SearchResult } from "@/lib/api";
import { docTitle } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { CitationSlip, ErrorNote } from "@/components/bits";

export default function SearchPage() {
  return (
    <Suspense>
      <SearchInner />
    </Suspense>
  );
}

function SearchInner() {
  const { t } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const q0 = params.get("q") || "";
  const ids0 = params.get("docs") || "";
  const ver0 = params.get("verified") === "1";
  const [q, setQ] = useState(q0);
  const [selected, setSelected] = useState<number[]>(ids0 ? ids0.split(",").map(Number) : []);
  const [verified, setVerified] = useState(ver0);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [books, setBooks] = useState<Doc[]>([]);

  useEffect(() => {
    api<{ items: Doc[] }>("/documents?status=indexed,partial,ocr_needed&limit=2000")
      .then((r) => setBooks(r.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    setQ(q0);
    if (q0.trim().length < 2) {
      setRes(null);
      return;
    }
    const p = new URLSearchParams({ q: q0, limit: "30" });
    if (ids0) p.set("doc_ids", ids0);
    if (ver0) p.set("verified_only", "true");
    setLoading(true);
    setErr(null);
    api<SearchResult>(`/search?${p}`)
      .then(setRes)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [q0, ids0, ver0]);

  const go = (e?: React.FormEvent) => {
    e?.preventDefault();
    const p = new URLSearchParams({ q: q.trim() });
    if (selected.length) p.set("docs", selected.join(","));
    if (verified) p.set("verified", "1");
    router.push(`/search?${p}`);
  };

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="h1">{t.nav_search}</h1>
      <form onSubmit={go} className="mt-5 space-y-3" role="search">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input flex-1 py-3" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t.ask_placeholder} dir="auto" aria-label={t.search} />
          <button className="btn-primary px-6 py-3" disabled={q.trim().length < 2}>
            {t.search}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <BookPicker books={books} selected={selected} onChange={setSelected} />
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} className="h-4 w-4 accent-teal" />
            {t.verified_only}
          </label>
        </div>
      </form>

      {err && <div className="mt-6"><ErrorNote msg={err} /></div>}
      {loading && <p className="mt-6 text-sm text-text-2">…</p>}

      {res && !loading && (
        <section className="mt-6" aria-live="polite">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-text-2">
            <span>
              <strong className="text-ink">{res.hits.length}</strong> {t.results_for}
            </span>
            {res.expanded_terms.some((g) => g.length > 1) && (
              <span className="ltr" dir="ltr">
                {t.expanded}: {res.expanded_terms.filter((g) => g.length > 1).map((g) => g.join(" / ")).join("; ")}
              </span>
            )}
            {res.semantic_error && <span className="text-amber">semantic: {res.semantic_error}</span>}
          </div>
          {res.hits.length === 0 ? (
            <p className="panel mt-4 p-5 text-sm">{t.no_hits}</p>
          ) : (
            <div className="mt-4 space-y-3">
              {res.hits.map((h) => (
                <CitationSlip key={h.chunk_id} c={h.citation} snippet={h.snippet} terms={res.highlight_terms} match={h.match} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function BookPicker({ books, selected, onChange }: { books: Doc[]; selected: number[]; onChange: (v: number[]) => void }) {
  const { t } = useI18n();
  const [filter, setFilter] = useState("");
  const shown = useMemo(
    () => books.filter((b) => docTitle(b).toLowerCase().includes(filter.toLowerCase())).slice(0, 200),
    [books, filter],
  );
  return (
    <details className="relative">
      <summary className="btn-ghost cursor-pointer list-none py-1.5">
        {t.filter_books}: {selected.length ? selected.length : t.all_books}
      </summary>
      <div className="absolute start-0 z-20 mt-2 w-[min(28rem,90vw)] rounded-lg border border-rule bg-white p-3 shadow-lg">
        <input className="input py-1.5 text-sm" placeholder={t.find_doc} value={filter} onChange={(e) => setFilter(e.target.value)} />
        <ul className="mt-2 max-h-72 overflow-y-auto">
          {shown.map((b) => (
            <li key={b.id}>
              <label className="flex items-start gap-2 rounded px-1.5 py-1.5 text-sm hover:bg-surface">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-teal"
                  checked={selected.includes(b.id)}
                  onChange={(e) => onChange(e.target.checked ? [...selected, b.id] : selected.filter((x) => x !== b.id))}
                />
                <span className="ltr" dir="ltr">
                  {docTitle(b)}
                  {b.edition && <span className="text-text-3"> ({b.edition} ed.)</span>}
                </span>
              </label>
            </li>
          ))}
        </ul>
        {selected.length > 0 && (
          <button type="button" className="mt-2 text-xs text-deep underline" onClick={() => onChange([])}>
            {t.all_books}
          </button>
        )}
      </div>
    </details>
  );
}
