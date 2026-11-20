import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
} from "react-router-dom";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({
  signInWithRedirect: vi.fn(),
}));

vi.mock("aws-amplify/auth", () => ({
  signInWithRedirect: mocks.signInWithRedirect,
}));

vi.mock("../../lib/amplify", () => ({
  amplifyConfigured: true,
}));

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

import LoginPage from "../LoginPage";
import { useAuth } from "../../features/auth/useAuth";

const mockUseAuth = vi.mocked(useAuth);

function renderLogin(
  initialEntry: string | {
    pathname: string;
    state?: unknown;
  } = "/login",
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={<h1>Dashboard page</h1>}
        />
        <Route
          path="/submissions/:submissionId"
          element={<h1>Submission destination</h1>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();

    mocks.signInWithRedirect.mockResolvedValue(undefined);

    mockUseAuth.mockReturnValue({
      status: "unauthenticated",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });
  });

  it("renders the login page for an unauthenticated user", () => {
    renderLogin();

    expect(
      screen.getByRole("heading", {
        name: "Welcome back",
      }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    ).toBeEnabled();
  });

  it("starts Cognito sign-in when the user clicks the login button", async () => {
    const user = userEvent.setup();

    renderLogin();

    await user.click(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    );

    expect(mocks.signInWithRedirect).toHaveBeenCalledTimes(1);
  });

  it("saves the requested destination before starting Cognito sign-in", async () => {
    const user = userEvent.setup();

    mocks.signInWithRedirect.mockImplementation(async () => {
      expect(
        sessionStorage.getItem("cloudsecure.auth.returnTo"),
      ).toBe("/submissions/123");

      return undefined;
    });

    renderLogin({
      pathname: "/login",
      state: {
        from: "/submissions/123",
      },
    });

    await user.click(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    );

    expect(mocks.signInWithRedirect).toHaveBeenCalledTimes(1);
    expect(
      sessionStorage.getItem("cloudsecure.auth.returnTo"),
    ).toBe("/submissions/123");
  });

  it("does not save an unsafe requested destination", async () => {
    const user = userEvent.setup();

    renderLogin({
      pathname: "/login",
      state: {
        from: "https://evil.example",
      },
    });

    await user.click(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    );

    expect(mocks.signInWithRedirect).toHaveBeenCalledTimes(1);
    expect(
      sessionStorage.getItem("cloudsecure.auth.returnTo"),
    ).toBeNull();
  });

  it("displays an error when Cognito sign-in cannot be started", async () => {
    const user = userEvent.setup();

    mocks.signInWithRedirect.mockRejectedValue(
      new Error("Cognito unavailable"),
    );

    renderLogin();

    await user.click(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to start sign-in. Check the Cognito configuration.",
    );

    expect(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    ).toBeEnabled();
  });

  it("shows a loading state while authentication is being restored", () => {
    mockUseAuth.mockReturnValue({
      status: "loading",
      user: null,
      error: null,
      refreshSession: vi.fn(),
      logout: vi.fn(),
    });

    renderLogin();

    expect(
      screen.getByText("Restoring secure session..."),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("button", {
        name: "Continue with Cognito",
      }),
    ).not.toBeInTheDocument();

    expect(mocks.signInWithRedirect).not.toHaveBeenCalled();
  });

  it("redirects authenticated users to their originally requested destination", async () => {
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

    renderLogin({
      pathname: "/login",
      state: {
        from: "/submissions/123",
      },
    });

    expect(
      await screen.findByRole("heading", {
        name: "Submission destination",
      }),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("button", {
        name: "Continue with Cognito",
      }),
    ).not.toBeInTheDocument();

    expect(mocks.signInWithRedirect).not.toHaveBeenCalled();
  });

  it("redirects authenticated users to the dashboard when no destination exists", async () => {
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

    renderLogin();

    expect(
      await screen.findByRole("heading", {
        name: "Dashboard page",
      }),
    ).toBeInTheDocument();
  });
});
