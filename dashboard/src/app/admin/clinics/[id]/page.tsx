"use client";

import { use, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";
import {
  ChevronRight,
  Clock,
  Globe,
  Phone,
  Cpu,
  Users,
  Power,
  PowerOff,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Clinic, Doctor, ModelConfig } from "@/../types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ClinicDetail extends Clinic {
  model_config?: ModelConfig;
}

async function fetchClinic(id: string): Promise<ClinicDetail> {
  const res = await fetch(`${API}/api/clinics/${id}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch clinic");
  return res.json();
}

async function fetchDoctors(id: string): Promise<Doctor[]> {
  const res = await fetch(`${API}/api/clinics/${id}/doctors`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Failed to fetch doctors");
  return res.json();
}

async function toggleClinic(id: string, activate: boolean): Promise<void> {
  const res = await fetch(`${API}/api/clinics/${id}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: activate }),
  });
  if (!res.ok) throw new Error("Failed to update clinic");
}

function formatHour(hour: number): string {
  const date = new Date(2000, 0, 1, hour, 0);
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 py-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="flex flex-1 items-center justify-between gap-4">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-sm font-medium text-foreground">{value}</span>
      </div>
    </div>
  );
}

export default function ClinicDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const [toggling, setToggling] = useState(false);

  const {
    data: clinic,
    isLoading: clinicLoading,
    isError: clinicError,
  } = useQuery({
    queryKey: ["admin", "clinic", id],
    queryFn: () => fetchClinic(id),
  });

  const {
    data: doctors = [],
    isLoading: doctorsLoading,
    isError: doctorsError,
  } = useQuery({
    queryKey: ["admin", "clinic", id, "doctors"],
    queryFn: () => fetchDoctors(id),
  });

  const toggleMutation = useMutation({
    mutationFn: (activate: boolean) => toggleClinic(id, activate),
    onMutate: () => setToggling(true),
    onSuccess: (_data, activate) => {
      toast.success(`Clinic ${activate ? "activated" : "deactivated"} successfully`);
      queryClient.invalidateQueries({ queryKey: ["admin", "clinic", id] });
      queryClient.invalidateQueries({ queryKey: ["admin", "clinics"] });
    },
    onError: () => {
      toast.error("Failed to update clinic status");
    },
    onSettled: () => setToggling(false),
  });

  const clinicName = clinic?.name ?? "Clinic";

  return (
    <div className="space-y-8">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link
          href="/admin"
          className="transition-colors hover:text-foreground"
        >
          Super Admin
        </Link>
        <ChevronRight className="size-4" />
        {clinicLoading ? (
          <Skeleton className="h-4 w-24" />
        ) : (
          <span className="text-foreground font-medium">{clinicName}</span>
        )}
      </nav>

      {/* Page heading + action */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          {clinicLoading ? (
            <Skeleton className="h-8 w-48" />
          ) : (
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {clinicName}
            </h1>
          )}
          <p className="mt-1 text-sm text-muted-foreground">
            Clinic detail and configuration
          </p>
        </div>

        {clinic && (
          <Button
            variant={clinic.is_active ? "destructive" : "secondary"}
            disabled={toggling}
            onClick={() => toggleMutation.mutate(!clinic.is_active)}
          >
            {clinic.is_active ? (
              <>
                <PowerOff className="size-4" />
                Deactivate Clinic
              </>
            ) : (
              <>
                <Power className="size-4" />
                Activate Clinic
              </>
            )}
          </Button>
        )}
      </div>

      {clinicError && (
        <p className="text-sm text-destructive">
          Failed to load clinic details. Please refresh.
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Clinic info card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Clinic Info
              {clinicLoading ? (
                <Skeleton className="h-5 w-14" />
              ) : (
                <Badge variant={clinic?.is_active ? "default" : "outline"}>
                  {clinic?.is_active ? "Active" : "Inactive"}
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            {clinicLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : clinic ? (
              <div className="divide-y divide-border">
                <InfoRow
                  icon={Phone}
                  label="Twilio Number"
                  value={
                    <span className="font-mono text-xs">
                      {clinic.twilio_number || "—"}
                    </span>
                  }
                />
                <InfoRow
                  icon={Globe}
                  label="Timezone"
                  value={clinic.timezone}
                />
                <InfoRow
                  icon={Clock}
                  label="Business Hours"
                  value={`${formatHour(clinic.open_hour)} – ${formatHour(clinic.close_hour)}`}
                />
                <InfoRow
                  icon={Clock}
                  label="Created"
                  value={new Date(clinic.created_at).toLocaleDateString(
                    "en-US",
                    {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    }
                  )}
                />
              </div>
            ) : null}
          </CardContent>
        </Card>

        {/* AI Config card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="size-4" />
              AI Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            {clinicLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : clinic?.model_config ? (
              <div className="divide-y divide-border">
                <InfoRow
                  icon={Cpu}
                  label="LLM Vendor"
                  value={clinic.model_config.llm_vendor}
                />
                <InfoRow
                  icon={Cpu}
                  label="LLM Model"
                  value={clinic.model_config.llm_model}
                />
                <InfoRow
                  icon={Cpu}
                  label="STT Model"
                  value={clinic.model_config.stt_model}
                />
                <div className="py-3">
                  <p className="mb-2 text-sm text-muted-foreground">
                    API Keys Status
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(
                      [
                        ["Groq", clinic.model_config.groq_api_key_set],
                        ["Anthropic", clinic.model_config.anthropic_api_key_set],
                        ["OpenAI", clinic.model_config.openai_api_key_set],
                        ["Google", clinic.model_config.google_api_key_set],
                      ] as [string, boolean][]
                    ).map(([name, isSet]) => (
                      <Badge
                        key={name}
                        variant={isSet ? "default" : "outline"}
                        className="text-xs"
                      >
                        {name}: {isSet ? "Set" : "Not set"}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <p className="py-4 text-sm text-muted-foreground">
                No AI configuration found for this clinic.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Doctors table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="size-4" />
            Doctors
            {!doctorsLoading && (
              <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs font-normal text-muted-foreground">
                {doctors.length}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <Separator />
        <CardContent className="p-0">
          {doctorsError && (
            <p className="px-4 py-6 text-sm text-destructive">
              Failed to load doctors. Please refresh.
            </p>
          )}

          {doctorsLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Specialty</TableHead>
                  <TableHead>WhatsApp</TableHead>
                  <TableHead>Working Hours</TableHead>
                  <TableHead className="text-center">Appt (min)</TableHead>
                  <TableHead className="text-center">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {doctors.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={6}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No doctors assigned to this clinic.
                    </TableCell>
                  </TableRow>
                ) : (
                  doctors.map((doctor) => (
                    <TableRow key={doctor.id}>
                      <TableCell className="font-medium">
                        {doctor.name}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {doctor.specialty}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {doctor.whatsapp_number}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatHour(doctor.working_hours_start)} –{" "}
                        {formatHour(doctor.working_hours_end)}
                      </TableCell>
                      <TableCell className="text-center text-sm">
                        {doctor.appointment_duration_minutes}
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant={doctor.is_active ? "default" : "outline"}
                        >
                          {doctor.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
