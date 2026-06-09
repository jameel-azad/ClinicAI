"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchDoctors, type Doctor } from "@/lib/api";

export function useDoctors(clinicId: string | undefined) {
  return useQuery<Doctor[]>({
    queryKey: ["doctors", clinicId],
    queryFn: () => fetchDoctors(clinicId!),
    enabled: Boolean(clinicId),
  });
}
