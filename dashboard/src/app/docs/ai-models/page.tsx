import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Models – ClinicAI Docs",
  description: "Compare supported AI models and choose the right one for your clinic.",
};

interface Model {
  vendor: string;
  model: string;
  bestFor: string;
  speed: "Very Fast" | "Fast" | "Moderate";
  cost: "Low" | "Medium" | "High";
  notes?: string;
}

const models: Model[] = [
  {
    vendor: "Groq",
    model: "LLaMA 3.3 70B",
    bestFor: "High-volume clinics, Hinglish-heavy patient bases",
    speed: "Very Fast",
    cost: "Low",
    notes: "Fastest inference available. Excellent Hinglish understanding. Best cost-per-token ratio.",
  },
  {
    vendor: "Anthropic",
    model: "Claude Sonnet",
    bestFor: "Clinical accuracy, complex SOAP note generation",
    speed: "Moderate",
    cost: "Medium",
    notes: "Highest clinical reasoning quality. Best SOAP note fidelity. Recommended for specialist clinics.",
  },
  {
    vendor: "OpenAI",
    model: "GPT-4o",
    bestFor: "General-purpose use, mixed workloads",
    speed: "Fast",
    cost: "Medium",
    notes: "Balanced across speed, cost, and quality. Strong function-calling for structured extraction.",
  },
  {
    vendor: "Google",
    model: "Gemini 2.5 Flash",
    bestFor: "Multilingual clinics, regional language support",
    speed: "Fast",
    cost: "Low",
    notes: "Best support for regional South Asian languages beyond Hinglish. Strong multimodal for lab report OCR.",
  },
];

function SpeedBadge({ speed }: { speed: Model["speed"] }) {
  const classes: Record<Model["speed"], string> = {
    "Very Fast": "bg-emerald-50 text-emerald-700 border-emerald-200",
    Fast: "bg-blue-50 text-blue-700 border-blue-200",
    Moderate: "bg-amber-50 text-amber-700 border-amber-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${classes[speed]}`}
    >
      {speed}
    </span>
  );
}

function CostBadge({ cost }: { cost: Model["cost"] }) {
  const classes: Record<Model["cost"], string> = {
    Low: "bg-emerald-50 text-emerald-700 border-emerald-200",
    Medium: "bg-amber-50 text-amber-700 border-amber-200",
    High: "bg-red-50 text-red-700 border-red-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${classes[cost]}`}
    >
      {cost}
    </span>
  );
}

export default function AiModelsPage() {
  return (
    <article>
      <h1 className="text-2xl font-bold text-zinc-900 mb-2">AI Models</h1>
      <p className="text-zinc-500 text-sm mb-8">
        ClinicAI supports four LLM providers. You can switch models at any time
        in <strong>Settings → AI Model</strong> without affecting existing
        patient records.
      </p>

      {/* Comparison table */}
      <div className="overflow-x-auto mb-10">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-zinc-200">
              <th className="py-3 pr-4 text-left font-semibold text-zinc-700 whitespace-nowrap">
                Vendor
              </th>
              <th className="py-3 pr-4 text-left font-semibold text-zinc-700 whitespace-nowrap">
                Model
              </th>
              <th className="py-3 pr-4 text-left font-semibold text-zinc-700">
                Best for
              </th>
              <th className="py-3 pr-4 text-left font-semibold text-zinc-700 whitespace-nowrap">
                Speed
              </th>
              <th className="py-3 text-left font-semibold text-zinc-700 whitespace-nowrap">
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr
                key={m.model}
                className="border-b border-zinc-100 hover:bg-zinc-50 transition-colors"
              >
                <td className="py-3 pr-4 font-medium text-zinc-900 whitespace-nowrap">
                  {m.vendor}
                </td>
                <td className="py-3 pr-4 font-mono text-xs text-zinc-700 whitespace-nowrap">
                  {m.model}
                </td>
                <td className="py-3 pr-4 text-zinc-600">{m.bestFor}</td>
                <td className="py-3 pr-4 whitespace-nowrap">
                  <SpeedBadge speed={m.speed} />
                </td>
                <td className="py-3 whitespace-nowrap">
                  <CostBadge cost={m.cost} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Detailed cards */}
      <h2 className="text-lg font-semibold text-zinc-900 mb-4">
        Model details
      </h2>
      <div className="space-y-4">
        {models.map((m) => (
          <div
            key={m.model}
            className="rounded-xl border border-zinc-200 px-5 py-4"
          >
            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-semibold text-zinc-900">
                {m.vendor} — {m.model}
              </span>
              <SpeedBadge speed={m.speed} />
              <CostBadge cost={m.cost} />
            </div>
            <p className="text-sm text-zinc-600">{m.notes}</p>
          </div>
        ))}
      </div>

      <div className="mt-10 rounded-xl border border-zinc-200 bg-zinc-50 px-5 py-4 text-sm text-zinc-600">
        <strong className="text-zinc-800">Recommendation: </strong>
        Start with <strong>Groq LLaMA 3.3 70B</strong> to evaluate response
        quality and costs. Switch to <strong>Claude Sonnet</strong> if SOAP
        note accuracy is a priority for your practice.
      </div>
    </article>
  );
}
