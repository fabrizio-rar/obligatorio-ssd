import { useQuery } from '@tanstack/react-query'

import { getComparison } from '@/api/endpoints'

/** One cache entry per set of IDs, shared by the chat table and the /compare page. */
export function useComparison(ids: string[]) {
  return useQuery({
    queryKey: ['comparison', ids.join(',')],
    queryFn: () => getComparison(ids),
    enabled: ids.length >= 2,
  })
}

/** "/compare?ids=a,b,c" */
export const compareUrl = (ids: string[]) => `/compare?ids=${ids.map(encodeURIComponent).join(',')}`
