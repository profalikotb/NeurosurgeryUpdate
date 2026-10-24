"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Status } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type NavKey =
  | "nav_dashboard" | "nav_library" | "nav_search" | "nav_chat" | "nav_approaches" | "nav_mcq" | "nav_essay"
  | "nav_viva" | "nav_cases" | "nav_lecture" | "nav_evidence" | "nav_saved" | "nav_collection" | "nav_settings";

const NAV: { key: NavKey; href?: string; phase: number }[] = [
  { key: "nav_dashboard", href: "/", phase: 1 },
  { key: "nav_library", href: "/library", phase: 1 },
  { key: "nav_search", href: "/search", phase: 1 },
  { key: "nav_chat", phase: 2 },
  { key: "nav_mcq", phase: 2 },
  { key: "nav_essay", phase: 2 },
  { key: "nav_viva", phase: 2 },
  { key: "nav_approaches", phase: 3 },
  { key: "nav_cases", phase: 3 },
  { key: "nav_evidence", phase: 4 },
  { key: "nav_lecture", phase: 5 },
  { key: "nav_saved", phase: 5 },
  { key: "nav_collection", phase: 5 },
  { key: "nav_settings", phase: 6 },
];

function Mark() {
  // Monogram: a coronal arc (cortex) over a vertical line (neuraxis).
  return (
    <svg viewBox="0 0 40 40" className="h-9 w-9 shrink-0" aria-hidden>
      <rect width="40" height="40" rx="9" fill="#163A6B" />
      <path d="M9 22c0-7 5-12 11-12s11 5 11 12" fill="none" stroke="#5FD3C9" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M14 21c0-4 3-6.5 6-6.5s6 2.5 6 6.5" fill="none" stroke="#fff" strokeOpacity=".55" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M20 21v10" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const { t, toggle, lang } = useI18n();
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [down, setDown] = useState<string | null>(null);

  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Status>("/status")
        .then((s) => alive && (setStatus(s), setDown(null)))
        .catch((e: Error) => alive && setDown(e.message || "unreachable"));
    load();
    const id = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const active = (href?: string) => (href === "/" ? path === "/" : !!href && path.startsWith(href));

  const sidebar = (
    <div className="flex h-full flex-col bg-ink text-white/85">
      <Link href="/" className="flex items-center gap-3 px-5 pb-5 pt-6">
        <Mark />
        <div className="min-w-0 leading-tight">
          <div className="text-[0.95rem] font-semibold text-white">{t.owner}</div>
          <div className="truncate text-xs text-white/60">{t.appName}</div>
        </div>
      </Link>
      <nav className="flex-1 overflow-y-auto px-3 pb-4" aria-label="Main">
        <ul className="space-y-0.5">
          {NAV.map((n, i) => {
            const prev = NAV[i - 1];
            const groupBreak = prev && prev.phase !== n.phase;
            const label = t[n.key];
            return (
              <li key={n.key} className={groupBreak ? "mt-3 border-t border-white/10 pt-3" : ""}>
                {n.href ? (
                  <Link
                    href={n.href}
                    aria-current={active(n.href) ? "page" : undefined}
                    className={`block rounded-md px-3 py-2 text-sm transition-colors ${
                      active(n.href) ? "bg-white/10 font-medium text-white" : "hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {label}
                  </Link>
                ) : (
                  <span
                    className="flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-white/40"
                    title={`${t.arrives_in} ${n.phase}`}
                  >
                    <span>{label}</span>
                    <span className="text-[0.7rem] text-white/35">
                      {t.phase} {n.phase}
                    </span>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="space-y-1.5 border-t border-white/10 px-5 py-4 text-xs text-white/55">
        {down ? (
          <div className="text-[#F3A49E]">
            <p>{t.backend_down}</p>
            <p className="mt-1 text-white/55">{down}</p>
          </div>
        ) : status ? (
          <>
            <p className="flex items-center gap-2">
              <Dot on={status.ocr_available} /> {status.ocr_available ? t.ocr_on : t.ocr_off}
            </p>
            <p className="flex items-center gap-2">
              <Dot on={status.semantic_enabled} /> {status.semantic_enabled ? t.sem_on : t.sem_off}
            </p>
            <p className="text-white/35">v{status.version}</p>
          </>
        ) : null}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <button className="absolute inset-0 bg-ink/50" aria-label="Close menu" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 start-0 w-72 shadow-xl">{sidebar}</div>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="no-print sticky top-0 z-30 flex items-center gap-3 border-b border-rule bg-white/90 px-4 py-2.5 backdrop-blur sm:px-8">
          <button className="btn-ghost px-2.5 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden>
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
          <p className="hidden min-w-0 flex-1 truncate text-xs text-text-2 sm:block">{t.subtitle}</p>
          <span className="flex-1 sm:hidden" />
          <button className="btn-ghost px-3 py-1.5" onClick={toggle} lang={lang === "en" ? "ar" : "en"}>
            {t.language}
          </button>
        </header>
        <main className="px-4 py-6 sm:px-8 sm:py-8">{children}</main>
      </div>
    </div>
  );
}

function Dot({ on }: { on: boolean }) {
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${on ? "bg-[#5FD3C9]" : "bg-white/30"}`} aria-hidden />;
}
