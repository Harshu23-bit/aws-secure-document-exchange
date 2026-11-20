import { createContext } from 'react'
import type {
  TenantMembership,
  TenantContext as TenantContextData,
} from '../../types/api'

export interface TenantContextValue {
  tenants: TenantMembership[]
  activeTenant: TenantMembership | null
  tenantContext: TenantContextData | null
  loading: boolean
  error: string | null
  selectTenant: (tenantId: string) => void
  refreshTenants: () => Promise<void>
}

export const TenantContext = createContext<
  TenantContextValue | undefined
>(undefined)
