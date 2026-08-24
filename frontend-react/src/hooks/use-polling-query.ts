import { useQuery, type QueryKey, type UseQueryOptions } from "@tanstack/react-query";

export function usePollingQuery<TData>(
  queryKey: QueryKey,
  queryFn: () => Promise<TData>,
  options: Omit<UseQueryOptions<TData>, "queryKey" | "queryFn" | "refetchInterval"> & {
    intervalMs?: number;
    isFinal?: (data: TData) => boolean;
  } = {},
) {
  const { intervalMs = 2500, isFinal, ...rest } = options;
  return useQuery({
    queryKey,
    queryFn,
    refetchInterval: (query) => {
      const data = query.state.data as TData | undefined;
      if (data && isFinal?.(data)) return false;
      return intervalMs;
    },
    ...rest,
  });
}
