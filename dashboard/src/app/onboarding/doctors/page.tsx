"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, Controller, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { PlusIcon, StethoscopeIcon } from "lucide-react";

import { useMe } from "@/hooks/useMe";
import { fetchDoctors, createDoctor, type Doctor } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const SPECIALTIES = [
  "General Physician",
  "Cardiologist",
  "Dermatologist",
  "Neurologist",
  "Orthopedist",
  "Pediatrician",
  "Gynecologist",
  "Psychiatrist",
  "ENT Specialist",
  "Ophthalmologist",
  "Urologist",
  "Gastroenterologist",
  "Pulmonologist",
  "Endocrinologist",
];

const HOURS = Array.from({ length: 17 }, (_, i) => i + 6); // 6 – 22

const APPOINTMENT_DURATIONS = [
  { value: 15, label: "15 min" },
  { value: 20, label: "20 min" },
  { value: 30, label: "30 min" },
  { value: 45, label: "45 min" },
  { value: 60, label: "60 min" },
];

const BUFFER_OPTIONS = [
  { value: 0, label: "No buffer" },
  { value: 5, label: "5 min" },
  { value: 10, label: "10 min" },
  { value: 15, label: "15 min" },
];

const WHATSAPP_REGEX = /^whatsapp:\+\d{10,15}$/;

const doctorSchema = z
  .object({
    name: z.string().min(2, "Name must be at least 2 characters"),
    specialty: z.string().min(1, "Please select a specialty"),
    whatsapp_number: z
      .string()
      .regex(
        WHATSAPP_REGEX,
        "Must be in format whatsapp:+91XXXXXXXXXX"
      ),
    working_hours_start: z.coerce.number().min(6).max(22),
    working_hours_end: z.coerce.number().min(6).max(22),
    appointment_duration: z.coerce.number(),
    buffer_minutes: z.coerce.number(),
  })
  .refine((d) => d.working_hours_end > d.working_hours_start, {
    message: "End hour must be after start hour",
    path: ["working_hours_end"],
  });

type DoctorFormValues = z.infer<typeof doctorSchema>;

function DoctorCard({ doctor }: { doctor: Doctor }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>{doctor.name}</CardTitle>
            <CardDescription>{doctor.specialty}</CardDescription>
          </div>
          <Badge variant="secondary">
            {doctor.appointment_duration} min
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <dt>WhatsApp</dt>
          <dd className="truncate text-foreground">{doctor.whatsapp_number}</dd>
          <dt>Hours</dt>
          <dd className="text-foreground">
            {String(doctor.working_hours_start).padStart(2, "0")}:00 –{" "}
            {String(doctor.working_hours_end).padStart(2, "0")}:00
          </dd>
          <dt>Buffer</dt>
          <dd className="text-foreground">
            {doctor.buffer_minutes > 0
              ? `${doctor.buffer_minutes} min`
              : "None"}
          </dd>
        </dl>
      </CardContent>
    </Card>
  );
}

