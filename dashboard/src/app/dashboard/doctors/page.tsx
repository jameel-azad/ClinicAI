"use client"

import * as React from "react"
import { useQueryClient, useMutation } from "@tanstack/react-query"
import { useForm, type Resolver } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Plus, Pencil, UserX, Users } from "lucide-react"

import api from "../../../../lib/api"
import { useMe, useDoctors } from "../../../../lib/hooks"
import { Doctor } from "../../../../types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card"
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table"
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog"

// ─── Schema ───────────────────────────────────────────────────────────────────

const doctorSchema = z.object({
  name: z.string().min(1, "Name is required"),
  specialty: z.string().min(1, "Specialty is required"),
  whatsapp_number: z.string().min(1, "WhatsApp number is required"),
  working_hours_start: z.coerce
    .number()
    .int()
    .min(0)
    .max(23, "Must be 0–23"),
  working_hours_end: z.coerce
    .number()
    .int()
    .min(0)
    .max(23, "Must be 0–23"),
  appointment_duration_minutes: z.coerce
    .number()
    .int()
    .min(5, "Minimum 5 minutes"),
  buffer_minutes: z.coerce.number().int().min(0),
})

type DoctorFormData = z.infer<typeof doctorSchema>

// ─── Doctor Form ──────────────────────────────────────────────────────────────

