"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, type Publication } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { ErrorNote } from "@/components/bits";
import { PubCard } from "@/components/Pub";

type Result = { source: string; warning: string | null; searched_at: string; total: number; items: Publication[] };
const DESIGNS = ["", "synthesis", "trials", "observational", "preliminary", "reviews"] as const;

export default function EvidencePage() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}

function Inner() {
  const { t, lang } = useI18n();
  const params = useSearchParams();
  const router = useRouter();
  const [form, setForm] = useState({
    q: params.get("q") || "",
    from: params.get("from") || "",
    to: params.get("to") || "",
    oa: params.get("oa") === "1",
    preprints: params.get("pre") === "1",
    all: params.get("all") === "1",
    design: params.get("design") || "",
  });
  const [res, setRes] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const key = params.toString();
  useEffect(() => {
    const q = params.get("q");
    if (!q || q.trim().length < 2) return;
    const p = new URLSearchParams({ q, limit: "100" });
    if (params.get("from")) p.set("date_from", params.get("from")!);
    if (params.get("to")) p.set("date_to", params.get("to")!);
    if (params.get("oa") === "1") p.set("oa", "true");
    if (params.get("pre") === "1") p.set("preprints", "true");
    if (params.get("all") === "1") p.set("fields", "all");
    if (params.get("design")) p.set("design", params.get("design")!);
    setLoading(true);
    setErr(null);
    api<Result>(`/literature/search?${p}`)
      .then(setRes)
      .catch((e) => (setErr(e.message), setRes(null)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const p = new URLSearchParams({ q: form.q.trim() });
    if (form.from) p.set("from", form.from);
    if (form.to) p.set("to", form.to);
    if (form.oa) p.set("oa", "1");
    if (form.preprints) p.set("pre", "1");
    if (form.all) p.set("all", "1");
    if (form.design) p.set("design", form.design);
    router.push(`/evidence?${p}`);
  };
  const set = (k: keyof typeof form, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="h1">{t.evidence_title}</h1>
      <p className="mt-1 max-w-read text-sm text-text-2">{t.evidence_hint}</p>
      <form onSubmit={submit} className="mt-5 space-y-3" role="search">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input ltr flex-1 py-3" dir="ltr" value={form.q} onChange={(e) => set("q", e.target.value)}
            placeholder='"chronic subdural hematoma" AND (embolization OR "middle meningeal artery")' />
          <button className="btn-primary px-6 py-3" disabled={form.q.trim().length < 2 || loading}>{loading ? "…" : t.search}</button>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2">{t.date_from}<input type="date" className="input w-40 py-1" value={form.from} onChange={(e) => set("from", e.target.value)} /></label>
          <label className="flex items-center gap-2">{t.date_to}<input type="date" className="input w-40 py-1" value={form.to} onChange={(e) => set("to", e.target.value)} /></label>
          <select className="input w-72 py-1.5" value={form.design} onChange={(e) => set("design", e.target.value)} aria-label="design">
            {DESIGNS.map((d) => <option key={d} value={d}>{t[(d ? `design_${d}` : "design_all") as "design_all"]}</option>)}
          </select>
          <label className="flex items-center gap-1.5"><input type="checkbox" className="h-4 w-4 accent-teal" checked={form.oa} onChange={(e) => set("oa", e.target.checked)} />{t.oa_only}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" className="h-4 w-4 accent-teal" checked={form.preprints} onChange={(e) => set("preprints", e.target.checked)} />{t.include_preprints}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" className="h-4 w-4 accent-teal" checked={form.all} onChange={(e) => set("all", e.target.checked)} />{t.all_fields}</label>
        </div>
      </form>

      {err && <div className="mt-5"><ErrorNote msg={err} /></div>}
      {res && (
        <section className="mt-6">
          <p className="text-sm text-text-2">
            <strong className="text-ink">{fmtNum(res.total)}</strong> {t.results} · {t.searched_with} {res.source} · {fmtDateTime(res.searched_at, lang)}
          </p>
          {res.warning && <p className="mt-1 text-sm text-amber">{res.warning}</p>}
          <div className="mt-3 space-y-3">
            {res.items.map((p) => (
              <PubCard key={p.id} p={p} onChange={(np) => setRes((r) => (r ? { ...r, items: r.items.map((i) => (i.id === np.id ? { ...i, ...np } : i)) } : r))} />
            ))}
          </div>
          <p className="mt-6 max-w-read text-xs text-text-3">{t.design_note}</p>
        </section>
      )}
    </div>
  );
}
