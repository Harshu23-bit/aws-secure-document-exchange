import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InternalAxiosRequestConfig } from "axios";

vi.mock("aws-amplify/auth", () => ({
  fetchAuthSession: vi.fn(),
}));

import { fetchAuthSession } from "aws-amplify/auth";
import api from "../api";

const mockFetchAuthSession = vi.mocked(fetchAuthSession);

const validToken = {
  payload: {
    scope: "openid email cloudsec-api/access",
  },
  toString: () => "test-access-token",
};

function createAdapter() {
  return vi.fn(async (config: InternalAxiosRequestConfig) => ({
    data: { success: true },
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  }));
}

describe("API client authentication and request boundaries", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockFetchAuthSession.mockResolvedValue({
      tokens: {
        accessToken: validToken,
      },
    } as never);
  });

  it("attaches the Cognito access token to valid API requests", async () => {
    const adapter = createAdapter();

    await api.get("/tenants", { adapter });

    expect(adapter).toHaveBeenCalledTimes(1);

    const config = adapter.mock.calls[0][0];

    expect(config.headers.Authorization).toBe("Bearer test-access-token");
  });

  it("rejects requests when no access token is available", async () => {
    mockFetchAuthSession.mockResolvedValue({
      tokens: undefined,
    } as never);

    const adapter = createAdapter();

    await expect(api.get("/tenants", { adapter })).rejects.toThrow(
      "No authenticated access token is available.",
    );

    expect(adapter).not.toHaveBeenCalled();
  });

  it("rejects access tokens without the required API scope", async () => {
    mockFetchAuthSession.mockResolvedValue({
      tokens: {
        accessToken: {
          payload: {
            scope: "openid email",
          },
          toString: () => "insufficient-scope-token",
        },
      },
    } as never);

    const adapter = createAdapter();

    await expect(api.get("/tenants", { adapter })).rejects.toThrow(
      "Access token is missing the required API scope.",
    );

    expect(adapter).not.toHaveBeenCalled();
  });

  it("rejects requests to an unexpected external origin before retrieving a token", async () => {
    const adapter = createAdapter();

    await expect(
      api.get("https://attacker.example/collect", { adapter }),
    ).rejects.toThrow("Request target is outside the configured API origin.");

    expect(mockFetchAuthSession).not.toHaveBeenCalled();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("rejects same-origin requests outside the configured API path", async () => {
    const adapter = createAdapter();

    await expect(
      api.get(`${window.location.origin}/api/v10/tenants`, {
        adapter,
      }),
    ).rejects.toThrow("Request target is outside the configured API origin.");

    expect(mockFetchAuthSession).not.toHaveBeenCalled();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("does not send a request when the access token is missing", async () => {
    mockFetchAuthSession.mockResolvedValue({
      tokens: {
        accessToken: undefined,
      },
    } as never);

    const adapter = createAdapter();

    await expect(api.get("/tenants", { adapter })).rejects.toThrow();

    expect(adapter).not.toHaveBeenCalled();
  });
});
