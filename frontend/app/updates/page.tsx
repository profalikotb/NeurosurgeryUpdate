"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type Publication, type SearchRun, type Topic } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { ErrorNote } from "@/components/bits";
import { PubCard } from "@/components/Pub";

type Feed = {
  total: number;
  items: Publication[];
  window_from: string;
  last_ok: SearchRun | null;
  last_error: SearchRun | null;
  run_state: { running: boolean; current: string | null; done: number; total: number; last_finished: string | null };
};

const WINDOWS = [
  { days: 1, key: "window_day" },
  { days: 7, key: "window_week" },
  { days: 30, key: "window_month" },
  { days: 90, key: "window_quarter" },
  { days: 365, key: "window_year" },
] as const;
const DESIGNS = ["", "synthesis", "trials", "observational", "preliminary", "reviews"] as const;

export default function UpdatesPage() {
  const { t, lang } = useI18n();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topicId, setTopicId] = useState<number | null>(null);
  const [days, setDays] = useState(30);
  const [design, setDesign] = useState("");
  const [oa, setOa] = useState(false);
  const [unreviewed, setUnreviewed] = useState(false);
  const [text, setText] = useState("");
  const [feed, setFeed] = useState<Feed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [checks, setChecks] = useState<{ source: string; ok: boolean; detail: string; ms: number }[] | null>(null);
  const [tick, setTick] = useState(0);

  const loadTopics = useCallback(() => api<Topic[]>("/literature/topics").then(setTopics).catch((e) => setErr(e.message)), []);
  useEffect(() => {
    loadTopics();
  }, [loadTopics, tick]);

  useEffect(() => {
    const p = new URLSearchParams({ days: String(days), limit: "100" });
    if (topicId) p.set("topic_id", String(topicId));
    if (design) p.set("design", design);
    if (oa) p.set("oa", "true");
    if (unreviewed) p.set("unreviewed", "true");
    if (text.trim()) p.set("text", text.trim());
    const h = setTimeout(() => api<Feed>(`/literature/feed?${p}`).then((f) => (setFeed(f), setErr(null))).catch((e) => setErr(e.message)), 150);
    return () => clearTimeout(h);
  }, [topicId, days, design, oa, unreviewed, text, tick]);

  // While a background update runs, refresh every few seconds.
  const running = feed?.run_state.running;
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((x) => x + 1), 4000);
    return () => clearInterval(id);
  }, [running]);

  const updateNow = async () => {
    setErr(null);
    try {
      if (topicId) {
        await api(`/literature/topics/${topicId}/run`, { method: "POST" });
      } else {
        await api("/literature/run", { method: "POST" });
      }
      setTick((x) => x + 1);
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const checkConnection = async () => {
    setChecks(null);
    try {
      setChecks(await api("/literature/selftest"));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const markShown = async () => {
    if (!feed) return;
    const ids = feed.items.filter((i) => !i.reviewed).map((i) => i.id);
    if (!ids.length) return;
    await api("/literature/publications/mark-reviewed", { method: "POST", json: { ids } }).catch(() => {});
    setTick((x) => x + 1);
  };
  const replace = (p: Publication) =>
    setFeed((f) => (f ? { ...f, items: f.items.map((i) => (i.id === p.id ? { ...i, ...p, topics: i.topics } : i)) } : f));

  const unrevTotal = topics.reduce((a, b) => a + (b.unreviewed || 0), 0);
  const rs = feed?.run_state;

  return (
    <div className="mx-auto max-w-6xl">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="h1">{t.nav_updates}</h1>
          <p className="mt-1 text-xs text-text-2">{t.lit_sources}</p>
          <p className="mt-0.5 text-xs text-text-3">
            {t.last_update}: {fmtDateTime(feed?.last_ok?.finished_at, lang)}
            {feed?.last_ok?.source ? ` (${feed.last_ok.source})` : ""}
          </p>
          {feed?.last_error && (
            <p className="mt-0.5 text-xs text-danger">
              {fmtDateTime(feed.last_error.started_at, lang)}: {feed.last_error.error}
            </p>
          )}
        </div>
        <button className="btn-ghost" onClick={checkConnection}>{t.check_connection}</button>
        <button className="btn-primary" onClick={updateNow} disabled={!!running}>
          {running ? `${t.updating} ${rs?.done}/${rs?.total}` : t.update_now}
        </button>
      </div>
      {checks && (
        <div className="panel mt-3 flex flex-wrap gap-x-6 gap-y-1 px-4 py-2.5 text-sm">
          {checks.map((c) => (
            <span key={c.source} className={c.ok ? "text-teal-600" : "text-danger"}>
              {c.ok ? "✓" : "✕"} {c.source}: {c.ok ? `${t.connection_ok} (${c.ms} ms)` : c.detail}
            </span>
          ))}
        </div>
      )}
      {err && <div className="mt-3"><ErrorNote msg={err} /></div>}

      <div className="-mx-4 mt-5 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0" role="tablist" aria-label={t.topics_manage}>
        <TopicChip active={topicId === null} onClick={() => setTopicId(null)} label={t.all_topics} count={unrevTotal} />
        {topics.filter((x) => x.enabled).map((tp) => (
          <TopicChip key={tp.id} active={topicId === tp.id} onClick={() => setTopicId(tp.id)} label={tp.name} count={tp.unreviewed || 0}
            error={tp.last_status === "error"} />
        ))}
      </div>

      <div className="mt-4 flex flex-col gap-2 lg:flex-row lg:items-center">
        <div className="flex shrink-0 overflow-x-auto rounded-md border border-rule bg-white text-sm">
          {WINDOWS.map((w) => (
            <button key={w.days} onClick={() => setDays(w.days)} className={`whitespace-nowrap px-3 py-1.5 ${days === w.days ? "bg-deep text-white" : "hover:bg-surface"}`}>
              {t[w.key]}
            </button>
          ))}
        </div>
        <select className="input py-1.5 lg:w-72" value={design} onChange={(e) => setDesign(e.target.value)} aria-label="design">
          {DESIGNS.map((d) => (
            <option key={d} value={d}>{t[(d ? `design_${d}` : "design_all") as "design_all"]}</option>
          ))}
        </select>
        <input className="input min-w-0 py-1.5 lg:flex-1" placeholder={t.filter_text} value={text} onChange={(e) => setText(e.target.value)} dir="auto" />
        <label className="flex items-center gap-1.5 whitespace-nowrap text-sm"><input type="checkbox" className="h-4 w-4 accent-teal" checked={oa} onChange={(e) => setOa(e.target.checked)} />{t.oa_only}</label>
        <label className="flex items-center gap-1.5 whitespace-nowrap text-sm"><input type="checkbox" className="h-4 w-4 accent-teal" checked={unreviewed} onChange={(e) => setUnreviewed(e.target.checked)} />{t.unreviewed_only}</label>
      </div>

      <div className="mt-4 flex items-baseline gap-3 text-sm text-text-2">
        <span><strong className="text-ink">{fmtNum(feed?.total)}</strong> {t.results}</span>
        <span className="flex-1" />
        {feed && feed.items.some((i) => !i.reviewed) && (
          <button className="text-deep underline" onClick={markShown}>{t.mark_page_reviewed}</button>
        )}
      </div>

      <div className="mt-3 space-y-3">
        {feed && feed.items.length === 0 && <p className="panel p-5 text-sm text-text-2">{t.no_updates}</p>}
        {feed?.items.map((p) => <PubCard key={p.id} p={p} onChange={replace} />)}
      </div>

      <p className="mt-6 max-w-read text-xs text-text-3">{t.design_note}</p>

      <TopicsPanel topics={topics} onChange={() => setTick((x) => x + 1)} />
      <RunLog tick={tick} />
    </div>
  );
}

function TopicChip({ active, onClick, label, count, error }: { active: boolean; onClick: () => void; label: string; count: number; error?: boolean }) {
  return (
    <button role="tab" aria-selected={active} onClick={onClick}
      className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-sm transition-colors ${active ? "border-deep bg-deep text-white" : "border-rule bg-white hover:border-deep/40"} ${error ? "border-danger/50" : ""}`}>
      {label}
      {count > 0 && <span className={`ms-1.5 rounded-full px-1.5 text-xs ${active ? "bg-white/20" : "bg-amber-50 text-amber"}`}>{count}</span>}
    </button>
  );
}

function TopicsPanel({ topics, onChange }: { topics: Topic[]; onChange: () => void }) {
  const { t, lang } = useI18n();
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/literature/topics", { method: "POST", json: { name, query } });
      setName("");
      setQuery("");
      onChange();
    } catch (e2) {
      setErr((e2 as Error).message);
    }
  };
  return (
    <details className="panel mt-6 p-5">
      <summary className="cursor-pointer font-semibold text-ink">{t.topics_manage} ({topics.length})</summary>
      <ul className="mt-3 divide-y divide-rule">
        {topics.map((tp) => <TopicRow key={tp.id} tp={tp} onChange={onChange} lang={lang} />)}
      </ul>
      <form onSubmit={add} className="mt-4 grid gap-2 sm:grid-cols-[14rem_1fr_auto]">
        <input className="input py-1.5" placeholder={t.topic_name} value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input ltr py-1.5" dir="ltr" placeholder={t.topic_query} value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="btn-primary" disabled={name.trim().length < 2 || query.trim().length < 2}>{t.add_topic}</button>
      </form>
      {err && <div className="mt-2"><ErrorNote msg={err} /></div>}
    </details>
  );
}

function TopicRow({ tp, onChange, lang }: { tp: Topic; onChange: () => void; lang: "en" | "ar" }) {
  const { t } = useI18n();
  const [q, setQ] = useState(tp.query);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const save = async () => {
    await api(`/literature/topics/${tp.id}`, { method: "PATCH", json: { query: q } });
    onChange();
  };
  const run = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api<{ found: number; new: number; source: string }>(`/literature/topics/${tp.id}/run`, { method: "POST" });
      setMsg(`${r.source}: ${r.found} found, ${r.new} new`);
      onChange();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" className="h-4 w-4 accent-teal" checked={!!tp.enabled}
            onChange={async (e) => { await api(`/literature/topics/${tp.id}`, { method: "PATCH", json: { enabled: e.target.checked } }); onChange(); }} />
          {tp.name}
        </label>
        <span className="text-xs text-text-3">{fmtNum(tp.total)} · {fmtDateTime(tp.last_run_at, lang)}</span>
        {tp.last_status === "error" && <span className="text-xs text-danger">{tp.last_error}</span>}
        <span className="flex-1" />
        <button className="btn-ghost px-2.5 py-1 text-xs" disabled={busy} onClick={run}>{busy ? "…" : t.run_topic}</button>
        <button className="btn-danger px-2.5 py-1 text-xs" onClick={async () => { if (confirm(`${t.delete_topic}: ${tp.name}?`)) { await api(`/literature/topics/${tp.id}`, { method: "DELETE" }); onChange(); } }}>
          {t.delete_topic}
        </button>
      </div>
      <div className="mt-2 flex gap-2">
        <input className="input ltr py-1 text-sm" dir="ltr" value={q} onChange={(e) => setQ(e.target.value)} />
        {q !== tp.query && <button className="btn-primary px-3 py-1 text-xs" onClick={save}>{t.save_topic}</button>}
      </div>
      {msg && <p className="mt-1 text-xs text-text-2">{msg}</p>}
    </li>
  );
}

function RunLog({ tick }: { tick: number }) {
  const { t, lang } = useI18n();
  const [runs, setRuns] = useState<SearchRun[]>([]);
  useEffect(() => {
    api<SearchRun[]>("/literature/runs?limit=25").then(setRuns).catch(() => {});
  }, [tick]);
  return (
    <details className="panel mt-3 p-5">
      <summary className="cursor-pointer font-semibold text-ink">{t.run_log}</summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <tbody className="divide-y divide-rule">
            {runs.map((r) => (
              <tr key={r.id} className="align-top">
                <td className="whitespace-nowrap py-2 pe-3 text-text-2">{fmtDateTime(r.started_at, lang)}</td>
                <td className="py-2 pe-3">{r.topic || <span className="ltr" dir="ltr">“{r.query.slice(0, 60)}”</span>}</td>
                <td className="py-2 pe-3 text-text-2">{r.source || "—"}</td>
                <td className="py-2 pe-3 tabular-nums">{r.status === "ok" ? `${r.found ?? 0} / ${r.new ?? "—"}` : ""}</td>
                <td className={`py-2 text-xs ${r.status === "error" ? "text-danger" : "text-text-3"}`}>{r.error || r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
