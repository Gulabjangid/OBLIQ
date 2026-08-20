"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Activity, ArrowUpRight, CalendarClock, Check, CircleDot, LockKeyhole, Mail, Play, Radar, RefreshCw, Send, ShieldCheck, TerminalSquare, X } from "lucide-react";

export interface AuditRequest { client_id: string; }
export interface AuditResponse {
  status: string;
  client_id: string;
  actions_taken: string[];
  final_message: string;
  summary?: string;
}

interface BackendComplianceResponse {
  status: string;
  data: {
    client_id: string;
    execution_log?: Array<{ tool?: string }>;
    agent_result?: {
      summary?: string;
      actions?: unknown;
      final_status?: string;
    };
  };
}

interface OverviewItem {
  client_id: string;
  client_name: string;
  email: string;
  missing_documents: string[];
  upcoming_deadlines: Array<{ event: string; date: string; days_remaining: number }>;
  overdue_deadlines: Array<{ event: string; date: string; days_remaining: number }>;
}

type TraceLine = { text: string; kind: "system" | "tool" | "success" | "error" };
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const syntheticTrace: TraceLine[] = [
  { text: "[SYS] Initializing synthetic audit trace...", kind: "system" },
  { text: "[SYS] Establishing secure link to Obliq Engine", kind: "system" },
  { text: "[THINKING] Parsing client context and policy scope", kind: "system" },
  { text: "[TOOL] Querying local compliance tool registry", kind: "tool" },
  { text: "[THINKING] Selecting evidence-backed audit actions", kind: "system" },
  { text: "[TOOL] Awaiting FastAPI compliance response...", kind: "tool" },
];

function isAuditResponse(value: unknown): value is AuditResponse {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  return typeof payload.status === "string" && typeof payload.client_id === "string" &&
    typeof payload.final_message === "string" && Array.isArray(payload.actions_taken) &&
    payload.actions_taken.every((action) => typeof action === "string");
}

function isBackendResponse(value: unknown): value is BackendComplianceResponse {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  const data = payload.data;
  return typeof payload.status === "string" && !!data && typeof data === "object" &&
    typeof (data as Record<string, unknown>).client_id === "string";
}

function normalizeAuditResponse(value: unknown): AuditResponse | null {
  if (isAuditResponse(value)) return value;
  if (!isBackendResponse(value)) return null;
  const agentResult = value.data.agent_result ?? {};
  let parsedResult: { summary?: string; actions?: unknown; final_status?: string } = agentResult;
  if (typeof agentResult.summary === "string") {
    const jsonMatch = agentResult.summary.match(/```json\s*([\s\S]*?)\s*```/);
    if (jsonMatch) {
      try {
        const candidate: unknown = JSON.parse(jsonMatch[1]);
        if (candidate && typeof candidate === "object") parsedResult = candidate as typeof parsedResult;
      } catch { /* Keep the plain summary when the model text is not valid JSON. */ }
    }
  }
  const actions = Array.isArray(parsedResult.actions) && parsedResult.actions.every((action) => typeof action === "string")
    ? parsedResult.actions as string[]
    : (value.data.execution_log ?? []).map((entry) => entry.tool).filter((tool): tool is string => typeof tool === "string");
  return {
    status: parsedResult.final_status ?? value.status,
    client_id: value.data.client_id,
    actions_taken: actions,
    final_message: parsedResult.summary ?? agentResult.summary ?? "The audit completed without a final message.",
  };
}

