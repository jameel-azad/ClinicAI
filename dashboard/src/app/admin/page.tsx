"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";
import {
  Building2,
  Stethoscope,
  Activity,
  Eye,
  PowerOff,
  Power,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Clinic } from "@/../types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface ClinicWithDoctors extends Clinic {
  doctor_count?: number;
  ai_model?: string;
}

async function fetchClinics(): Promise<ClinicWithDoctors[]> {
  const res = await fetch(`${API}/api/clinics/`, { credentials: "include" });
  if (!res.ok) throw new Error("Failed to fetch clinics");
  return res.json();
}

async function toggleClinicActive(id: string, activate: boolean): Promise<void> {
  const res = await fetch(`${API}/api/clinics/${id}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: activate }),
  });
  if (!res.ok) throw new Error("Failed to update clinic");
}

function StatCard({
  label,
  value,
  icon: Icon,
  loading,
}: {
  label: string;
  value: number | string;
  icon: React.ElementType;
  loading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
          {label}
          <Icon className="size-4 text-muted-foreground" />
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <p className="text-2xl font-bold text-foreground">{value}</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function SuperAdminPage() {
  const queryClient = useQueryClient();
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const { data: clinics = [], isLoading, isError } = useQuery({
    queryKey: ["admin", "clinics"],
    queryFn: fetchClinics,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, activate }: { id: string; activate: boolean }) =>
      toggleClinicActive(id, activate),
    onMutate: ({ id }) => setTogglingId(id),
    onSuccess: (_data, { activate }) => {
      toast.success(`Clinic ${activate ? "activated" : "deactivated"} successfully`);
      queryClient.invalidateQueries({ queryKey: ["admin", "clinics"] });
    },
    onError: () => {
      toast.error("Failed to update clinic status");
    },
    onSettled: () => setTogglingId(null),
  });

  const totalClinics = clinics.length;
  const activeClinics = clinics.filter((c) => c.is_active).length;
  const totalDoctors = clinics.reduce(
    (sum, c) => sum + (c.doctor_count ?? 0),
    0
  );

  function formatDate(iso: string) {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Overview
        </h1>
        <p className="text-sm text-muted-foreground">
          Manage all clinics and their configurations.
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Total Clinics"
          value={totalClinics}
          icon={Building2}
          loading={isLoading}
        />
        <StatCard
          label="Active Clinics"
          value={activeClinics}
          icon={Activity}
          loading={isLoading}
        />
        <StatCard
          label="Total Doctors"
          value={totalDoctors}
          icon={Stethoscope}
          loading={isLoading}
        />
      </div>

      {/* Clinics table */}
      <Card>
        <CardHeader>
          <CardTitle>All Clinics</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isError && (
            <p className="px-4 py-6 text-sm text-destructive">
              Failed to load clinics. Please refresh the page.
            </p>
          )}

          {isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Clinic Name</TableHead>
                  <TableHead>Twilio Number</TableHead>
                  <TableHead className="text-center">Doctors</TableHead>
                  <TableHead>AI Model</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-center">Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clinics.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="py-8 text-center text-muted-foreground"
                    >
                      No clinics found.
                    </TableCell>
                  </TableRow>
                ) : (
                  clinics.map((clinic) => (
                    <TableRow key={clinic.id}>
                      <TableCell className="font-medium">
                        {clinic.name}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {clinic.twilio_number || "—"}
                      </TableCell>
                      <TableCell className="text-center">
                        {clinic.doctor_count ?? "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {clinic.ai_model ?? "—"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDate(clinic.created_at)}
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant={clinic.is_active ? "default" : "outline"}
                        >
                          {clinic.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="outline" size="sm" asChild>
                            <Link href={`/admin/clinics/${clinic.id}`}>
                              <Eye className="size-3.5" />
                              View
                            </Link>
                          </Button>
                          <Button
                            variant={clinic.is_active ? "destructive" : "secondary"}
                            size="sm"
                            disabled={togglingId === clinic.id}
                            onClick={() =>
                              toggleMutation.mutate({
                                id: clinic.id,
                                activate: !clinic.is_active,
                              })
                            }
                          >
                            {clinic.is_active ? (
                              <>
                                <PowerOff className="size-3.5" />
                                Deactivate
                              </>
                            ) : (
                              <>
                                <Power className="size-3.5" />
                                Activate
                              </>
                            )}
                          </Button>
                        </div>
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
