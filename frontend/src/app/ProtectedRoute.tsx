import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../features/auth/useAuth";

export default function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-slate-500">Restoring secure session...</p>
      </main>
    );
  }

  if (status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <div className="max-w-lg text-center">
          <h1 className="text-xl font-semibold text-red-600">
            Authentication configuration error
          </h1>
          <p className="mt-3 text-sm text-slate-600">
            Your access token does not contain the required API scope.
            Verify the Cognito app client and resource server configuration.
          </p>
        </div>
      </main>
    );
  }

  return status === "authenticated" ? (
    <Outlet />
  ) : (
    <Navigate
      to="/login"
      replace
      state={{
        from: `${location.pathname}${location.search}${location.hash}`,
      }}
    />
  );
}
