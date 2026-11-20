import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../features/auth/useAuth";
import { consumeReturnTo } from "../features/auth/returnTo";

export default function AuthCallbackPage() {
  const { status, error } = useAuth();
  const navigate = useNavigate();
  const [timedOut, setTimedOut] = useState(false);
  const redirectHandled = useRef(false);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setTimedOut(true);
    }, 15000);

    return () => window.clearTimeout(timeout);
  }, []);

  useEffect(() => {
    if (status === "authenticated" && !redirectHandled.current) {
      redirectHandled.current = true;
      navigate(consumeReturnTo(), { replace: true });
    }
  }, [status, navigate]);

  const showFailure =
    status === "error" ||
    Boolean(error) ||
    (status === "unauthenticated" && timedOut);

  if (showFailure) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6">
        <div className="max-w-md text-center">
          <h1 className="text-xl font-semibold text-white">
            Sign-in could not be completed
          </h1>

          <p className="mt-3 text-sm text-slate-400">
            {error ??
              "We could not establish your Cognito session. Please try signing in again."}
          </p>

          <Link
            to="/login"
            className="mt-6 inline-block rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500"
          >
            Return to sign in
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950">
      <div className="text-center">
        <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-4 border-slate-700 border-t-blue-500" />

        <h1 className="text-lg font-semibold text-white">
          Completing secure sign-in
        </h1>

        <p className="mt-2 text-sm text-slate-400">
          Verifying your Cognito session...
        </p>
      </div>
    </main>
  );
}
