"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchModelConfig, type ModelConfig } from "@/lib/api";

export function useModelConfig(clinicId: string | undefined) {
  return useQuery<ModelConfig>({
    queryKey: ["model-config", clinicId],
    queryFn: () => fetchModelConfig(clinicId!),
    enabled: Boolean(clinicId),
    staleTime: 30_000,
  });
}
