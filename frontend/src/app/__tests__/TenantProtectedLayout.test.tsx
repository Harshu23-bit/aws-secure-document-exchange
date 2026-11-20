import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TenantProtectedLayout from "../TenantProtectedLayout";
import { useAuth } from "../../features/auth/useAuth";

const mocks = vi.hoisted(() => ({
  tenantProviderMounts: vi.fn(),
}));

vi.mock("../../features/tenants/TenantProvider", () => ({
  TenantProvider: ({
    children,
  }: {
    children: React.ReactNode;
  }) => {
    mocks.tenantProviderMounts();

    return <>{children}</>;
  },
}));

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<TenantProtectedLayout />}>
          <Route path="/" element={<h1>Protected dashboard</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("TenantProtectedLayout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("wraps protected content in the tenant provider", () => {
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      user: {
        userId: "user-a",
        username: "user-a",
      } as NonNullable<ReturnType<typeof useAuth>["user"]>,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderLayout();

    expect(screen.getByText("Protected dashboard")).toBeInTheDocument();
    expect(mocks.tenantProviderMounts).toHaveBeenCalledTimes(1);
  });

  it("keys the tenant provider using the authenticated user ID", () => {
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      user: {
        userId: "user-a",
        username: "user-a",
      } as NonNullable<ReturnType<typeof useAuth>["user"]>,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    const { rerender } = renderLayout();

    expect(mocks.tenantProviderMounts).toHaveBeenCalledTimes(1);

    mockUseAuth.mockReturnValue({
      status: "authenticated",
      user: {
        userId: "user-b",
        username: "user-b",
      } as NonNullable<ReturnType<typeof useAuth>["user"]>,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<TenantProtectedLayout />}>
            <Route path="/" element={<h1>Protected dashboard</h1>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(mocks.tenantProviderMounts).toHaveBeenCalledTimes(2);
  });

  it("uses an unauthenticated fallback key when no user exists", () => {
    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderLayout();

    expect(screen.getByText("Protected dashboard")).toBeInTheDocument();
    expect(mocks.tenantProviderMounts).toHaveBeenCalledTimes(1);
  });
});