function AddDoctorDialog({
  clinicId,
  onAdded,
}: {
  clinicId: string;
  onAdded: () => void;
}) {
  const [open, setOpen] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<DoctorFormValues>({
    resolver: zodResolver(doctorSchema) as Resolver<DoctorFormValues>,
    defaultValues: {
      name: "",
      specialty: "",
      whatsapp_number: "whatsapp:+91",
      working_hours_start: 9,
      working_hours_end: 17,
      appointment_duration: 30,
      buffer_minutes: 5,
    },
  });

  async function onSubmit(values: DoctorFormValues) {
    try {
      await createDoctor(clinicId, values);
      toast.success(`Dr. ${values.name} added`);
      reset();
      setOpen(false);
      onAdded();
    } catch {
      toast.error("Failed to add doctor. Please try again.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button><PlusIcon />Add Doctor</Button>} />
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add a Doctor</DialogTitle>
        </DialogHeader>

        <form
          id="add-doctor-form"
          onSubmit={handleSubmit(onSubmit)}
          className="flex flex-col gap-4 py-2"
        >
          {/* Name */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="doctor-name">Doctor Name</Label>
            <Input
              id="doctor-name"
              placeholder="e.g. Dr. Ayesha Khan"
              aria-invalid={Boolean(errors.name)}
              {...register("name")}
            />
            {errors.name && (
              <p className="text-xs text-destructive">{errors.name.message}</p>
            )}
          </div>

          {/* Specialty */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="doctor-specialty">Specialty</Label>
            <Controller
              name="specialty"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="doctor-specialty" className="w-full">
                    <SelectValue placeholder="Select specialty" />
                  </SelectTrigger>
                  <SelectContent>
                    {SPECIALTIES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.specialty && (
              <p className="text-xs text-destructive">
                {errors.specialty.message}
              </p>
            )}
          </div>

          {/* WhatsApp Number */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="doctor-whatsapp">WhatsApp Number</Label>
            <Input
              id="doctor-whatsapp"
              placeholder="whatsapp:+91XXXXXXXXXX"
              aria-invalid={Boolean(errors.whatsapp_number)}
              {...register("whatsapp_number")}
            />
            <p className="text-xs text-muted-foreground">
              Format: whatsapp:+91XXXXXXXXXX
            </p>
            {errors.whatsapp_number && (
              <p className="text-xs text-destructive">
                {errors.whatsapp_number.message}
              </p>
            )}
          </div>

          {/* Working Hours */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>Start Hour</Label>
              <Controller
                name="working_hours_start"
                control={control}
                render={({ field }) => (
                  <Select
                    value={String(field.value)}
                    onValueChange={(v) => field.onChange(Number(v))}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {HOURS.map((h) => (
                        <SelectItem key={h} value={String(h)}>
                          {String(h).padStart(2, "0")}:00
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>End Hour</Label>
              <Controller
                name="working_hours_end"
                control={control}
                render={({ field }) => (
                  <Select
                    value={String(field.value)}
                    onValueChange={(v) => field.onChange(Number(v))}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {HOURS.map((h) => (
                        <SelectItem key={h} value={String(h)}>
                          {String(h).padStart(2, "0")}:00
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              {errors.working_hours_end && (
                <p className="text-xs text-destructive">
                  {errors.working_hours_end.message}
                </p>
              )}
            </div>
          </div>

          {/* Duration & Buffer */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <Label>Appointment Duration</Label>
              <Controller
                name="appointment_duration"
                control={control}
                render={({ field }) => (
                  <Select
                    value={String(field.value)}
                    onValueChange={(v) => field.onChange(Number(v))}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {APPOINTMENT_DURATIONS.map((d) => (
                        <SelectItem key={d.value} value={String(d.value)}>
                          {d.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Buffer Minutes</Label>
              <Controller
                name="buffer_minutes"
                control={control}
                render={({ field }) => (
                  <Select
                    value={String(field.value)}
                    onValueChange={(v) => field.onChange(Number(v))}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {BUFFER_OPTIONS.map((b) => (
                        <SelectItem key={b.value} value={String(b.value)}>
                          {b.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>
        </form>

        <DialogFooter>
          <Button
            type="submit"
            form="add-doctor-form"
            disabled={isSubmitting}
          >
            {isSubmitting ? "Adding…" : "Add Doctor"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function DoctorsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me, isLoading: meLoading } = useMe();
  const clinicId = me?.clinic?.id;

  const {
    data: doctors = [],
    isLoading: doctorsLoading,
    refetch,
  } = useQuery<Doctor[]>({
    queryKey: ["doctors", clinicId],
    queryFn: () => fetchDoctors(clinicId!),
    enabled: Boolean(clinicId),
  });

  function handleDoctorAdded() {
    refetch();
    queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  const isLoading = meLoading || doctorsLoading;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Add Doctors</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Add the doctors who will be receiving appointments via ClinicAI.
          </p>
        </div>
        {clinicId && (
          <AddDoctorDialog clinicId={clinicId} onAdded={handleDoctorAdded} />
        )}
      </div>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
          Loading doctors…
        </div>
      ) : doctors.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-sm text-muted-foreground">
          <StethoscopeIcon className="size-8 opacity-40" />
          <span>No doctors added yet. Add at least one to continue.</span>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {doctors.map((doc) => (
            <DoctorCard key={doc.id} doctor={doc} />
          ))}
        </div>
      )}

      <div className="flex justify-end">
        <Button
          onClick={() => router.push("/onboarding/model")}
          disabled={doctors.length === 0}
          size="lg"
        >
          Continue
        </Button>
      </div>
    </div>
  );
}
