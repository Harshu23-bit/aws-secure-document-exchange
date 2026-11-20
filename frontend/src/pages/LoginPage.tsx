import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { signInWithRedirect } from 'aws-amplify/auth'
import { ShieldCheck } from 'lucide-react'

import { useAuth } from '../features/auth/useAuth'
import { saveReturnTo, getSafeReturnPath } from '../features/auth/returnTo'
import { amplifyConfigured } from '../lib/amplify'

export default function LoginPage() {
  const { status } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const locationState = location.state as { from?: unknown } | null
  const returnPath = getSafeReturnPath(locationState?.from) ?? '/'

  useEffect(() => {
    if (status === 'authenticated') {
      navigate(returnPath, { replace: true })
    }
  }, [status, returnPath, navigate])

  const handleLogin = async () => {
    if (!amplifyConfigured) {
      setError('Cognito configuration is missing. Configure frontend/.env.local.')
      return
    }

    try {
      setLoading(true)
      setError(null)

      saveReturnTo(locationState?.from)

      await signInWithRedirect()
    } catch {
      setLoading(false)
      setError('Unable to start sign-in. Check the Cognito configuration.')
    }
  }

  if (status === 'loading') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950">
        <p className="text-slate-400">Restoring secure session...</p>
      </main>
    )
  }

  if (status === 'authenticated') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950">
        <p className="text-slate-400">Redirecting to your workspace...</p>
      </main>
    )
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <section className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
        <div className="mb-8 flex items-center gap-3">
          <div className="rounded-xl bg-blue-600 p-3 text-white">
            <ShieldCheck size={28} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">
              CloudSecure
            </h1>
            <p className="text-sm text-slate-400">
              Secure document workflow
            </p>
          </div>
        </div>

        <h2 className="mb-2 text-2xl font-semibold text-white">
          Welcome back
        </h2>
        <p className="mb-8 text-sm text-slate-400">
          Sign in securely to access your organization's workspace.
        </p>

        <button
          type="button"
          onClick={handleLogin}
          disabled={loading || !amplifyConfigured}
          className="w-full rounded-lg bg-blue-600 px-4 py-3 font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? 'Redirecting to sign in...' : 'Continue with Cognito'}
        </button>

        {!amplifyConfigured && (
          <p className="mt-4 text-sm text-amber-400">
            Cognito environment variables are not configured.
          </p>
        )}

        {error && (
          <p role="alert" className="mt-4 text-sm text-red-400">
            {error}
          </p>
        )}

        <p className="mt-8 text-center text-xs text-slate-500">
          Authentication secured by Amazon Cognito
        </p>
      </section>
    </main>
  )
}