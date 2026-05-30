"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchMe, type Me } from "@/lib/api";

export function useMe() {
  return useQuery<Me>({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 30_000,
  });
}
