import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  fetchAuthSession,
  getCurrentUser,
  signOut,
  type GetCurrentUserOutput,
} from "aws-amplify/auth";
import { Hub } from "aws-amplify/utils";
import { amplifyConfigured } from "../../lib/amplify";
import { AuthContext, type AuthStatus } from "./authContext";
import { queryClient } from "../../lib/queryClient";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<GetCurrentUserOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const authenticatedUserIdRef = useRef<string | null>(null);
  const authOperationRef = useRef(0);

  const refreshSession = useCallback(async () => {
    const operation = ++authOperationRef.current;
    if (!amplifyConfigured) {
      queryClient.clear();
      authenticatedUserIdRef.current = null;
      setUser(null);
      setError(null);
      setStatus("unauthenticated");
      return;
    }

    try {
      const session = await fetchAuthSession();
      if (operation !== authOperationRef.current) return;
      const accessToken = session.tokens?.accessToken;

      if (!accessToken) {
        queryClient.clear();
        authenticatedUserIdRef.current = null;
        setUser(null);
        setError(null);
        setStatus("unauthenticated");
        return;
      }

      const scopeClaim = accessToken.payload.scope;
      const scopes =
        typeof scopeClaim === "string" ? scopeClaim.split(" ") : [];

      if (!scopes.includes("cloudsec-api/access")) {
        queryClient.clear();
        authenticatedUserIdRef.current = null;
        setUser(null);
        setStatus("error");
        setError(
          "Your Cognito access token is missing the required cloudsec-api/access scope.",
        );
        return;
      }

      const currentUser = await getCurrentUser();
      if (operation !== authOperationRef.current) return;

      if (
        authenticatedUserIdRef.current !== null &&
        authenticatedUserIdRef.current !== currentUser.userId
      ) {
        queryClient.clear();
      }

      authenticatedUserIdRef.current = currentUser.userId;

      setUser(currentUser);
      setError(null);
      setStatus("authenticated");
    } catch {
      if (operation !== authOperationRef.current) return;

      queryClient.clear();
      authenticatedUserIdRef.current = null;
      setUser(null);
      setError(null);
      setStatus("unauthenticated");
    }
  }, []);

  const logout = useCallback(async () => {
    const operation = ++authOperationRef.current;
    try {
      await signOut();

      if (operation !== authOperationRef.current) return;

      authenticatedUserIdRef.current = null;
      queryClient.clear();
      setUser(null);
      setError(null);
      setStatus("unauthenticated");
    } catch {
      if (operation === authOperationRef.current) {
        setError("Unable to sign out. Please try again.");
      }

      throw new Error("Sign-out failed");
    }
  }, []);

  useEffect(() => {
    const initialize = () => {
      void refreshSession();
    };

    const stopListening = Hub.listen("auth", ({ payload }) => {
      const event = payload.event;

      if (
        event === "signedIn" ||
        event === "signInWithRedirect" ||
        event === "tokenRefresh"
      ) {
        void refreshSession();
      }

      if (event === "signedOut") {
        authOperationRef.current += 1;
        authenticatedUserIdRef.current = null;
        queryClient.clear();
        setUser(null);
        setStatus("unauthenticated");
      }

      if (event === "signInWithRedirect_failure") {
        authOperationRef.current += 1;
        authenticatedUserIdRef.current = null;
        queryClient.clear();
        setUser(null);
        setError("Cognito sign-in failed. Please try again.");
        setStatus("unauthenticated");
      }
    });

    initialize();

    return () => stopListening();
  }, [refreshSession]);

  const value = useMemo(
    () => ({
      status,
      user,
      error,
      refreshSession,
      logout,
    }),
    [status, user, error, refreshSession, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
