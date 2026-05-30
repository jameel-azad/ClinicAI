import type { Metadata } from "next";
import Link from "next/link";
import {
  Calendar,
  Mic,
  FileText,
  Users,
  Activity,
  Moon,
  ArrowRight,
  MessageCircle,
  Cpu,
  CheckCircle,
} from "lucide-react";

export const metadata: Metadata = {
  title: "ClinicAI – WhatsApp-first AI for your clinic",
  description:
    "Automate appointment booking, clinical scribing, lab parsing, and more — all over WhatsApp.",
};

const features = [
  {
    icon: Calendar,
    title: "Appointment Booking",
    description:
      "Patients book slots over WhatsApp in plain language. Doctors approve with a single tap.",
  },
  {
    icon: Mic,
    title: "Clinical Scribe",
    description:
      "Voice notes auto-transcribed and structured into SOAP notes. Review and approve in seconds.",
  },
  {
    icon: FileText,
    title: "Lab Report Parsing",
    description:
      "Patients send PDFs directly in WhatsApp. ClinicAI extracts key values and attaches them to the patient record.",
  },
  {
    icon: Users,
    title: "Multi-Doctor Support",
    description:
      "Invite your entire team. Each doctor receives their own appointment queue and notification stream.",
  },
  {
    icon: Activity,
    title: "FHIR R4 Coding",
    description:
      "Diagnoses and prescriptions are automatically coded to ICD-10 and SNOMED CT for FHIR R4 export.",
  },
  {
    icon: Moon,
    title: "After-Hours Queue",
    description:
      "Patients who message outside clinic hours are queued and notified automatically at opening time.",
  },
];

const steps = [
  {
    icon: MessageCircle,
    number: "01",
    title: "Patient WhatsApps",
    description:
      "Patient sends any message to the clinic number — booking request, symptom description, or lab PDF.",
  },
  {
    icon: Cpu,
    number: "02",
    title: "AI Understands & Routes",
    description:
      "ClinicAI understands English and Hinglish, extracts intent, and routes to the right doctor.",
  },
  {
    icon: CheckCircle,
    number: "03",
    title: "Doctor Approves",
    description:
      "Doctor receives a WhatsApp with quick-reply buttons. One tap confirms the appointment or SOAP note.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex flex-col min-h-screen bg-white">
      {/* Nav */}
      <header className="border-b border-zinc-100 px-6 py-4 flex items-center justify-between max-w-6xl mx-auto w-full">
        <span className="font-bold text-zinc-900 text-lg tracking-tight">
          ClinicAI
        </span>
        <nav className="flex items-center gap-6 text-sm text-zinc-600">
          <Link href="/docs" className="hover:text-zinc-900 transition-colors">
            Docs
          </Link>
          <Link
            href="/auth/login"
            className="hover:text-zinc-900 transition-colors"
          >
            Log in
          </Link>
          <Link
            href="/auth/signup"
            className="rounded-lg bg-zinc-900 px-4 py-1.5 text-white hover:bg-zinc-700 transition-colors"
          >
            Get started
          </Link>
        </nav>
      </header>

      <main className="flex-1">
        {/* Hero */}
        <section className="px-6 pt-24 pb-20 text-center max-w-4xl mx-auto">
          <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-zinc-50 px-4 py-1.5 text-xs font-medium text-zinc-600 mb-8">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Now with FHIR R4 &amp; SNOMED CT support
          </div>
          <h1 className="text-5xl font-bold text-zinc-900 tracking-tight leading-tight mb-6">
            WhatsApp-first AI
            <br />
            for your clinic
          </h1>
          <p className="text-lg text-zinc-500 leading-relaxed max-w-xl mx-auto mb-10">
            Automate appointment booking, clinical scribing, lab report parsing,
            and multi-doctor workflows — entirely over WhatsApp. No app download
            required.
          </p>
          <div className="flex items-center justify-center gap-4 flex-wrap">
            <Link
              href="/auth/signup"
              className="inline-flex items-center gap-2 rounded-xl bg-zinc-900 px-6 py-3 text-sm font-semibold text-white hover:bg-zinc-700 transition-colors"
            >
              Get started free
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/docs"
              className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 px-6 py-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 transition-colors"
            >
              Read docs
            </Link>
          </div>
        </section>

        {/* Features */}
        <section className="px-6 py-20 bg-zinc-50">
          <div className="max-w-5xl mx-auto">
            <h2 className="text-2xl font-bold text-zinc-900 text-center mb-3">
              Everything your clinic needs
            </h2>
            <p className="text-zinc-500 text-center text-sm mb-12 max-w-lg mx-auto">
              Six core modules, all working together over a single WhatsApp
              number.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {features.map(({ icon: Icon, title, description }) => (
                <div
                  key={title}
                  className="rounded-2xl border border-zinc-200 bg-white p-6 hover:shadow-sm transition-shadow"
                >
                  <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-zinc-100">
                    <Icon className="h-5 w-5 text-zinc-700" />
                  </div>
                  <h3 className="text-sm font-semibold text-zinc-900 mb-1.5">
                    {title}
                  </h3>
                  <p className="text-sm text-zinc-500 leading-relaxed">
                    {description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="px-6 py-20">
          <div className="max-w-4xl mx-auto">
            <h2 className="text-2xl font-bold text-zinc-900 text-center mb-3">
              How it works
            </h2>
            <p className="text-zinc-500 text-center text-sm mb-14 max-w-md mx-auto">
              Three steps from patient message to confirmed appointment.
            </p>
            <div className="flex flex-col md:flex-row items-start gap-6 md:gap-4">
              {steps.map(({ icon: Icon, number, title, description }, idx) => (
                <div key={number} className="flex md:flex-col items-start gap-4 flex-1">
                  <div className="flex flex-col md:flex-row items-center md:items-center gap-4 md:gap-0 w-full">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-zinc-900">
                      <Icon className="h-5 w-5 text-white" />
                    </div>
                    {idx < steps.length - 1 && (
                      <div className="hidden md:block flex-1 h-px bg-zinc-200 mx-4" />
                    )}
                  </div>
                  <div className="mt-4">
                    <div className="text-xs font-semibold text-zinc-400 mb-1">
                      {number}
                    </div>
                    <h3 className="text-sm font-semibold text-zinc-900 mb-1.5">
                      {title}
                    </h3>
                    <p className="text-sm text-zinc-500 leading-relaxed">
                      {description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA strip */}
        <section className="px-6 py-16 bg-zinc-900">
          <div className="max-w-3xl mx-auto text-center">
            <h2 className="text-2xl font-bold text-white mb-4">
              Ready to modernise your clinic?
            </h2>
            <p className="text-zinc-400 text-sm mb-8">
              Set up in under 30 minutes. No WhatsApp app download for your
              patients.
            </p>
            <Link
              href="/auth/signup"
              className="inline-flex items-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-zinc-900 hover:bg-zinc-100 transition-colors"
            >
              Get started free
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-100 px-6 py-8">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-zinc-500">
          <span className="font-semibold text-zinc-900">ClinicAI</span>
          <nav className="flex items-center gap-6">
            <Link href="/docs" className="hover:text-zinc-900 transition-colors">
              Documentation
            </Link>
            <Link
              href="/auth/login"
              className="hover:text-zinc-900 transition-colors"
            >
              Log in
            </Link>
          </nav>
          <span className="text-xs text-zinc-400">
            &copy; {new Date().getFullYear()} ClinicAI
          </span>
        </div>
      </footer>
    </div>
  );
}
