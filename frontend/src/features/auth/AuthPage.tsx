import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { login, register } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Logo } from '@/components/brand/Logo'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { setSession, useSession } from '@/lib/session'

// Same rules as backend/app/auth/service.py, checked here first to give instant feedback
const USERNAME_PATTERN = /^[a-z0-9._-]{3,30}$/
const PASSWORD_MIN = 6

type Mode = 'login' | 'register'
type Field = 'username' | 'password' | 'confirm'

function validate(mode: Mode, username: string, password: string, confirm: string) {
  const errors: Partial<Record<Field, string>> = {}
  if (!USERNAME_PATTERN.test(username.trim().toLowerCase())) {
    errors.username = "Entre 3 y 30 caracteres: letras, números, '.', '_' o '-'"
  }
  if (password.length < PASSWORD_MIN) errors.password = `Al menos ${PASSWORD_MIN} caracteres`
  if (mode === 'register' && confirm !== password) errors.confirm = 'Las contraseñas no coinciden'
  return errors
}

/** Login and register (N3). After registering, it logs in with the same credentials. */
export function AuthPage({ mode }: { mode: Mode }) {
  const session = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Partial<Record<Field, string>>>({})

  const submit = useMutation({
    mutationFn: async () => {
      if (mode === 'register') await register(username, password)
      return login(username, password)
    },
    onSuccess: (result) => {
      queryClient.clear() // nothing cached from a previous user survives
      setSession({ token: result.token, username: result.user.username })
      toast.success(`Hola, ${result.user.username}`)
      navigate(from, { replace: true })
    },
    onError: (error) => {
      const field = error instanceof ApiError ? error.details.field : undefined
      if (error instanceof ApiError && error.code === 'USERNAME_TAKEN') setErrors({ username: error.message })
      else if (field === 'username' || field === 'password') setErrors({ [field]: error.message })
    },
  })

  if (session && !submit.isPending) return <Navigate to={from} replace />

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const found = validate(mode, username, password, confirm)
    setErrors(found)
    if (Object.keys(found).length === 0) submit.mutate()
  }

  const isLogin = mode === 'login'
  // Field errors are shown under each input; anything else (wrong password, network) goes here
  const formError =
    submit.error && !(submit.error instanceof ApiError && (submit.error.code === 'USERNAME_TAKEN' || submit.error.details.field))
      ? submit.error.message
      : null

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-linear-to-br from-indigo-950 via-indigo-900 to-violet-900 p-4">
      <div className="pointer-events-none absolute -top-24 -left-24 size-96 rounded-full bg-violet-500/30 blur-3xl" />
      <div className="pointer-events-none absolute -right-24 -bottom-24 size-96 rounded-full bg-fuchsia-500/25 blur-3xl" />
      <Card className="relative w-full max-w-sm shadow-2xl shadow-black/30">
        <CardHeader>
          <Link to="/" aria-label="MercaNova: volver al catálogo" className="mb-2 w-fit">
            <Logo />
          </Link>
          <CardTitle>{isLogin ? 'Iniciar sesión' : 'Crear cuenta'}</CardTitle>
          <CardDescription>
            {isLogin ? 'Necesitás una cuenta para usar el asistente y el carrito.' : 'Solo usuario y contraseña.'}
          </CardDescription>
        </CardHeader>
        <form onSubmit={onSubmit} noValidate>
          <CardContent className="flex flex-col gap-4">
            <FormField
              id="username"
              label="Usuario"
              value={username}
              onChange={setUsername}
              error={errors.username}
              autoComplete="username"
            />
            <FormField
              id="password"
              label="Contraseña"
              type="password"
              value={password}
              onChange={setPassword}
              error={errors.password}
              autoComplete={isLogin ? 'current-password' : 'new-password'}
            />
            {!isLogin && (
              <FormField
                id="confirm"
                label="Repetí la contraseña"
                type="password"
                value={confirm}
                onChange={setConfirm}
                error={errors.confirm}
                autoComplete="new-password"
              />
            )}
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
          </CardContent>
          <CardFooter className="mt-4 flex flex-col gap-3">
            <Button type="submit" className="w-full" disabled={submit.isPending}>
              {submit.isPending ? 'Un momento…' : isLogin ? 'Entrar' : 'Crear cuenta'}
            </Button>
            <p className="text-sm text-muted-foreground">
              {isLogin ? '¿No tenés cuenta? ' : '¿Ya tenés cuenta? '}
              <Link
                to={isLogin ? '/register' : '/login'}
                state={location.state}
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                {isLogin ? 'Registrate' : 'Iniciá sesión'}
              </Link>
            </p>
            {isLogin && <p className="text-xs text-muted-foreground">Usuario de prueba: demo / demo1234</p>}
          </CardFooter>
        </form>
      </Card>
    </div>
  )
}

function FormField({
  id,
  label,
  value,
  onChange,
  error,
  type = 'text',
  autoComplete,
}: {
  id: Field
  label: string
  value: string
  onChange: (value: string) => void
  error?: string
  type?: string
  autoComplete?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
