"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Stats } from "@/lib/api";
import { docTitle, fmtDate, fmtDateTime, fmtNum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { ErrorNote } from "@/components/bits";

export default function Dashboard() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Stats>("/stats").then(setStats).catch((e) => setErr(e.message));
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim().length >= 2) router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  };

  return (
    <div className="mx-auto max-w-6xl">
      <section className="rounded-xl bg-ink px-5 py-8 text-white sm:px-10 sm:py-10">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t.appName}</h1>
        <p className="mt-2 max-w-read text-sm text-white/65">{t.subtitle}</p>
        <form onSubmit={submit} className="mt-7 flex flex-col gap-2 sm:flex-row" role="search">
          <label htmlFor="q" className="sr-only">
            {t.ask_books}
          </label>
          <input
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t.ask_placeholder}
            className="min-w-0 flex-1 rounded-md border border-white/15 bg-white px-4 py-3 text-base text-text placeholder:text-text-3 focus:outline-none focus:ring-2 focus:ring-[#5FD3C9]"
            dir="auto"
          />
          <button className="btn-teal px-6 py-3 text-base" disabled={q.trim().length < 2}>
            {t.ask_books}
          </button>
        </form>
      </section>

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <ModulePanel title={t.btn1} desc={t.btn1_desc} phase={2} href="/search" readyLabel={t.nav_search} />
        <ModulePanel title={t.btn2} desc={t.btn2_desc} href="/updates" readyLabel={t.open_updates}
          note={stats && stats.new_publications ? `${fmtNum(stats.new_publications)} ${t.new_since}` : undefined} />
      </section>

      {err && <div className="mt-6"><ErrorNote msg={`${t.backend_down} ${err}`} /></div>}

      {stats && (
        <section className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.3fr]">
          <div className="panel min-w-0 p-5">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
              <Stat label={t.indexed_books} value={fmtNum(stats.indexed_documents)} />
              <Stat label={t.pages} value={fmtNum(stats.pages)} />
              <Stat label={t.verified_meta} value={`${fmtNum(stats.verified_metadata)} / ${fmtNum(stats.indexed_documents)}`} />
              <Stat label={t.added_week} value={fmtNum(stats.added_last_7_days)} />
            </dl>
            <p className="mt-5 border-t border-rule pt-3 text-xs text-text-2">
              {t.last_scan}: {fmtDateTime(stats.last_scan_at, lang)}
            </p>
          </div>
          <div className="panel min-w-0 p-5">
            <h2 className="h2">{t.recent_books}</h2>
            {stats.recent.length ? (
              <ul className="mt-3 divide-y divide-rule">
                {stats.recent.map((d) => (
                  <li key={d.id} className="flex items-baseline gap-3 py-2.5">
                    <Link href={`/documents/${d.id}`} className="ltr min-w-0 flex-1 truncate text-sm hover:text-deep" dir="ltr">
                      {docTitle(d)}
                    </Link>
                    <span className="shrink-0 text-xs text-text-3">
                      {fmtNum(d.page_count)} {lang === "ar" ? "ص" : "pp"} · {fmtDate(d.indexed_at)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-3">
                <p className="text-sm text-text-2">{t.no_books}</p>
                <Link href="/library" className="btn-primary mt-4">
                  {t.go_library}
                </Link>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function ModulePanel({ title, desc, phase, href, readyLabel, note }: { title: string; desc: string; phase?: number; href?: string; readyLabel?: string; note?: string }) {
  const { t } = useI18n();
  return (
    <div className="panel flex min-w-0 flex-col border-s-4 border-s-deep p-6">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      <p className="mt-2 flex-1 text-sm text-text-2">{desc}</p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {href && readyLabel && (
          <Link href={href} className="btn-primary">
            {readyLabel}
          </Link>
        )}
        {note && <span className="chip bg-amber-50 text-amber">{note}</span>}
        {phase && (
          <span className="text-xs text-text-3">
            {t.arrives_in} {phase}
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-text-2">{label}</dt>
      <dd className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{value}</dd>
    </div>
  );
}
