import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProtectedRoute from "../ProtectedRoute";
import { useAuth } from "../../features/auth/useAuth";

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);

function LocationDisplay() {
  const location = useLocation();
  const state = location.state as { from?: string } | null;

  return (
    <>
      <div data-testid="location">
        {location.pathname}
      </div>
      <div data-testid="return-to">
        {state?.from ?? "none"}
      </div>
    </>
  );
}

function renderProtectedRoute(initialEntry = "/protected") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<h1>Login page</h1>} />

        <Route element={<ProtectedRoute />}>
          <Route
            path="/protected"
            element={<h1>Protected content</h1>}
          />
        </Route>
      </Routes>

      <LocationDisplay />
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state while authentication is being restored", () => {
    mockUseAuth.mockReturnValue({
      status: "loading",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderProtectedRoute();

    expect(
      screen.getByText("Restoring secure session..."),
    ).toBeInTheDocument();

    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });

  it("renders protected content for an authenticated user", () => {
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

    renderProtectedRoute();

    expect(screen.getByText("Protected content")).toBeInTheDocument();
  });

  it("redirects unauthenticated users to login", () => {
    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderProtectedRoute();

    expect(screen.getByText("Login page")).toBeInTheDocument();
    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/login");
    expect(screen.getByTestId("return-to")).toHaveTextContent("/protected",);
  });

  it("displays an authentication configuration error instead of rendering protected content", () => {
    mockUseAuth.mockReturnValue({
      status: "error",
      user: null,
      error: "Missing required API scope",
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderProtectedRoute();

    expect(
      screen.getByRole("heading", {
        name: "Authentication configuration error",
      }),
    ).toBeInTheDocument();

    expect(screen.queryByText("Protected content")).not.toBeInTheDocument();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});
