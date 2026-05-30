"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useForm, Controller, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { useMe } from "@/hooks/useMe";
import { updateClinic } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ── IANA timezones (common subset) ────────────────────────────────────────
const TIMEZONES = [
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Karachi",
  "Asia/Riyadh",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Africa/Cairo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

const HOURS = Array.from({ length: 17 }, (_, i) => i + 6); // 6 – 22

const schema = z
  .object({
    name: z.string().min(2, "Clinic name must be at least 2 characters"),
    timezone: z.string().min(1, "Please select a timezone"),
    opening_hour: z.coerce.number().min(6).max(22),
    closing_hour: z.coerce.number().min(6).max(22),
  })
  .refine((d) => d.closing_hour > d.opening_hour, {
    message: "Closing hour must be after opening hour",
    path: ["closing_hour"],
  });

type FormValues = z.infer<typeof schema>;

export default function ClinicPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me, isLoading } = useMe();

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema) as Resolver<FormValues>,
    defaultValues: {
      name: "",
      timezone: "Asia/Kolkata",
      opening_hour: 9,
      closing_hour: 18,
    },
  });

  // Prefill once data arrives
  useEffect(() => {
    if (me?.clinic) {
      reset({
        name: me.clinic.name,
        timezone: me.clinic.timezone,
        opening_hour: me.clinic.opening_hour,
        closing_hour: me.clinic.closing_hour,
      });
    }
  }, [me, reset]);

  async function onSubmit(values: FormValues) {
    if (!me?.clinic?.id) return;
    try {
      await updateClinic(me.clinic.id, values);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("Clinic details saved");
      router.push("/onboarding/doctors");
    } catch {
      toast.error("Failed to save clinic details. Please try again.");
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">Clinic Details</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tell us a bit about your clinic so we can set things up correctly.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
        {/* Clinic Name */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="name">Clinic Name</Label>
          <Input
            id="name"
            placeholder="e.g. Sunrise Health Clinic"
            aria-invalid={Boolean(errors.name)}
            {...register("name")}
          />
          {errors.name && (
            <p className="text-xs text-destructive">{errors.name.message}</p>
          )}
        </div>

        {/* Timezone */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="timezone">Timezone</Label>
          <Controller
            name="timezone"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="timezone" className="w-full">
                  <SelectValue placeholder="Select timezone" />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {errors.timezone && (
            <p className="text-xs text-destructive">
              {errors.timezone.message}
            </p>
          )}
        </div>

        {/* Hours row */}
        <div className="grid grid-cols-2 gap-4">
          {/* Opening Hour */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="opening_hour">Opening Hour</Label>
            <Controller
              name="opening_hour"
              control={control}
              render={({ field }) => (
                <Select
                  value={String(field.value)}
                  onValueChange={(v) => field.onChange(Number(v))}
                >
                  <SelectTrigger id="opening_hour" className="w-full">
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

          {/* Closing Hour */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="closing_hour">Closing Hour</Label>
            <Controller
              name="closing_hour"
              control={control}
              render={({ field }) => (
                <Select
                  value={String(field.value)}
                  onValueChange={(v) => field.onChange(Number(v))}
                >
                  <SelectTrigger id="closing_hour" className="w-full">
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
            {errors.closing_hour && (
              <p className="text-xs text-destructive">
                {errors.closing_hour.message}
              </p>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button type="submit" disabled={isSubmitting} size="lg">
            {isSubmitting ? "Saving…" : "Save & Continue"}
          </Button>
        </div>
      </form>
    </div>
  );
}
