import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
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
  authStatus: "unauthenticated" as
    | "loading"
    | "authenticated"
    | "unauthenticated"
    | "error",
}));

vi.mock("aws-amplify/auth", () => ({
  signInWithRedirect: mocks.signInWithRedirect,
}));

vi.mock("../../lib/amplify", () => ({
  amplifyConfigured: true,
}));

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: () => ({
    status: mocks.authStatus,
    user:
      mocks.authStatus === "authenticated"
        ? { userId: "user-a", username: "user-a" }
        : null,
    error: null,
    refreshSession: vi.fn(),
    logout: vi.fn(),
  }),
}));

import ProtectedRoute from "../ProtectedRoute";
import LoginPage from "../../pages/LoginPage";
import AuthCallbackPage from "../../pages/AuthCallbackPage";

function SimulateCognitoCallback() {
  const navigate = useNavigate();

  return (
    <button
      type="button"
      onClick={() => navigate("/auth/callback")}
    >
      Simulate Cognito callback
    </button>
  );
}

function renderAuthenticationFlow() {
  return render(
    <MemoryRouter
      initialEntries={["/submissions/123?tab=documents"]}
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          path="/auth/callback"
          element={<AuthCallbackPage />}
        />

        <Route element={<ProtectedRoute />}>
          <Route
            path="/submissions/:submissionId"
            element={<h1>Original submission page</h1>}
          />
        </Route>
      </Routes>

      <SimulateCognitoCallback />
    </MemoryRouter>,
  );
}

describe("Authentication redirect flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();

    mocks.authStatus = "unauthenticated";
    mocks.signInWithRedirect.mockResolvedValue(undefined);
  });

  it("preserves the original destination through login and authentication callback", async () => {
    const user = userEvent.setup();

    const { rerender } = renderAuthenticationFlow();

    // Unauthenticated access redirects to login.
    expect(
      screen.getByRole("heading", {
        name: "Welcome back",
      }),
    ).toBeInTheDocument();

    // Start Cognito authentication.
    await user.click(
      screen.getByRole("button", {
        name: "Continue with Cognito",
      }),
    );

    expect(mocks.signInWithRedirect).toHaveBeenCalledTimes(1);

    expect(
      sessionStorage.getItem("cloudsecure.auth.returnTo"),
    ).toBe("/submissions/123?tab=documents");

    // Simulate Cognito returning the browser to the callback route.
    await user.click(
      screen.getByRole("button", {
        name: "Simulate Cognito callback",
      }),
    );

    expect(
      screen.getByRole("heading", {
        name: "Completing secure sign-in",
      }),
    ).toBeInTheDocument();

    // Simulate successful session restoration by AuthProvider.
    mocks.authStatus = "authenticated";

    rerender(
      <MemoryRouter
        initialEntries={["/submissions/123?tab=documents"]}
      >
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route
            path="/auth/callback"
            element={<AuthCallbackPage />}
          />

          <Route element={<ProtectedRoute />}>
            <Route
              path="/submissions/:submissionId"
              element={<h1>Original submission page</h1>}
            />
          </Route>
        </Routes>

        <SimulateCognitoCallback />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("heading", {
          name: "Original submission page",
        }),
      ).toBeInTheDocument();
    });

    expect(sessionStorage.length).toBe(0);
  });
});