export default function Home() {
  const [clientId, setClientId] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [trace, setTrace] = useState<TraceLine[]>([]);
  const [result, setResult] = useState<AuditResponse | null>(null);
  const [isReminderDispatched, setIsReminderDispatched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [overview, setOverview] = useState<OverviewItem[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const terminalRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => () => {
    abortRef.current?.abort();
    timersRef.current.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
  }, [trace]);

  function stopTimers() {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  }

  function beginTrace() {
    stopTimers();
    setTrace([]);
    syntheticTrace.forEach((line, index) => {
      const timer = setTimeout(() => setTrace((current) => [...current, line]), 280 + index * 680);
      timersRef.current.push(timer);
    });
  }

  async function runAudit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedId = clientId.trim();
    if (!normalizedId) { setError("Enter a client ID to initialize the audit."); return; }
    abortRef.current?.abort();
    setIsLoading(true); setError(null); setResult(null); setIsReminderDispatched(false); beginTrace();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/compliance/check`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: normalizedId } satisfies AuditRequest), signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Audit service returned ${response.status}.`);
      const payload: unknown = await response.json();
      const normalizedPayload = normalizeAuditResponse(payload);
      if (!normalizedPayload) throw new Error("The audit service returned an invalid payload.");
      stopTimers();
      setTrace((current) => [...current, ...normalizedPayload.actions_taken.map((action) => ({ text: `[RESULT] ${action}`, kind: "success" as const })), { text: "[SYS] Task complete. Evidence returned.", kind: "success" }]);
      setResult(normalizedPayload);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      const message = caught instanceof Error ? caught.message : "Unable to reach the audit service.";
      stopTimers(); setTrace((current) => [...current, { text: `[ERROR] ${message}`, kind: "error" }]); setError(message);
    } finally { setIsLoading(false); }
  }

  async function loadOverview() {
    setOverviewLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/compliance/overview`);
      if (!response.ok) throw new Error(`Overview service returned ${response.status}.`);
      const payload: unknown = await response.json();
      if (!Array.isArray(payload)) throw new Error("The overview service returned an invalid payload.");
      setOverview(payload as OverviewItem[]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load the compliance overview.");
    } finally {
      setOverviewLoading(false);
    }
  }

  function dispatchReminder() {
    setIsReminderDispatched(true);
    window.alert("Message sent to client");
  }

  return (
    <main className="min-h-screen overflow-hidden px-4 text-slate-100 sm:px-8">
      <header className="mx-auto flex max-w-7xl items-center justify-between border-b border-blue-950/70 py-5">
        <div className="flex items-center gap-3"><div className="mark"><Radar size={19} /></div><span className="text-lg font-semibold tracking-[-0.03em]">obliq<span className="text-cyan-400">.io</span></span></div>
        <div className="flex items-center gap-2 rounded-full border border-cyan-900/50 bg-cyan-950/20 px-3 py-1.5 text-xs text-cyan-200"><span className="status-dot" /> System operational</div>
      </header>

      <div className="mx-auto max-w-7xl pb-14 pt-12 sm:pt-20">
        <section className="mb-10 max-w-3xl"><div className="eyebrow"><Activity size={14} /> COMPLIANCE OPERATIONS / LIVE CONSOLE</div><h1 className="mt-5 text-4xl font-semibold tracking-[-0.055em] text-white sm:text-6xl">Make every audit<br /><span className="text-gradient">actionable.</span></h1><p className="mt-5 max-w-xl text-base leading-7 text-slate-400">Deploy an evidence-first compliance agent against your client workspace. Observe the execution trace, then review the exact actions returned by the engine.</p></section>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <section className="glass-panel flex flex-col justify-between p-6 sm:p-8"><div><div className="mb-8 flex items-center justify-between"><div><p className="section-kicker">01 / TARGET</p><h2 className="mt-2 text-xl font-medium text-white">Initialize an audit</h2></div><LockKeyhole className="text-blue-400" size={20} /></div><form onSubmit={runAudit}><label htmlFor="client-id" className="mb-2 block text-sm text-slate-300">Client ID</label><div className="relative"><input id="client-id" value={clientId} onChange={(event) => setClientId(event.target.value)} disabled={isLoading} placeholder="e.g. 102" className="field pr-12" autoComplete="off" /><span className="absolute right-4 top-1/2 -translate-y-1/2 font-mono text-xs text-slate-600">ID</span></div><button type="submit" disabled={isLoading} className="primary-button mt-4 w-full"><Play size={16} fill="currentColor" />{isLoading ? "Agent running..." : "Initialize agent"}<ArrowUpRight size={16} className="ml-auto" /></button></form><button type="button" onClick={loadOverview} disabled={overviewLoading} className="secondary-button mt-3 w-full"><RefreshCw size={15} className={overviewLoading ? "animate-spin" : ""} />{overviewLoading ? "Scanning all clients..." : "Scan all clients"}<CalendarClock size={15} className="ml-auto" /></button>{error && <div role="alert" className="mt-4 flex gap-2 rounded-lg border border-rose-900/70 bg-rose-950/30 p-3 text-sm text-rose-200"><X size={16} className="mt-0.5 shrink-0" />{error}</div>}</div><div className="mt-12 border-t border-white/5 pt-5 text-xs text-slate-500"><div className="flex items-center justify-between"><span>ENGINE</span><span className="font-mono text-slate-300">obliq-compliance-v1</span></div><div className="mt-3 flex items-center justify-between"><span>TRANSPORT</span><span className="font-mono text-cyan-400">LOCAL / SECURE</span></div></div></section>
          <section className="terminal-shell"><div className="flex items-center justify-between border-b border-blue-950/80 px-5 py-4"><div className="flex items-center gap-3"><div className="window-dots"><i /><i /><i /></div><span className="font-mono text-xs text-slate-500">agent_trace.log</span></div><div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-slate-600"><TerminalSquare size={14} /> {isLoading ? "Streaming" : "Standby"}</div></div><div ref={terminalRef} className="terminal-body" aria-live="polite">{trace.length === 0 ? <div className="flex h-full items-center justify-center text-center font-mono text-xs text-slate-700"><div><CircleDot size={18} className="mx-auto mb-3" /><p>Awaiting initialization...</p><p className="mt-1">Synthetic status traces appear here.</p></div></div> : trace.map((line, index) => <div key={`${line.text}-${index}`} className={`trace-line ${line.kind}`}><span className="mr-3 opacity-40">{String(index + 1).padStart(2, "0")}</span>{line.text}</div>)}{isLoading && <div className="trace-line tool"><span className="mr-3 opacity-40">··</span><span className="cursor-blink">█</span></div>}</div></section>
        </div>
        {overview.length > 0 && <section className="outcome-panel mt-5"><div className="flex flex-wrap items-end justify-between gap-4"><div><p className="section-kicker text-cyan-400">BULK MONITOR / 30 DAY WINDOW</p><h2 className="mt-2 text-2xl font-medium text-white">Clients needing attention</h2></div><div className="font-mono text-xs text-slate-400">{overview.length} affected clients</div></div><div className="mt-6 grid gap-3">{overview.map((item) => <article key={item.client_id} className="overview-row"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-cyan-400">#{item.client_id}</span><h3 className="font-medium text-white">{item.client_name}</h3></div><p className="mt-1 truncate text-xs text-slate-500">{item.email}</p></div><div className="flex flex-wrap gap-2 text-xs">{item.missing_documents.length > 0 && <span className="metric-pill danger">{item.missing_documents.length} missing docs</span>}{item.overdue_deadlines.length > 0 && <span className="metric-pill danger">{item.overdue_deadlines.length} overdue</span>}{item.upcoming_deadlines.length > 0 && <span className="metric-pill warning">{item.upcoming_deadlines.length} upcoming</span>}</div><div className="mt-3 border-t border-white/5 pt-3 text-xs text-slate-500">{item.missing_documents.length > 0 && <p><span className="text-slate-300">Missing:</span> {item.missing_documents.join(", ")}</p>}{[...item.overdue_deadlines, ...item.upcoming_deadlines].map((deadline) => <p key={`${item.client_id}-${deadline.event}-${deadline.date}`} className="mt-1"><span className={deadline.days_remaining < 0 ? "text-rose-300" : "text-amber-300"}>{deadline.days_remaining < 0 ? "Overdue" : `Due in ${deadline.days_remaining}d`}:</span> {deadline.event} ({deadline.date})</p>)}</div></article>)}</div></section>}
        {result && <section className="outcome-panel mt-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="section-kicker text-cyan-400">02 / OUTCOME</p><h2 className="mt-2 text-2xl font-medium text-white">Audit complete</h2></div><div className="flex items-center gap-2 rounded-full border border-cyan-800/50 bg-cyan-950/30 px-3 py-1.5 text-xs text-cyan-300"><ShieldCheck size={15} /> {result.status}</div></div><div className="mt-6 overflow-hidden rounded-xl border border-cyan-900/60 bg-slate-950/75 shadow-2xl shadow-cyan-950/20 backdrop-blur-xl"><div className="flex items-center gap-3 border-b border-white/10 bg-white/[0.03] px-5 py-4"><Mail size={17} className="text-cyan-400" /><div><p className="section-kicker text-cyan-400">DRAFTED REMINDER</p><p className="mt-1 text-xs text-slate-500">Mock email client</p></div></div><div className="space-y-3 px-5 py-5 text-sm"><div className="flex gap-3"><span className="w-16 shrink-0 font-mono text-[11px] text-slate-500">TO:</span><span className="text-slate-200">Client {result.client_id}</span></div><div className="flex gap-3"><span className="w-16 shrink-0 font-mono text-[11px] text-slate-500">SUBJECT:</span><span className="text-slate-200">Compliance reminder for client {result.client_id}</span></div><div className="mt-4 border-t border-white/10 pt-5"><p className="whitespace-pre-wrap leading-7 text-slate-300">{result.final_message}</p></div></div><div className="border-t border-white/10 bg-black/20 px-5 py-4"><button type="button" onClick={dispatchReminder} disabled={isReminderDispatched} className="primary-button w-full sm:w-auto"><>{isReminderDispatched ? <Check size={16} /> : <Send size={16} />}</>{isReminderDispatched ? "Reminder dispatched" : "Approve & Dispatch Reminder"}</button></div></div>{result.summary && <p className="mt-3 text-sm text-slate-500">{result.summary}</p>}<div className="mt-8 border-t border-white/5 pt-6"><p className="section-kicker">EXECUTED ACTIONS</p><div className="mt-4 grid gap-3 sm:grid-cols-2">{result.actions_taken.map((action, index) => <div key={`${action}-${index}`} className="flex items-center gap-3 rounded-lg border border-blue-950/80 bg-black/20 px-4 py-3 text-sm text-slate-300"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-cyan-500/10 text-cyan-400"><Check size={14} /></span>{action}</div>)}</div></div></section>}
      </div>
    </main>
  );
}
