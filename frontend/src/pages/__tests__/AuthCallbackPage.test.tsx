import { act, render, screen } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router-dom";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import AuthCallbackPage from "../AuthCallbackPage";
import { useAuth } from "../../features/auth/useAuth";
import { saveReturnTo } from "../../features/auth/returnTo";

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);

function renderCallback(initialEntry = "/auth/callback") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/auth/callback"
          element={<AuthCallbackPage />}
        />

        <Route
          path="/"
          element={<h1>Dashboard page</h1>}
        />

        <Route
          path="/login"
          element={<h1>Login page</h1>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthCallbackPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows a loading state while authentication is pending", () => {
    mockUseAuth.mockReturnValue({
      status: "loading",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderCallback();

    expect(
      screen.getByRole("heading", {
        name: "Completing secure sign-in",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Verifying your Cognito session..."),
    ).toBeInTheDocument();

    expect(
      screen.queryByText("Dashboard page"),
    ).not.toBeInTheDocument();
  });

  it("redirects to the dashboard after successful authentication", () => {
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

    renderCallback();

    expect(
      screen.getByRole("heading", {
        name: "Dashboard page",
      }),
    ).toBeInTheDocument();

    expect(
      screen.queryByText("Completing secure sign-in"),
    ).not.toBeInTheDocument();
  });

  it("displays the authentication error and a login link", () => {
    mockUseAuth.mockReturnValue({
      status: "error",
      user: null,
      error: "Cognito session validation failed",
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderCallback();

    expect(
      screen.getByRole("heading", {
        name: "Sign-in could not be completed",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Cognito session validation failed"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", {
        name: "Return to sign in",
      }),
    ).toHaveAttribute("href", "/login");
  });

  it("displays an error when authentication remains unauthenticated after 15 seconds", () => {
    vi.useFakeTimers();

    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderCallback();

    expect(
      screen.getByRole("heading", {
        name: "Completing secure sign-in",
      }),
    ).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(15000);
    });

    expect(
      screen.getByRole("heading", {
        name: "Sign-in could not be completed",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        "We could not establish your Cognito session. Please try signing in again.",
      ),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("link", {
        name: "Return to sign in",
      }),
    ).toHaveAttribute("href", "/login");
  });

  it("redirects to the originally requested route after authentication", () => {
    saveReturnTo("/submissions/123?tab=documents");

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

    render(
        <MemoryRouter initialEntries={["/auth/callback"]}>
        <Routes>
            <Route
            path="/auth/callback"
            element={<AuthCallbackPage />}
            />
            <Route
            path="/submissions/:submissionId"
            element={<h1>Submission destination</h1>}
            />
        </Routes>
        </MemoryRouter>,
    );

    expect(
        screen.getByRole("heading", {
        name: "Submission destination",
        }),
    ).toBeInTheDocument();

    expect(sessionStorage.length).toBe(0);
    });

  it("falls back to the dashboard when the saved destination is unsafe", () => {
    sessionStorage.setItem(
        "cloudsecure.auth.returnTo",
        "//evil.example",
    );

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

    render(
        <MemoryRouter initialEntries={["/auth/callback"]}>
        <Routes>
            <Route
            path="/auth/callback"
            element={<AuthCallbackPage />}
            />
            <Route
            path="/"
            element={<h1>Dashboard page</h1>}
            />
        </Routes>
        </MemoryRouter>,
    );

    expect(
        screen.getByRole("heading", {
        name: "Dashboard page",
        }),
    ).toBeInTheDocument();

    expect(sessionStorage.length).toBe(0);
    });
});
