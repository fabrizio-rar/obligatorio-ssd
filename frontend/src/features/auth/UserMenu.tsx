import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LogOutIcon, UserIcon } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { getMe, logout } from '@/api/endpoints'
import { Button, buttonVariants } from '@/components/ui/button'
import { setSession, useSession } from '@/lib/session'

/** Header: "Iniciar sesión" or the username with "Salir". */
export function UserMenu() {
  const session = useSession()
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Check the stored token once per session: if it expired, api/client.ts gets a 401 and logs out
  useQuery({ queryKey: ['me', session?.token], queryFn: getMe, enabled: session !== null, staleTime: Infinity })

  const signOut = useMutation({
    mutationFn: logout,
    // Log out locally even if the request fails (the token may already be invalid)
    onSettled: () => {
      setSession(null)
      queryClient.clear()
      navigate('/')
    },
  })

  if (!session) {
    return (
      <Link
        to="/login"
        state={{ from: location.pathname + location.search }}
        className={buttonVariants({ variant: 'default' })}
      >
        Iniciar sesión
      </Link>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <span className="flex items-center gap-1 text-sm text-muted-foreground">
        <UserIcon className="size-4" />
        {session.username}
      </span>
      <Button variant="ghost" size="sm" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
        <LogOutIcon data-icon="inline-start" />
        Salir
      </Button>
    </div>
  )
}
