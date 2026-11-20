import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { tenantService } from "../../lib/apiServices";
import { useAuth } from "../auth/useAuth";
import { TenantContext, type TenantContextValue } from "./tenantContext";

function getStorageKey(userId: string): string {
  return `cloudsecure.activeTenant.${userId}`;
}

function getStoredTenantId(userId: string): string | null {
  try {
    return sessionStorage.getItem(getStorageKey(userId));
  } catch {
    return null;
  }
}

function storeTenantId(userId: string, tenantId: string | null): void {
  try {
    const key = getStorageKey(userId);

    if (tenantId) {
      sessionStorage.setItem(key, tenantId);
    } else {
      sessionStorage.removeItem(key);
    }
  } catch {
    // Workspace selection remains functional without session storage.
  }
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "An unexpected error occurred while loading workspace data.";
}

export function TenantProvider({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const userId = user?.userId;

  const [tenantSelection, setTenantSelection] = useState<{
    userId: string;
    tenantId: string;
  } | null>(null);

  const selectedTenantId =
    userId && tenantSelection?.userId === userId
      ? tenantSelection.tenantId
      : userId
        ? getStoredTenantId(userId)
        : null;

  const tenantsQuery = useQuery({
    queryKey: ["tenants", userId],
    queryFn: tenantService.listTenants,
    enabled: status === "authenticated" && Boolean(userId),
    staleTime: 30_000,
    retry: 1,
  });

  const tenants = useMemo(() => tenantsQuery.data ?? [], [tenantsQuery.data]);

  const activeTenant = useMemo(() => {
    if (tenants.length === 0) {
      return null;
    }

    return (
      tenants.find((tenant) => tenant.tenant_id === selectedTenantId) ??
      tenants[0]
    );
  }, [tenants, selectedTenantId]);

  const tenantContextQuery = useQuery({
    queryKey: ["tenant-context", userId, activeTenant?.tenant_id],
    queryFn: () => tenantService.getContext(activeTenant!.tenant_id),
    enabled:
      status === "authenticated" && Boolean(userId) && Boolean(activeTenant),
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    if (!userId || !tenantsQuery.isSuccess) {
      return;
    }

    if (!activeTenant) {
      storeTenantId(userId, null);
      return;
    }

    storeTenantId(userId, activeTenant.tenant_id);
  }, [userId, tenantsQuery.isSuccess, activeTenant]);

  const selectTenant = useCallback(
    (tenantId: string) => {
      const membership = tenants.find(
        (tenant) => tenant.tenant_id === tenantId,
      );

      if (!membership) {
        throw new Error(
          "You do not have an active membership in this workspace.",
        );
      }

      if (userId) {
        setTenantSelection({ userId, tenantId });
      }

      if (userId) {
        storeTenantId(userId, tenantId);
      }
    },
    [tenants, userId],
  );

  const refetchTenants = tenantsQuery.refetch;

  const refreshTenants = useCallback(async () => {
    await refetchTenants();
  }, [refetchTenants]);

  const error = tenantsQuery.isError
    ? getErrorMessage(tenantsQuery.error)
    : tenantContextQuery.isError
      ? getErrorMessage(tenantContextQuery.error)
      : null;

  const value = useMemo<TenantContextValue>(
    () => ({
      tenants,
      activeTenant,
      tenantContext: tenantContextQuery.data ?? null,
      loading:
        status === "authenticated" &&
        (tenantsQuery.isPending ||
          (Boolean(activeTenant) && tenantContextQuery.isPending)),
      error,
      selectTenant,
      refreshTenants,
    }),
    [
      status,
      tenants,
      activeTenant,
      tenantContextQuery.data,
      tenantContextQuery.isPending,
      tenantsQuery.isPending,
      error,
      selectTenant,
      refreshTenants,
    ],
  );

  return (
    <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
  );
}
