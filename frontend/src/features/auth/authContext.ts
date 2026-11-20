import { createContext } from 'react'
import type { GetCurrentUserOutput } from 'aws-amplify/auth'

export type AuthStatus =
  | 'loading'
  | 'authenticated'
  | 'unauthenticated'
  | 'error'

export interface AuthContextValue {
  status: AuthStatus
  user: GetCurrentUserOutput | null
  error: string | null
  refreshSession: () => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(
  undefined,
)
