"use client"

import * as React from "react"
import {
  Database, Server, Zap, MessageSquare, Brain, Mic, Globe,
  CheckCircle2, TrendingUp, Shield, Clock, ChevronRight, Download
} from "lucide-react"

// ── Print styles injected at runtime ────────────────────────────────────────
const PRINT_CSS = `
@page {
  size: A4 portrait;
  margin: 14mm 12mm;
}
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  body { background: white !important; }
  .no-print { display: none !important; }
  .print-break { page-break-before: always; }
  .print-avoid-break { page-break-inside: avoid; }
}
`

// ── Types ───────────────────────────────────────────────────────────────────

interface TierRow {
  label: string
  starter: string
  growth: string
  scale: string
  note?: string
}

interface LLMRow {
  model: string
  vendor: string
  inputPer1M: string
  outputPer1M: string
  speed: string
  chosen: boolean
  verdict: string
}

// ── Data ────────────────────────────────────────────────────────────────────

const TIERS = {
  starter: { patients: "100 patients/mo", consultations: "200 consults/mo", messages: "2,000 msgs/mo" },
  growth:  { patients: "500 patients/mo", consultations: "1,000 consults/mo", messages: "10,000 msgs/mo" },
  scale:   { patients: "2,000 patients/mo", consultations: "4,000 consults/mo", messages: "40,000 msgs/mo" },
}

const COST_ROWS: TierRow[] = [
  { label: "Groq LLaMA 3.3 70B (LLM)", starter: "$0.40", growth: "$2.00", scale: "$8.00", note: "$0.59/M input · $0.79/M output" },
  { label: "Groq Whisper Turbo (STT)", starter: "$0.20", growth: "$1.00", scale: "$4.00", note: "$0.04/hr audio · avg 3 min/consult" },
  { label: "Meta WhatsApp Cloud API", starter: "$7", growth: "$34", scale: "$136", note: "$0.0034/msg · Meta fees only, no middleman" },
  { label: "PostgreSQL — Neon", starter: "$0", growth: "$5", scale: "$19", note: "Free tier: 100 CU-hrs, 0.5 GB · Launch: $0.106/CU-hr" },
  { label: "Redis — Upstash", starter: "$0", growth: "$0", scale: "$10", note: "Free: 500K cmds/mo · Pay-as-you-go after" },
  { label: "API Hosting — Railway", starter: "$5", growth: "$10", scale: "$25", note: "Hobby $5/mo · auto-scales with usage" },
  { label: "Dashboard — Vercel", starter: "$0", growth: "$0", scale: "$20", note: "Hobby (free) covers most clinics · Pro $20/mo" },
]

const TOTALS = { starter: "$13", growth: "$52", scale: "$222" }
const PER_PATIENT = { starter: "$0.13", growth: "$0.10", scale: "$0.11" }

const LLM_COMPARISON: LLMRow[] = [
  { model: "LLaMA 3.3 70B", vendor: "Groq", inputPer1M: "$0.59", outputPer1M: "$0.79", speed: "~300 tok/s", chosen: true, verdict: "Best value. Fast, Hinglish-capable, production-stable." },
  { model: "Gemini 2.5 Flash", vendor: "Google", inputPer1M: "$0.30", outputPer1M: "$2.50", speed: "~200 tok/s", chosen: false, verdict: "Cheaper input but 3× costlier output. Good fallback." },
  { model: "Claude Sonnet 4.6", vendor: "Anthropic", inputPer1M: "$3.00", outputPer1M: "$15.00", speed: "~120 tok/s", chosen: false, verdict: "Highest clinical accuracy. 20× costlier — enterprise only." },
  { model: "GPT-4o", vendor: "OpenAI", inputPer1M: "$2.50", outputPer1M: "$10.00", speed: "~100 tok/s", chosen: false, verdict: "Premium quality, premium price. Not justified at this scale." },
]