function DoctorForm({
  defaultValues,
  onSubmit,
  isPending,
}: {
  defaultValues?: Partial<DoctorFormData>
  onSubmit: (data: DoctorFormData) => void
  isPending: boolean
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<DoctorFormData>({
    resolver: zodResolver(doctorSchema) as Resolver<DoctorFormData>,
    defaultValues: {
      working_hours_start: 8,
      working_hours_end: 18,
      appointment_duration_minutes: 30,
      buffer_minutes: 5,
      ...defaultValues,
    },
  })

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
      <div className="grid gap-1.5">
        <Label htmlFor="name">Full Name</Label>
        <Input id="name" placeholder="Dr. Jane Smith" {...register("name")} />
        {errors.name && (
          <p className="text-xs text-destructive">{errors.name.message}</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="specialty">Specialty</Label>
        <Input
          id="specialty"
          placeholder="General Practitioner"
          {...register("specialty")}
        />
        {errors.specialty && (
          <p className="text-xs text-destructive">
            {errors.specialty.message}
          </p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="whatsapp_number">WhatsApp Number</Label>
        <Input
          id="whatsapp_number"
          placeholder="+1234567890"
          {...register("whatsapp_number")}
        />
        {errors.whatsapp_number && (
          <p className="text-xs text-destructive">
            {errors.whatsapp_number.message}
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="working_hours_start">Start Hour (0–23)</Label>
          <Input
            id="working_hours_start"
            type="number"
            min={0}
            max={23}
            {...register("working_hours_start", { valueAsNumber: true })}
          />
          {errors.working_hours_start && (
            <p className="text-xs text-destructive">
              {errors.working_hours_start.message}
            </p>
          )}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="working_hours_end">End Hour (0–23)</Label>
          <Input
            id="working_hours_end"
            type="number"
            min={0}
            max={23}
            {...register("working_hours_end", { valueAsNumber: true })}
          />
          {errors.working_hours_end && (
            <p className="text-xs text-destructive">
              {errors.working_hours_end.message}
            </p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="appointment_duration_minutes">
            Appointment (min)
          </Label>
          <Input
            id="appointment_duration_minutes"
            type="number"
            min={5}
            {...register("appointment_duration_minutes", { valueAsNumber: true })}
          />
          {errors.appointment_duration_minutes && (
            <p className="text-xs text-destructive">
              {errors.appointment_duration_minutes.message}
            </p>
          )}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="buffer_minutes">Buffer (min)</Label>
          <Input
            id="buffer_minutes"
            type="number"
            min={0}
            {...register("buffer_minutes", { valueAsNumber: true })}
          />
        </div>
      </div>

      <DialogFooter className="border-none bg-transparent p-0">
        <DialogClose render={<Button variant="outline" type="button">Cancel</Button>} />

        <Button type="submit" disabled={isPending}>
          {isPending ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </form>
  )
}

// ─── Add Doctor Dialog ─────────────────────────────────────────────────────

function AddDoctorDialog({ clinicId }: { clinicId: string }) {
  const [open, setOpen] = React.useState(false)
  const queryClient = useQueryClient()

  const addMutation = useMutation({
    mutationFn: (data: DoctorFormData) =>
      api.post(`/api/clinics/${clinicId}/doctors`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["doctors", clinicId] })
      setOpen(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button size="sm"><Plus className="size-4" />Add Doctor</Button>} />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Doctor</DialogTitle>
          <DialogDescription>
            Enter the doctor's details below.
          </DialogDescription>
        </DialogHeader>
        <DoctorForm
          onSubmit={(data) => addMutation.mutate(data)}
          isPending={addMutation.isPending}
        />
      </DialogContent>
    </Dialog>
  )
}

// ─── Edit Doctor Dialog ────────────────────────────────────────────────────

function EditDoctorDialog({
  doctor,
  clinicId,
}: {
  doctor: Doctor
  clinicId: string
}) {
  const [open, setOpen] = React.useState(false)
  const queryClient = useQueryClient()

  const editMutation = useMutation({
    mutationFn: (data: DoctorFormData) =>
      api
        .put(`/api/clinics/${clinicId}/doctors/${doctor.id}`, data)
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["doctors", clinicId] })
      setOpen(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" size="icon-sm" aria-label="Edit doctor"><Pencil className="size-3.5" /></Button>} />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Doctor</DialogTitle>
          <DialogDescription>Update {doctor.name}'s details.</DialogDescription>
        </DialogHeader>
        <DoctorForm
          defaultValues={{
            name: doctor.name,
            specialty: doctor.specialty,
            whatsapp_number: doctor.whatsapp_number,
            working_hours_start: doctor.working_hours_start,
            working_hours_end: doctor.working_hours_end,
            appointment_duration_minutes: doctor.appointment_duration_minutes,
            buffer_minutes: doctor.buffer_minutes,
          }}
          onSubmit={(data) => editMutation.mutate(data)}
          isPending={editMutation.isPending}
        />
      </DialogContent>
    </Dialog>
  )
}

// ─── Deactivate Doctor Dialog ──────────────────────────────────────────────

function DeactivateDoctorDialog({
  doctor,
  clinicId,
}: {
  doctor: Doctor
  clinicId: string
}) {
  const [open, setOpen] = React.useState(false)
  const queryClient = useQueryClient()

  const deleteMutation = useMutation({
    mutationFn: () =>
      api
        .delete(`/api/clinics/${clinicId}/doctors/${doctor.id}`)
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["doctors", clinicId] })
      setOpen(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="destructive" size="icon-sm" disabled={!doctor.is_active} aria-label="Deactivate doctor"><UserX className="size-3.5" /></Button>} />
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Deactivate Doctor</DialogTitle>
          <DialogDescription>
            Are you sure you want to deactivate{" "}
            <span className="font-medium text-foreground">{doctor.name}</span>?
            They will no longer appear as available.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="border-none bg-transparent p-0">
          <DialogClose render={<Button variant="outline">Cancel</Button>} />
          <Button
            variant="destructive"
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending ? "Deactivating…" : "Deactivate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────

function formatHour(h: number): string {
  const ampm = h >= 12 ? "PM" : "AM"
  const display = h % 12 === 0 ? 12 : h % 12
  return `${display}:00 ${ampm}`
}

export default function DoctorsPage() {
  const { data: me } = useMe()
  const clinicId = me?.clinic_id ?? ""
  const { data: doctors, isLoading } = useDoctors(clinicId)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Doctors</h1>
          <p className="text-sm text-muted-foreground">
            Manage your clinic's doctors
          </p>
        </div>
        {clinicId && <AddDoctorDialog clinicId={clinicId} />}
      </div>

      <Card>
        <CardHeader className="border-b">
          <CardTitle>Doctor List</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !doctors || doctors.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <Users className="size-10 text-muted-foreground/40" />
              <p className="text-sm font-medium text-muted-foreground">
                No doctors yet
              </p>
              <p className="max-w-xs text-xs text-muted-foreground">
                Add your first doctor to start managing appointments.
              </p>
              {clinicId && <AddDoctorDialog clinicId={clinicId} />}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Specialty</TableHead>
                  <TableHead>WhatsApp</TableHead>
                  <TableHead>Hours</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {doctors.map((doctor) => (
                  <TableRow key={doctor.id}>
                    <TableCell className="font-medium">{doctor.name}</TableCell>
                    <TableCell>{doctor.specialty}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {doctor.whatsapp_number}
                    </TableCell>
                    <TableCell className="text-xs">
                      {formatHour(doctor.working_hours_start)} –{" "}
                      {formatHour(doctor.working_hours_end)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {doctor.appointment_duration_minutes} min
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={doctor.is_active ? "default" : "secondary"}
                      >
                        {doctor.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <EditDoctorDialog
                          doctor={doctor}
                          clinicId={clinicId}
                        />
                        <DeactivateDoctorDialog
                          doctor={doctor}
                          clinicId={clinicId}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
