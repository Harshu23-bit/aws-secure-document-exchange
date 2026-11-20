import { Outlet } from 'react-router-dom'
import { TenantProvider } from '../features/tenants/TenantProvider'
import { useAuth } from '../features/auth/useAuth'

export default function TenantProtectedLayout() {
  const { user } = useAuth()

  return (
    <TenantProvider key={user?.userId ?? 'unauthenticated'}>
      <Outlet />
    </TenantProvider>
  )
}