const STACK_ITEMS = [
  { icon: Brain, title: "Groq — LLaMA 3.3 70B", role: "Primary LLM", why: "Fastest inference (~300 tok/s). 10× cheaper than GPT-4o. Excellent Hinglish support for Indian clinics. Production SLA available.", cost: "$0.59 / $0.79 per 1M tokens", color: "from-orange-500/20 to-orange-600/5", badge: "bg-orange-500/15 text-orange-400" },
  { icon: Mic, title: "Groq Whisper Turbo", role: "Speech-to-Text", why: "2.8× cheaper than standard Whisper v3 ($0.04 vs $0.111/hr). Same Groq infra — no added latency. Handles doctor accent variability well.", cost: "$0.04 per audio hour", color: "from-violet-500/20 to-violet-600/5", badge: "bg-violet-500/15 text-violet-400" },
  { icon: MessageSquare, title: "Meta WhatsApp Cloud API", role: "Messaging Layer", why: "Direct Meta integration — no Twilio middleman. $0.0034/msg vs $0.0084/msg with Twilio. Same reliability, 60% cheaper. Production SLA from Meta.", cost: "$0.0034 per message", color: "from-green-500/20 to-green-600/5", badge: "bg-green-500/15 text-green-400" },
  { icon: Database, title: "Neon — PostgreSQL", role: "Primary Database", why: "Serverless Postgres with scale-to-zero. Free tier handles early clinics. 30× cheaper than AWS RDS at equivalent spec. Branching for dev/staging.", cost: "Free → $19/mo", color: "from-emerald-500/20 to-emerald-600/5", badge: "bg-emerald-500/15 text-emerald-400" },
  { icon: Zap, title: "Upstash — Redis", role: "Session Cache", why: "Pay-per-request pricing eliminates idle cost. 500K commands/month free — sufficient for 500+ patients. Serverless, no provisioning.", cost: "Free → $0.20/100K cmds", color: "from-yellow-500/20 to-yellow-600/5", badge: "bg-yellow-500/15 text-yellow-400" },
  { icon: Server, title: "Railway — API Hosting", role: "Backend Deployment", why: "Zero-config Python deployment. $5/mo Hobby handles ~500 patients. Scales linearly. 5× cheaper than comparable AWS EC2.", cost: "$5–$25/mo", color: "from-blue-500/20 to-blue-600/5", badge: "bg-blue-500/15 text-blue-400" },
  { icon: Globe, title: "Vercel — Dashboard", role: "Next.js Hosting", why: "First-class Next.js host. Edge CDN globally. Free tier serves unlimited clinics. Pro ($20/mo) only needed for >1M page views.", cost: "Free → $20/mo", color: "from-slate-500/20 to-slate-600/5", badge: "bg-slate-500/15 text-slate-400" },
]

// ── Helpers ─────────────────────────────────────────────────────────────────

function TierBadge({ label, sub }: { label: string; sub: string }) {
  return (
    <div className="text-center">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground print:text-gray-600">{label}</div>
      <div className="mt-0.5 text-[10px] text-muted-foreground/60 print:text-gray-400">{sub}</div>
    </div>
  )
}

