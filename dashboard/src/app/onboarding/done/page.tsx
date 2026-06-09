"use client";

import Link from "next/link";
import { CircleCheckIcon, ExternalLinkIcon } from "lucide-react";

import { useMe } from "@/hooks/useMe";
import { useDoctors } from "@/hooks/useDoctors";
import { useModelConfig } from "@/hooks/useModelConfig";
import { Button } from "@/components/ui/button";

function extractWhatsAppNumber(raw: string | undefined): string | null {
  if (!raw) return null;
  // Accept "whatsapp:+<digits>" or a plain E.164 number
  const match = raw.match(/\+?(\d+)/);
  return match ? match[1] : null;
}

export default function DonePage() {
  const { data: me, isLoading: meLoading } = useMe();
  const clinicId = me?.clinic?.id;
  const { data: doctors } = useDoctors(clinicId);
  const { data: modelConfig } = useModelConfig(clinicId);

  if (meLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  const clinic = me?.clinic;
  const doctorCount = doctors?.length ?? 0;
  const modelLabel = modelConfig
    ? `${modelConfig.llm_vendor} / ${modelConfig.llm_model}`
    : "Not configured";

  const waDigits = extractWhatsAppNumber(clinic?.twilio_whatsapp_number);
  const waLink = waDigits ? `https://wa.me/${waDigits}` : null;

  return (
    <div className="flex flex-col items-center gap-8 py-10 text-center">
      {/* Celebration icon */}
      <div className="flex h-20 w-20 items-center justify-center rounded-full bg-green-500/10">
        <CircleCheckIcon className="size-12 text-green-500" />
      </div>

      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold">You&apos;re all set!</h1>
        <p className="text-muted-foreground">
          ClinicAI is configured and ready to take appointments on WhatsApp.
        </p>
      </div>

      {/* Summary */}
      <div className="w-full max-w-sm rounded-xl border bg-card p-5 text-left text-sm">
        <dl className="flex flex-col gap-3">
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Clinic</dt>
            <dd className="font-medium">{clinic?.name ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Doctors</dt>
            <dd className="font-medium">{doctorCount}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">AI Model</dt>
            <dd className="truncate font-medium">{modelLabel}</dd>
          </div>
        </dl>
      </div>

      {/* WhatsApp link */}
      {waLink && (
        <a
          href={waLink}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-lg bg-[#25D366] px-5 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          Open in WhatsApp
          <ExternalLinkIcon className="size-4" />
        </a>
      )}

      {/* CTA buttons */}
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button size="lg" asChild>
          <Link href="/dashboard">Go to Dashboard</Link>
        </Button>
        <Button size="lg" variant="outline" asChild>
          <Link href="/docs">Read Docs</Link>
        </Button>
      </div>
    </div>
  );
}
