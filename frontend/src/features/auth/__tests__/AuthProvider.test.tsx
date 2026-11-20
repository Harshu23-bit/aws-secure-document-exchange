import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchAuthSession: vi.fn(),
  getCurrentUser: vi.fn(),
  signOut: vi.fn(),
  hubListen: vi.fn(),
}));

vi.mock("aws-amplify/auth", () => ({
  fetchAuthSession: mocks.fetchAuthSession,
  getCurrentUser: mocks.getCurrentUser,
  signOut: mocks.signOut,
}));

vi.mock("aws-amplify/utils", () => ({
  Hub: {
    listen: mocks.hubListen,
  },
}));

vi.mock("../../../lib/amplify", () => ({
  amplifyConfigured: true,
}));

import { AuthProvider } from "../AuthProvider";
import { AuthContext } from "../authContext";
import { queryClient } from "../../../lib/queryClient";

type HubEvent = {
  payload: {
    event: string;
  };
};

let authListener: ((data: HubEvent) => void) | undefined;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

function TestConsumer() {
  return (
    <AuthContext.Consumer>
      {(value) => {
        if (!value) return null;

        return (
          <div>
            <span data-testid="status">{value.status}</span>
            <span data-testid="user">{value.user?.userId ?? "none"}</span>
            <span data-testid="error">{value.error ?? "none"}</span>
            <button onClick={() => void value.refreshSession()}>Refresh</button>
            <button onClick={() => void value.logout()}>Logout</button>
          </div>
        );
      }}
    </AuthContext.Consumer>
  );
}

function renderAuthProvider() {
  return render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>,
  );
}

function validSession() {
  return {
    tokens: {
      accessToken: {
        payload: {
          scope: "openid email cloudsec-api/access",
        },
      },
    },
  };
}

function seedQueryCache() {
  queryClient.setQueryData(["sensitive-tenant-data"], {
    tenant: "tenant-a",
  });
}

function expectQueryCacheCleared() {
  expect(queryClient.getQueryData(["sensitive-tenant-data"])).toBeUndefined();
}

describe("AuthProvider", () => {
  beforeEach(() => {
    queryClient.clear();
    authListener = undefined;

    mocks.fetchAuthSession.mockReset();
    mocks.getCurrentUser.mockReset();
    mocks.signOut.mockReset();
    mocks.hubListen.mockReset();

    mocks.hubListen.mockImplementation((_channel, listener) => {
      authListener = listener;
      return vi.fn();
    });

    mocks.fetchAuthSession.mockResolvedValue(validSession());
    mocks.getCurrentUser.mockResolvedValue({
      userId: "user-a",
      username: "user-a",
    });
    mocks.signOut.mockResolvedValue(undefined);
  });

  afterEach(() => {
    queryClient.clear();
  });

  it("authenticates a user with the required access-token scope", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user")).toHaveTextContent("user-a");
    });
  });

  it("clears cached data when no access token exists", async () => {
    seedQueryCache();
    mocks.fetchAuthSession.mockResolvedValue({ tokens: undefined });

    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    });

    expectQueryCacheCleared();
  });

  it("rejects an access token missing the required scope", async () => {
    seedQueryCache();
    mocks.fetchAuthSession.mockResolvedValue({
      tokens: {
        accessToken: {
          payload: {
            scope: "openid email",
          },
        },
      },
    });

    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("error");
      expect(screen.getByTestId("error")).toHaveTextContent(
        "missing the required cloudsec-api/access scope",
      );
    });

    expectQueryCacheCleared();
  });

  it("clears an authenticated user and cached data when a refreshed token lacks the required scope", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user")).toHaveTextContent("user-a");
    });

    seedQueryCache();

    mocks.fetchAuthSession.mockResolvedValue({
      tokens: {
        accessToken: {
          payload: {
            scope: "openid email",
          },
        },
      },
    });

    await act(async () => {
      screen.getByRole("button", { name: "Refresh" }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("error");
      expect(screen.getByTestId("user")).toHaveTextContent("none");
      expect(screen.getByTestId("error")).toHaveTextContent(
        "missing the required cloudsec-api/access scope",
      );
    });

    expectQueryCacheCleared();
  });

  it("clears cached data when session refresh fails", async () => {
    seedQueryCache();
    mocks.fetchAuthSession.mockRejectedValue(new Error("Session unavailable"));

    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    });

    expectQueryCacheCleared();
  });

  it("clears cached data when the authenticated identity changes", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("user-a");
    });

    seedQueryCache();
    mocks.getCurrentUser.mockResolvedValue({
      userId: "user-b",
      username: "user-b",
    });

    await act(async () => {
      screen.getByRole("button", { name: "Refresh" }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("user-b");
    });

    expectQueryCacheCleared();
  });

  it("clears user state and cached data after logout", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    seedQueryCache();

    await act(async () => {
      screen.getByRole("button", { name: "Logout" }).click();
    });

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expectQueryCacheCleared();
  });

  it("clears user state and cached data on a Cognito signedOut event", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    seedQueryCache();

    act(() => {
      authListener?.({ payload: { event: "signedOut" } });
    });

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expectQueryCacheCleared();
  });

  it("clears user state and cached data on redirect failure", async () => {
    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    seedQueryCache();

    act(() => {
      authListener?.({
        payload: { event: "signInWithRedirect_failure" },
      });
    });

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(screen.getByTestId("error")).toHaveTextContent(
      "Cognito sign-in failed",
    );
    expectQueryCacheCleared();
  });

  it("ignores an older refresh that completes after a newer refresh", async () => {
    const olderSession = deferred<ReturnType<typeof validSession>>();

    mocks.fetchAuthSession
      .mockReturnValueOnce(olderSession.promise)
      .mockResolvedValueOnce(validSession());

    mocks.getCurrentUser.mockResolvedValue({
      userId: "user-b",
      username: "user-b",
    });

    renderAuthProvider();

    await waitFor(() => {
      expect(mocks.fetchAuthSession).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      screen.getByRole("button", { name: "Refresh" }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("user")).toHaveTextContent("user-b");
    });

    await act(async () => {
      olderSession.resolve(validSession());
      await olderSession.promise;
    });

    expect(screen.getByTestId("user")).toHaveTextContent("user-b");
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
  });

  it("does not restore authentication when a refresh completes after sign-out", async () => {
    const pendingSession = deferred<ReturnType<typeof validSession>>();

    mocks.fetchAuthSession.mockReturnValueOnce(pendingSession.promise);

    renderAuthProvider();

    await waitFor(() => {
      expect(mocks.fetchAuthSession).toHaveBeenCalledTimes(1);
    });

    act(() => {
      authListener?.({ payload: { event: "signedOut" } });
    });

    await act(async () => {
      pendingSession.resolve(validSession());
      await pendingSession.promise;
    });

    expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("does not clear a newer session when an older logout completes late", async () => {
    const pendingLogout = deferred<void>();

    mocks.signOut.mockReturnValueOnce(pendingLogout.promise);

    renderAuthProvider();

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    act(() => {
      screen.getByRole("button", { name: "Logout" }).click();
    });

    act(() => {
      authListener?.({ payload: { event: "signedIn" } });
    });

    await waitFor(() => {
      expect(mocks.fetchAuthSession).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    });

    await act(async () => {
      pendingLogout.resolve();
      await pendingLogout.promise;
    });

    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("user")).toHaveTextContent("user-a");
  });
});