function CostCell({ value }: { value: string }) {
  return (
    <td className="py-2.5 px-3 text-center text-sm tabular-nums text-muted-foreground print:text-gray-700">
      {value}
    </td>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────

export default function StackPage() {
  // Inject print CSS once
  React.useEffect(() => {
    const el = document.createElement("style")
    el.textContent = PRINT_CSS
    document.head.appendChild(el)
    return () => { document.head.removeChild(el) }
  }, [])

  function handleDownload() {
    window.print()
  }

  return (
    <div className="min-h-screen bg-background text-foreground print:bg-white print:text-black">

      {/* ── Header ── */}
      <div className="border-b bg-muted/30 px-8 py-10 print:bg-white print:py-6 print:border-gray-200">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-start justify-between gap-4">
            <div>
              {/* print: show a clean title block */}
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground no-print">
                <span className="size-1.5 rounded-full bg-green-400" />
                Production-Ready Stack · June 2026
              </div>
              {/* print-only subtitle */}
              <p className="hidden print:block text-xs text-gray-400 mb-1 uppercase tracking-widest">ClinicAI · Production Stack &amp; Cost Estimates · June 2026</p>
              <h1 className="text-3xl font-bold tracking-tight print:text-2xl">Tech Stack &amp; Cost Estimates</h1>
              <p className="mt-2 max-w-2xl text-muted-foreground print:text-gray-500 print:text-sm">
                Every component chosen for production reliability at the lowest viable cost.
                Using Meta WhatsApp Cloud API directly — no middleware, 60% cheaper than Twilio.
              </p>
            </div>

            <div className="flex flex-col items-end gap-3">
              {/* Download button — hidden on print */}
              <button
                onClick={handleDownload}
                className="no-print inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
              >
                <Download className="size-4" />
                Download PDF
              </button>

              {/* Stat — shown on screen and print */}
              <div className="hidden shrink-0 flex-col items-end gap-1 text-right md:flex">
                <div className="text-xs text-muted-foreground print:text-gray-500">Cost per patient/mo</div>
                <div className="text-4xl font-bold text-green-400 print:text-green-700 print:text-3xl">~$0.11</div>
                <div className="text-xs text-muted-foreground print:text-gray-500">at any scale</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl space-y-12 px-8 py-10 print:space-y-8 print:py-6 print:px-0">

        {/* ── Key Insight ── */}
        <div className="print-avoid-break rounded-xl border border-amber-500/30 bg-amber-500/5 p-5 print:border-amber-300 print:bg-amber-50">
          <div className="flex items-start gap-3">
            <TrendingUp className="mt-0.5 size-5 shrink-0 text-amber-400 print:text-amber-600" />
            <div>
              <div className="font-semibold text-amber-400 print:text-amber-700">Ditching Twilio saves 60% on messaging</div>
              <p className="mt-1 text-sm text-muted-foreground print:text-gray-600">
                Meta WhatsApp Cloud API costs <strong className="text-foreground print:text-black">$0.0034/msg</strong> — no Twilio markup.
                At 10,000 messages/month that's <strong className="text-foreground print:text-black">$34</strong> vs Twilio's{" "}
                <strong className="text-foreground print:text-black">$88</strong>. The entire LLM + STT bill for 1,000 consultations is still only ~$2.40.
              </p>
            </div>
          </div>
        </div>

        {/* ── Monthly Cost by Tier ── */}
        <section className="print-avoid-break">
          <h2 className="mb-1 text-xl font-semibold print:text-lg">Monthly Cost by Tier</h2>
          <p className="mb-4 text-sm text-muted-foreground print:text-gray-500">All prices in USD. Based on June 2026 published rates.</p>

          <div className="overflow-hidden rounded-xl border print:border-gray-300">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 print:bg-gray-50">
                  <th className="py-3 pl-4 pr-3 text-left font-medium text-muted-foreground print:text-gray-600">Service</th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">
                    <TierBadge label="Starter" sub={TIERS.starter.patients} />
                  </th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">
                    <TierBadge label="Growth" sub={TIERS.growth.patients} />
                  </th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">
                    <TierBadge label="Scale" sub={TIERS.scale.patients} />
                  </th>
                  <th className="py-3 pl-3 pr-4 text-left font-medium text-muted-foreground print:text-gray-600">Pricing basis</th>
                </tr>
              </thead>
              <tbody className="divide-y print:divide-gray-200">
                {COST_ROWS.map((row, i) => (
                  <tr key={i} className="hover:bg-muted/20 transition-colors print:hover:bg-transparent">
                    <td className="py-2.5 pl-4 pr-3 font-medium text-sm print:text-gray-800">{row.label}</td>
                    <CostCell value={row.starter} />
                    <CostCell value={row.growth} />
                    <CostCell value={row.scale} />
                    <td className="py-2.5 pl-3 pr-4 text-xs text-muted-foreground print:text-gray-500">{row.note}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 bg-muted/40 print:bg-gray-50 print:border-gray-300">
                  <td className="py-3 pl-4 pr-3 font-bold print:text-gray-900">Total / month</td>
                  <td className="py-3 px-3 text-center font-bold text-lg text-green-400 print:text-green-700">{TOTALS.starter}</td>
                  <td className="py-3 px-3 text-center font-bold text-lg text-green-400 print:text-green-700">{TOTALS.growth}</td>
                  <td className="py-3 px-3 text-center font-bold text-lg text-green-400 print:text-green-700">{TOTALS.scale}</td>
                  <td className="py-3 pl-3 pr-4 text-xs text-muted-foreground print:text-gray-500">excl. staff &amp; domain</td>
                </tr>
                <tr className="bg-muted/20 print:bg-white">
                  <td className="py-2 pl-4 pr-3 text-sm text-muted-foreground print:text-gray-500">Cost per patient</td>
                  <td className="py-2 px-3 text-center text-sm text-muted-foreground print:text-gray-500">{PER_PATIENT.starter}</td>
                  <td className="py-2 px-3 text-center text-sm text-muted-foreground print:text-gray-500">{PER_PATIENT.growth}</td>
                  <td className="py-2 px-3 text-center text-sm text-muted-foreground print:text-gray-500">{PER_PATIENT.scale}</td>
                  <td className="py-2 pl-3 pr-4 text-xs text-muted-foreground print:text-gray-400">remarkably flat</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>

        {/* ── LLM Comparison — page break before on print ── */}
        <section className="print-break print-avoid-break">
          <h2 className="mb-1 text-xl font-semibold print:text-lg">LLM Selection — Why Groq</h2>
          <p className="mb-4 text-sm text-muted-foreground print:text-gray-500">Per-clinic model override available via dashboard. All models reachable at runtime.</p>

          <div className="overflow-hidden rounded-xl border print:border-gray-300">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40 print:bg-gray-50">
                  <th className="py-3 pl-4 pr-3 text-left font-medium text-muted-foreground print:text-gray-600">Model</th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">Input / 1M tok</th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">Output / 1M tok</th>
                  <th className="px-3 py-3 text-center font-medium text-muted-foreground print:text-gray-600">Speed</th>
                  <th className="py-3 pl-3 pr-4 text-left font-medium text-muted-foreground print:text-gray-600">Verdict</th>
                </tr>
              </thead>
              <tbody className="divide-y print:divide-gray-200">
                {LLM_COMPARISON.map((row, i) => (
                  <tr
                    key={i}
                    className={`transition-colors ${row.chosen ? "bg-green-500/5 print:bg-green-50" : "hover:bg-muted/20 print:hover:bg-transparent"}`}
                  >
                    <td className="py-3 pl-4 pr-3">
                      <div className="flex items-center gap-2">
                        {row.chosen
                          ? <CheckCircle2 className="size-4 shrink-0 text-green-400 print:text-green-600" />
                          : <div className="size-4 shrink-0" />
                        }
                        <div>
                          <div className="font-medium print:text-gray-900">{row.model}</div>
                          <div className="text-xs text-muted-foreground print:text-gray-500">{row.vendor}</div>
                        </div>
                        {row.chosen && (
                          <span className="ml-1 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-semibold text-green-400 print:bg-green-100 print:text-green-700">
                            SELECTED
                          </span>
                        )}
                      </div>
                    </td>
                    <td className={`py-3 px-3 text-center tabular-nums ${row.chosen ? "font-semibold text-green-400 print:text-green-700" : "text-muted-foreground print:text-gray-600"}`}>
                      {row.inputPer1M}
                    </td>
                    <td className={`py-3 px-3 text-center tabular-nums ${row.chosen ? "font-semibold text-green-400 print:text-green-700" : "text-muted-foreground print:text-gray-600"}`}>
                      {row.outputPer1M}
                    </td>
                    <td className="py-3 px-3 text-center text-muted-foreground print:text-gray-600">{row.speed}</td>
                    <td className="py-3 pl-3 pr-4 text-xs text-muted-foreground print:text-gray-500">{row.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ── Stack Cards ── */}
        <section>
          <h2 className="mb-1 text-xl font-semibold print:text-lg">Stack Rationale</h2>
          <p className="mb-4 text-sm text-muted-foreground print:text-gray-500">Every component has a cheaper alternative that was evaluated and rejected — with a documented reason.</p>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 print:grid-cols-3 print:gap-3">
            {STACK_ITEMS.map((item, i) => (
              <div
                key={i}
                className={`print-avoid-break rounded-xl border bg-gradient-to-br p-5 print:border-gray-200 print:bg-gray-50 print:p-4 ${item.color}`}
              >
                <div className="mb-3 flex items-start justify-between">
                  <item.icon className="size-5 text-foreground/70 print:text-gray-500" />
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${item.badge} print:bg-gray-200 print:text-gray-600`}>
                    {item.role}
                  </span>
                </div>
                <div className="mb-1 font-semibold text-sm print:text-gray-900">{item.title}</div>
                <div className="mb-3 text-xs text-muted-foreground leading-relaxed print:text-gray-600">{item.why}</div>
                <div className="mt-auto border-t border-white/10 pt-3 text-xs font-medium tabular-nums print:border-gray-200 print:text-gray-700">
                  {item.cost}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ── Assumptions ── */}
        <section className="print-break print-avoid-break">
          <h2 className="mb-4 text-xl font-semibold print:text-lg">Estimate Assumptions</h2>
          <div className="grid gap-4 sm:grid-cols-3 print:gap-3">
            {[
              {
                tier: "Starter",
                items: ["100 patients/month", "200 consultations/month", "~2,000 WhatsApp messages @ $0.0034", "~2 min avg voice note/consult", "~4,000 tokens avg per consult", "Neon free tier (0 DB cost)", "Upstash free tier (0 Redis cost)", "Vercel Hobby (0 dashboard cost)"],
              },
              {
                tier: "Growth",
                items: ["500 patients/month", "1,000 consultations/month", "~10,000 WhatsApp messages", "~2.5 min avg voice note", "~4,000 tokens avg per consult", "Neon Launch plan", "Upstash pay-as-you-go", "Railway Hobby + burst"],
              },
              {
                tier: "Scale",
                items: ["2,000 patients/month", "4,000 consultations/month", "~40,000 WhatsApp messages", "~3 min avg voice note", "~4,500 tokens avg per consult", "Neon Launch plan (5 GB)", "Upstash fixed plan", "Railway Pro + Vercel Pro"],
              },
            ].map((t) => (
              <div key={t.tier} className="rounded-xl border bg-muted/20 p-5 print:border-gray-200 print:bg-gray-50 print:p-4">
                <div className="mb-3 font-semibold print:text-gray-900">{t.tier} Tier</div>
                <ul className="space-y-1.5">
                  {t.items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground print:text-gray-600">
                      <ChevronRight className="mt-0.5 size-3 shrink-0 text-muted-foreground/50 print:text-gray-400" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* ── Reliability ── */}
        <section className="print-avoid-break rounded-xl border bg-muted/20 p-6 print:border-gray-200 print:bg-gray-50 print:p-5">
          <div className="flex items-start gap-3">
            <Shield className="mt-0.5 size-5 shrink-0 text-blue-400 print:text-blue-600" />
            <div className="w-full">
              <h2 className="font-semibold print:text-gray-900">Production Reliability Notes</h2>
              <div className="mt-3 grid gap-3 text-sm text-muted-foreground sm:grid-cols-2 print:text-gray-600 print:text-xs">
                {[
                  { icon: CheckCircle2, text: "Groq has 99.9% SLA on paid plans. Gemini 2.5 Flash is configured as automatic fallback — zero manual intervention on LLM outage." },
                  { icon: CheckCircle2, text: "Neon scales to zero preventing idle costs, and supports read replicas for high-read workloads at no architectural change." },
                  { icon: CheckCircle2, text: "Railway restarts crashed containers automatically. Zero-downtime deploys via built-in blue/green when using a Pro plan." },
                  { icon: Clock, text: "APScheduler jobs are in-process only — restart loses pending reminders. Migrating to Upstash QStash ($0 free tier) is the recommended fix." },
                  { icon: CheckCircle2, text: "All API keys encrypted with Fernet (AES-128-CBC) before PostgreSQL storage. Keys never returned in API responses." },
                  { icon: Shield, text: "Twilio webhook signature validation should be added before production to prevent fake message injection." },
                ].map((note, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <note.icon className="mt-0.5 size-3.5 shrink-0 text-blue-400 print:text-blue-600" />
                    <span>{note.text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ── Footer ── */}
        <div className="border-t pt-6 text-xs text-muted-foreground text-center print:text-gray-400">
          Prices based on publicly published rates as of June 2026.
          Meta WhatsApp rates subject to regional variation — India utility rate: $0.0034/msg.
          Volume discounts available from Groq and Meta at enterprise tier. No Twilio fees.
          <span className="no-print"> · <button onClick={handleDownload} className="underline hover:text-foreground transition-colors">Download as PDF</button></span>
        </div>

      </div>
    </div>
  )
}
