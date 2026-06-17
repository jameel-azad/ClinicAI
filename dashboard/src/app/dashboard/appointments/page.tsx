"use client"

import * as React from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, Search, X } from "lucide-react"

import api, { type Appointment } from "@/lib/api"
import { useMe } from "@/hooks/useMe"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadge(status: Appointment["status"]) {
  const variants: Record<string, string> = {
    active: "bg-green-100 text-green-800",
    cancelled: "bg-red-100 text-red-800",
    completed: "bg-gray-100 text-gray-600",
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${variants[status] ?? variants.active}`}
    >
      {status}
    </span>
  )
}

function formatPhone(phone: string) {
  return phone.replace("whatsapp:", "")
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AppointmentsPage() {
  const { data: me } = useMe()
  const clinicId = me?.clinic?.id
  const queryClient = useQueryClient()

  const [statusFilter, setStatusFilter] = React.useState<string>("all")
  const [doctorFilter, setDoctorFilter] = React.useState("")
  const [debouncedDoctor, setDebouncedDoctor] = React.useState("")

  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedDoctor(doctorFilter), 300)
    return () => clearTimeout(t)
  }, [doctorFilter])

  const { data: appointments, isLoading } = useQuery<Appointment[]>({
    queryKey: ["appointments", clinicId, statusFilter, debouncedDoctor],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter && statusFilter !== "all") params.set("status", statusFilter)
      if (debouncedDoctor) params.set("doctor_name", debouncedDoctor)
      const qs = params.toString()
      const { data } = await api.get(
        `/api/clinics/${clinicId}/appointments${qs ? `?${qs}` : ""}`
      )
      return data
    },
    enabled: Boolean(clinicId),
  })

  const cancelMutation = useMutation({
    mutationFn: async (appointmentId: string) => {
      await api.put(`/api/clinics/${clinicId}/appointments/${appointmentId}`, {
        status: "cancelled",
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointments", clinicId] })
    },
  })

  const completeMutation = useMutation({
    mutationFn: async (appointmentId: string) => {
      await api.put(`/api/clinics/${clinicId}/appointments/${appointmentId}`, {
        status: "completed",
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["appointments", clinicId] })
    },
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CalendarDays className="size-6 text-muted-foreground" />
          <h1 className="text-2xl font-semibold">Appointments</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          {appointments ? `${appointments.length} result${appointments.length !== 1 ? "s" : ""}` : ""}
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-3">
            <Select
              value={statusFilter}
              onValueChange={setStatusFilter}
            >
              <SelectTrigger className="w-40">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
              </SelectContent>
            </Select>

            <div className="relative flex-1 min-w-48">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Filter by doctor name…"
                value={doctorFilter}
                onChange={(e) => setDoctorFilter(e.target.value)}
              />
              {doctorFilter && (
                <button
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  onClick={() => setDoctorFilter("")}
                >
                  <X className="size-4 text-muted-foreground" />
                </button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Patient</TableHead>
                <TableHead>Phone</TableHead>
                <TableHead>Doctor</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Symptoms</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 8 }).map((_, j) => (
                      <TableCell key={j}>
                        <Skeleton className="h-4 w-full" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}

              {!isLoading && appointments?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-10 text-center text-muted-foreground">
                    No appointments found.
                  </TableCell>
                </TableRow>
              )}

              {!isLoading &&
                appointments?.map((appt) => (
                  <TableRow key={appt.id}>
                    <TableCell className="font-medium">
                      {appt.patient_name ?? <span className="text-muted-foreground italic">Unknown</span>}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatPhone(appt.from_number)}
                    </TableCell>
                    <TableCell>{appt.doctor_name}</TableCell>
                    <TableCell>{appt.date_str}</TableCell>
                    <TableCell>{appt.time_str}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {appt.symptoms && appt.symptoms.length > 0
                        ? appt.symptoms.join(", ")
                        : <span className="italic">Not provided</span>}
                    </TableCell>
                    <TableCell>{statusBadge(appt.status)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {appt.status === "active" && (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={completeMutation.isPending}
                              onClick={() => completeMutation.mutate(appt.id)}
                            >
                              Complete
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={cancelMutation.isPending}
                              onClick={() => cancelMutation.mutate(appt.id)}
                            >
                              Cancel
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
