import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TenantProvider } from "../TenantProvider";
import { useTenant } from "../useTenant";
import { tenantService } from "../../../lib/apiServices";
import { useAuth } from "../../auth/useAuth";
import type { TenantContext, TenantMembership } from "../../../types/api";

vi.mock("../../auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../../lib/apiServices", () => ({
  tenantService: {
    listTenants: vi.fn(),
    getContext: vi.fn(),
  },
}));

const mockUseAuth = vi.mocked(useAuth);
const mockListTenants = vi.mocked(tenantService.listTenants);
const mockGetContext = vi.mocked(tenantService.getContext);

const userA = { userId: "user-a" } as NonNullable<
  ReturnType<typeof useAuth>["user"]
>;

const userB = { userId: "user-b" } as NonNullable<
  ReturnType<typeof useAuth>["user"]
>;

const tenantA: TenantMembership = {
  tenant_id: "tenant-a",
  role: "TENANT_ADMIN",
};

const tenantB: TenantMembership = {
  tenant_id: "tenant-b",
  role: "SUBMITTER",
};

const tenantC: TenantMembership = {
  tenant_id: "tenant-c",
  role: "REVIEWER",
};

const contextA: TenantContext = {
  tenant_id: "tenant-a",
  user_id: "user-a",
  role: "TENANT_ADMIN",
};

const contextB: TenantContext = {
  tenant_id: "tenant-b",
  user_id: "user-a",
  role: "SUBMITTER",
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TenantProvider>{children}</TenantProvider>
      </QueryClientProvider>
    );
  }

  return { Wrapper, queryClient };
}

function setAuthenticatedUser(user = userA) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    user,
    error: null,
    refreshSession: vi.fn(),
    logout: vi.fn(),
  });
}

describe("TenantProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();

    setAuthenticatedUser();

    mockListTenants.mockResolvedValue([tenantA, tenantB]);
    mockGetContext.mockImplementation(async (tenantId) => {
      if (tenantId === tenantA.tenant_id) return contextA;
      if (tenantId === tenantB.tenant_id) return contextB;

      throw new Error("Unexpected tenant ID");
    });
  });

  it("does not fetch tenants when the user is unauthenticated", async () => {
    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(mockListTenants).not.toHaveBeenCalled();
    expect(mockGetContext).not.toHaveBeenCalled();
    expect(result.current.tenants).toEqual([]);
    expect(result.current.activeTenant).toBeNull();
  });

  it("selects the first authorized tenant by default", async () => {
    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantA);
      expect(result.current.tenantContext).toEqual(contextA);
    });

    expect(mockListTenants).toHaveBeenCalledTimes(1);
    expect(mockListTenants).toHaveBeenCalledTimes(1);
    expect(mockGetContext).toHaveBeenCalledWith("tenant-a");
  });

  it("restores a previously selected authorized tenant", async () => {
    sessionStorage.setItem("cloudsecure.activeTenant.user-a", "tenant-b");

    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantB);
      expect(result.current.tenantContext).toEqual(contextB);
    });

    expect(mockGetContext).toHaveBeenCalledWith("tenant-b");
  });

  it("falls back to the first tenant when the stored selection is unauthorized", async () => {
    sessionStorage.setItem(
      "cloudsecure.activeTenant.user-a",
      "tenant-not-authorized",
    );

    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantA);
      expect(result.current.tenantContext).toEqual(contextA);
    });

    expect(mockGetContext).toHaveBeenCalledWith("tenant-a");
  });

  it("rejects selecting a tenant the user does not belong to", async () => {
    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.tenants).toHaveLength(2);
    });

    expect(() => {
      act(() => {
        result.current.selectTenant("tenant-c");
      });
    }).toThrow("You do not have an active membership in this workspace.");

    expect(result.current.activeTenant).toEqual(tenantA);
  });

  it("switches tenant context when an authorized tenant is selected", async () => {
    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.tenantContext).toEqual(contextA);
    });

    act(() => {
      result.current.selectTenant("tenant-b");
    });

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantB);
      expect(result.current.tenantContext).toEqual(contextB);
    });

    expect(mockGetContext).toHaveBeenCalledWith("tenant-b");
    expect(sessionStorage.getItem("cloudsecure.activeTenant.user-a")).toBe(
      "tenant-b",
    );
  });

  it("keeps tenant selections isolated by user", async () => {
    sessionStorage.setItem("cloudsecure.activeTenant.user-a", "tenant-b");
    sessionStorage.setItem("cloudsecure.activeTenant.user-b", "tenant-c");

    mockListTenants.mockImplementation(async () => {
      const currentUserId =
        mockUseAuth.mock.results.at(-1)?.value?.user?.userId;

      if (currentUserId === "user-b") return [tenantB, tenantC];

      return [tenantA, tenantB];
    });

    mockGetContext.mockImplementation(async (tenantId) => {
      const currentUserId =
        mockUseAuth.mock.results.at(-1)?.value?.user?.userId;

      if (tenantId === "tenant-b") {
        return {
          tenant_id: "tenant-b",
          user_id: currentUserId,
          role: "SUBMITTER",
        };
      }

      if (tenantId === "tenant-c") {
        return {
          tenant_id: "tenant-c",
          user_id: "user-b",
          role: "REVIEWER",
        };
      }

      return contextA;
    });

    const { Wrapper } = createWrapper();

    const { result, rerender } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantB);
    });

    setAuthenticatedUser(userB);

    rerender();

    await waitFor(() => {
      expect(result.current.activeTenant).toEqual(tenantC);
      expect(result.current.tenantContext).toEqual({
        tenant_id: "tenant-c",
        user_id: "user-b",
        role: "REVIEWER",
      });
    });

    expect(sessionStorage.getItem("cloudsecure.activeTenant.user-a")).toBe(
      "tenant-b",
    );

    expect(sessionStorage.getItem("cloudsecure.activeTenant.user-b")).toBe(
      "tenant-c",
    );
  });

  it("exposes tenant loading errors", async () => {
    mockListTenants.mockRejectedValue(
      new Error("Unable to load tenant memberships"),
    );

    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(
      () => {
        expect(result.current.error).toBe("Unable to load tenant memberships");
      },
      { timeout: 5000 },
    );

    expect(result.current.activeTenant).toBeNull();
    expect(mockGetContext).not.toHaveBeenCalled();
  });

  it("refreshes tenant memberships when refreshTenants is called", async () => {
    const { Wrapper } = createWrapper();

    const { result } = renderHook(() => useTenant(), {
      wrapper: Wrapper,
    });

    await waitFor(() => {
      expect(result.current.tenants).toEqual([tenantA, tenantB]);
    });

    mockListTenants.mockResolvedValue([tenantB, tenantC]);

    await act(async () => {
      await result.current.refreshTenants();
    });

    await waitFor(() => {
      expect(result.current.tenants).toEqual([tenantB, tenantC]);
    });

    expect(mockListTenants).toHaveBeenCalledTimes(2);
  });
});
