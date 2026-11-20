import axios from "axios";
import { fetchAuthSession } from "aws-amplify/auth";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  timeout: 15000,
  headers: {
    Accept: "application/json",
  },
});

api.interceptors.request.use(async (config) => {
  const configuredBase = new URL(
    api.defaults.baseURL || "/api/v1",
    window.location.origin,
  );

  const requestUrl = new URL(api.getUri(config), window.location.origin);

  const basePath = configuredBase.pathname.replace(/\/+$/, "");

  const isWithinApiPath =
    basePath === "" ||
    basePath === "/" ||
    requestUrl.pathname === basePath ||
    requestUrl.pathname.startsWith(`${basePath}/`);

  if (requestUrl.origin !== configuredBase.origin || !isWithinApiPath) {
    throw new Error("Request target is outside the configured API origin.");
  }

  const session = await fetchAuthSession();
  const accessToken = session.tokens?.accessToken;

  if (!accessToken) {
    throw new Error("No authenticated access token is available.");
  }

  const scopeClaim = accessToken.payload.scope;
  const scopes = typeof scopeClaim === "string" ? scopeClaim.split(" ") : [];

  if (!scopes.includes("cloudsec-api/access")) {
    throw new Error("Access token is missing the required API scope.");
  }

  config.headers.Authorization = `Bearer ${accessToken.toString()}`;

  return config;
});

export default api;
