"use client";
import Link from "next/link";
import { useState } from "react";
import { type Citation, pageImage } from "@/lib/api";
import { statusLabel, useI18n } from "@/lib/i18n";

const OPEN = "";
const CLOSE = "";

/** Renders backend snippets: text is escaped by React; only our private-use markers become <mark>. */
export function Snippet({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest.length) {
    const a = rest.indexOf(OPEN);
    if (a === -1) {
      parts.push(rest);
      break;
    }
    const b = rest.indexOf(CLOSE, a);
    parts.push(rest.slice(0, a));
    parts.push(<mark key={k++}>{rest.slice(a + 1, b === -1 ? undefined : b)}</mark>);
    rest = b === -1 ? "" : rest.slice(b + 1);
  }
  return <>{parts}</>;
}

const STATUS_STYLE: Record<string, string> = {
  indexed: "bg-teal-50 text-teal-600",
  partial: "bg-amber-50 text-amber",
  ocr_needed: "bg-amber-50 text-amber",
  duplicate: "bg-deep-50 text-deep",
  pending: "bg-deep-50 text-deep",
  missing: "bg-danger-50 text-danger",
  error: "bg-danger-50 text-danger",
  skipped: "bg-surface text-text-2",
};

export function StatusChip({ status }: { status: string }) {
  const { lang } = useI18n();
  return <span className={`chip ${STATUS_STYLE[status] || "bg-surface"}`}>{statusLabel[lang][status] || status}</span>;
}

/** The printed-page badge states where the page number came from. */
export function PageBadge({ c }: { c: Citation }) {
  const { t, lang } = useI18n();
  if (c.reflowable)
    return (
      <span className="chip bg-deep-50 text-deep">
        {lang === "ar" ? "قسم" : "Section"} {c.pdf_page}
      </span>
    );
  if (c.printed_page)
    return (
      <span
        className={`chip ${c.printed_page_source === "inferred" ? "bg-amber-50 text-amber" : "bg-teal-50 text-teal-600"}`}
        title={c.printed_page_source === "inferred" ? t.printed_inferred : t.printed_embedded}
      >
        p. {c.printed_page}
        {c.printed_page_source === "inferred" && "*"}
        <span className="font-normal opacity-70">· PDF {c.pdf_page}</span>
      </span>
    );
  return (
    <span className="chip bg-surface text-text-2" title={t.printed_none}>
      PDF p. {c.pdf_page}
    </span>
  );
}

export function CitationSlip({ c, terms, snippet, match }: { c: Citation; terms: string[]; snippet: string; match?: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const href = `/documents/${c.document_id}?page=${c.page_index}${terms.length ? `&hl=${encodeURIComponent(terms.join("|"))}` : ""}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(c.formatted);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <article className="panel flex gap-4 p-4 sm:p-5">
      {!c.reflowable && (
        <Link href={href} className="hidden shrink-0 sm:block" aria-label={t.view_passage}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={pageImage(c.document_id, c.page_index, terms, 60)}
            alt=""
            loading="lazy"
            className="h-[148px] w-[106px] rounded border border-rule bg-surface object-cover object-top"
          />
        </Link>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="ltr min-w-0 truncate text-[0.98rem] font-semibold text-ink" dir="ltr">
            {c.title || c.filename}
          </h3>
          {c.edition && <span className="ltr text-sm text-text-2">{c.edition} ed.</span>}
          {c.year && <span className="text-sm text-text-2">{c.year}</span>}
        </div>
        <div className="ltr mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-2" dir="ltr">
          <PageBadge c={c} />
          {c.chapter && <span className="truncate">{c.chapter}</span>}
          {c.section && c.section !== c.chapter && <span className="truncate text-text-3">{c.section}</span>}
        </div>
        <p className="passage mt-3 line-clamp-5" dir="ltr">
          <Snippet text={snippet} />
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {!c.metadata_verified && <span className="chip bg-amber-50 text-amber">{t.meta_unverified}</span>}
          {c.ocr && <span className="chip bg-amber-50 text-amber">{t.ocr_text}</span>}
          {match && (
            <span className="chip bg-surface text-text-2">
              {match === "all_terms" ? t.all_terms : match === "some_terms" ? t.some_terms : t.semantic}
            </span>
          )}
          <span className="flex-1" />
          <button className="btn-ghost px-2.5 py-1 text-xs" onClick={copy}>
            {copied ? t.copied : t.copy_citation}
          </button>
          <Link href={href} className="btn-teal px-2.5 py-1 text-xs">
            {t.view_passage}
          </Link>
        </div>
      </div>
    </article>
  );
}

export function ErrorNote({ msg }: { msg: string }) {
  return <p className="rounded-md border border-danger/30 bg-danger-50 px-3 py-2 text-sm text-danger">{msg}</p>;
}
