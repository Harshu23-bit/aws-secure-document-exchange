import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  FileText,
  FolderOpen,
  Users,
  ClipboardList,
  Settings,
  ShieldCheck,
  ArrowUpRight,
  Clock3,
  CheckCircle2,
  AlertCircle,
  Menu,
  X,
  ChevronDown,
  LogOut,
  RefreshCw,
  Building2,
  Plus,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../features/auth/useAuth";
import { useTenant } from "../features/tenants/useTenant";
import { submissionService } from "../lib/apiServices";
import TeamMembersPanel from "../features/tenants/TeamMembersPanel";
import CreateSubmissionModal from "../features/submissions/CreateSubmissionModal";
import TenantAuditPanel from "../features/audit/TenantAuditPanel";

const PAGE_SIZE = 20;

const navigation = [
  { label: "Overview", icon: LayoutDashboard, available: true },
  { label: "Submissions", icon: FileText, available: true },
  { label: "Documents", icon: FolderOpen, available: false },
  { label: "Team members", icon: Users, available: true },
  { label: "Audit activity", icon: ClipboardList, available: true },
];

const statusStyles: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-600 ring-slate-500/20",
  SUBMITTED: "bg-blue-50 text-blue-700 ring-blue-600/20",
  IN_REVIEW: "bg-amber-50 text-amber-700 ring-amber-600/20",
  APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  REJECTED: "bg-red-50 text-red-700 ring-red-600/20",
  NEEDS_CHANGES: "bg-orange-50 text-orange-700 ring-orange-600/20",
  CLOSED: "bg-slate-200 text-slate-700 ring-slate-500/20",
};

function formatStatus(status: string): string {
  return status
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function getInitials(value: string): string {
  const parts = value
    .trim()
    .split(/[\s._@-]+/)
    .filter(Boolean);

  if (parts.length === 0) {
    return "U";
  }

  return parts
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
        statusStyles[status] ?? statusStyles.DRAFT
      }`}
    >
      {formatStatus(status)}
    </span>
  );
}

function MetricCard({
  label,
  value,
  description,
  icon: Icon,
  iconStyle,
}: {
  label: string;
  value: number;
  description: string;
  icon: typeof FileText;
  iconStyle: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <div className={`rounded-lg p-2 ${iconStyle}`}>
          <Icon size={19} />
        </div>
      </div>

      <p className="mt-4 text-3xl font-semibold tracking-tight text-slate-900">
        {value}
      </p>

      <p className="mt-1 text-xs text-slate-500">{description}</p>
    </div>
  );
}

interface SubmissionTableProps {
  submissions: Awaited<ReturnType<typeof submissionService.list>>["items"];
  onSelect: (submissionId: string) => void;
}

function SubmissionTable({ submissions, onSelect }: SubmissionTableProps) {
  if (submissions.length === 0) {
    return (
      <div className="px-5 py-16 text-center">
        <FileText className="mx-auto text-slate-300" size={36} />

        <h3 className="mt-4 font-semibold text-slate-800">
          No submissions yet
        </h3>

        <p className="mt-1 text-sm text-slate-500">
          Submissions created in this workspace will appear here.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-left">
        <thead className="bg-slate-50">
          <tr className="text-xs font-medium uppercase tracking-wide text-slate-500">
            <th className="px-5 py-3">Submission</th>
            <th className="px-5 py-3">Documents</th>
            <th className="px-5 py-3">Last updated</th>
            <th className="px-5 py-3">Status</th>
          </tr>
        </thead>

        <tbody className="divide-y divide-slate-100">
          {submissions.map((submission) => (
            <tr
              key={submission.submission_id}
              onClick={() => onSelect(submission.submission_id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(submission.submission_id);
                }
              }}
              tabIndex={0}
              role="link"
              aria-label={`Open documents for ${submission.title}`}
              className="cursor-pointer transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500"
            >
              <td className="px-5 py-4">
                <p className="text-sm font-medium text-slate-800">
                  {submission.title}
                </p>

                <p className="mt-1 text-xs text-slate-400">
                  {submission.submission_id}
                </p>
              </td>

              <td className="px-5 py-4">
                <p className="text-sm text-slate-700">
                  {submission.uploaded_document_count} uploaded
                </p>

                {submission.pending_document_count > 0 && (
                  <p className="mt-1 text-xs text-amber-600">
                    {submission.pending_document_count} pending
                  </p>
                )}
              </td>

              <td className="px-5 py-4 text-sm text-slate-500">
                {formatDate(submission.updated_at)}
              </td>

              <td className="px-5 py-4">
                <StatusBadge status={submission.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DashboardPage() {
  const [activePage, setActivePage] = useState("Overview");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);

  const navigate = useNavigate();

  const { user, logout } = useAuth();

  const {
    tenants,
    activeTenant,
    tenantContext,
    loading: tenantLoading,
    error: tenantError,
    selectTenant,
    refreshTenants,
  } = useTenant();

  const tenantId = activeTenant?.tenant_id;
  const userId = user?.userId;

  const submissionsQuery = useInfiniteQuery({
    queryKey: ["submissions", userId, tenantId, PAGE_SIZE],
    enabled: Boolean(userId && tenantId),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      submissionService.list(tenantId!, {
        limit: PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    getNextPageParam: (lastPage) =>
      lastPage.next_cursor ?? undefined,
    staleTime: 15_000,
    retry: 1,
  });

  const submissions =
  submissionsQuery.data?.pages.flatMap((page) => page.items) ?? [];

  const totalLoaded = submissions.length;

  const pendingReview = submissions.filter(
    (item) => item.status === "SUBMITTED" || item.status === "IN_REVIEW",
  ).length;

  const approved = submissions.filter(
    (item) => item.status === "APPROVED",
  ).length;

  const needsChanges = submissions.filter(
    (item) => item.status === "NEEDS_CHANGES",
  ).length;

  const uploadedDocuments = submissions.reduce(
    (total, item) => total + item.uploaded_document_count,
    0,
  );

  const pendingDocuments = submissions.reduce(
    (total, item) => total + item.pending_document_count,
    0,
  );

  const displayName = user?.username ?? "User";
  const initials = getInitials(displayName);
  const role = tenantContext?.role ?? activeTenant?.role ?? "Unknown";

  async function handleLogout() {
    try {
      await logout();
      navigate("/login", { replace: true });
    } catch {
      // AuthProvider exposes the sign-out failure through its error state.
    }
  }

  const submissionsPanel = (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-5">
        <div>
          <h3 className="font-semibold text-slate-900">
            {activePage === "Overview" ? "Recent submissions" : "Submissions"}
          </h3>

          <p className="mt-1 text-xs text-slate-500">
            {totalLoaded} submissions loaded from this workspace.
          </p>
        </div>

        {activePage === "Overview" && (
          <button
            onClick={() => setActivePage("Submissions")}
            className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700"
          >
            View all <ArrowUpRight size={15} />
          </button>
        )}

        <button
          onClick={() => void submissionsQuery.refetch()}
          disabled={submissionsQuery.isFetching}
          aria-label="Refresh submissions"
          className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 disabled:opacity-50"
        >
          <RefreshCw
            size={17}
            className={submissionsQuery.isFetching ? "animate-spin" : ""}
          />
        </button>
      </div>

      {submissionsQuery.isPending ? (
        <div className="px-5 py-16 text-center">
          <RefreshCw className="mx-auto animate-spin text-blue-500" size={26} />
          <p className="mt-3 text-sm text-slate-500">Loading submissions...</p>
        </div>
      ) : submissionsQuery.isError && !submissionsQuery.data ? (
        <div className="px-5 py-12 text-center">
          <AlertCircle className="mx-auto text-red-500" size={30} />

          <p className="mt-3 text-sm font-medium text-slate-800">
            Unable to load submissions
          </p>

          <p className="mt-1 text-xs text-slate-500">
            {submissionsQuery.error instanceof Error
              ? submissionsQuery.error.message
              : "An unexpected error occurred."}
          </p>

          <button
            onClick={() => void submissionsQuery.refetch()}
            className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Try again
          </button>
        </div>
      ) : (
        <SubmissionTable
          submissions={
            activePage === "Overview" ? submissions.slice(0, 5) : submissions
          }
          onSelect={(id) => navigate(`/submissions/${encodeURIComponent(id)}`)}
        />
      )}

      {submissionsQuery.hasNextPage && (
        <div className="border-t border-slate-100 px-5 py-4">
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => void submissionsQuery.fetchNextPage()}
              disabled={submissionsQuery.isFetchingNextPage}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submissionsQuery.isFetchingNextPage
                ? "Loading..."
                : submissionsQuery.isFetchNextPageError
                  ? "Retry loading more"
                  : "Load more submissions"}
            </button>
          </div>

          {submissionsQuery.isFetchNextPageError && (
            <p
              role="alert"
              className="mt-2 text-center text-sm text-red-600"
            >
              Unable to load more submissions. Previously loaded submissions are still available.
            </p>
          )}
        </div>
      )}

      <div className="border-t border-slate-100 px-5 py-3">
        <p className="text-xs text-slate-400">
          Showing {totalLoaded} submissions across loaded pages.
          {submissionsQuery.hasNextPage
            ? " More submissions are available."
            : ""}{" "}
          Statistics reflect loaded submissions only.
        </p>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50">
      {sidebarOpen && (
        <button
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-slate-950/40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-[#111c32] text-white transition-transform duration-200 lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-20 items-center justify-between border-b border-white/10 px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500">
              <ShieldCheck size={21} strokeWidth={2.2} />
            </div>

            <div>
              <p className="text-base font-semibold tracking-wide">
                CloudSecure
              </p>
              <p className="text-[11px] text-slate-400">Document Workspace</p>
            </div>
          </div>

          <button
            className="text-slate-400 hover:text-white lg:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close sidebar"
          >
            <X size={20} />
          </button>
        </div>

        <div className="px-4 py-6">
          <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Workspace
          </p>

          <nav className="space-y-1">
            {navigation.map(({ label, icon: Icon, available }) => {
              const active = activePage === label;

              return (
                <button
                  key={label}
                  disabled={!available}
                  title={available ? label : "Coming soon"}
                  onClick={() => {
                    if (!available) return;
                    setActivePage(label);
                    setSidebarOpen(false);
                  }}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition ${
                    active
                      ? "bg-blue-500/15 font-medium text-blue-300"
                      : available
                        ? "text-slate-400 hover:bg-white/5 hover:text-white"
                        : "cursor-not-allowed text-slate-600"
                  }`}
                >
                  <Icon size={18} />
                  {label}
                  {!available && (
                    <span className="ml-auto text-[9px] uppercase tracking-wide">
                      Soon
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto border-t border-white/10 p-4">
          <button
            disabled
            title="Settings are not implemented yet"
            className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-600"
          >
            <Settings size={18} />
            Settings
          </button>

          <div className="mt-4 flex items-center gap-3 rounded-lg bg-white/5 p-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-sm font-semibold">
              {initials}
            </div>

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{displayName}</p>
              <p className="truncate text-xs text-slate-400">{role}</p>
            </div>

            <button
              onClick={() => void handleLogout()}
              aria-label="Sign out"
              title="Sign out"
              className="rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex min-h-20 items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 py-3 sm:px-8">
          <div className="flex items-center gap-4">
            <button
              className="text-slate-600 lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={22} />
            </button>

            <div>
              <p className="text-sm text-slate-500">Workspace / {activePage}</p>
              <h1 className="text-lg font-semibold text-slate-900">
                {activePage}
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <Building2 size={16} className="shrink-0 text-slate-500" />

              <select
                aria-label="Select workspace"
                value={activeTenant?.tenant_id ?? ""}
                disabled={tenantLoading || tenants.length === 0}
                onChange={(event) => {
                  selectTenant(event.target.value);
                  setActivePage("Overview");
                }}
                className="max-w-[150px] bg-transparent text-sm font-medium text-slate-700 outline-none sm:max-w-[220px]"
              >
                {tenants.length === 0 && (
                  <option value="">No workspaces</option>
                )}

                {tenants.map((tenant) => (
                  <option key={tenant.tenant_id} value={tenant.tenant_id}>
                    {tenant.tenant_id}
                  </option>
                ))}
              </select>

              <ChevronDown size={14} className="text-slate-400" />
            </div>

            <div className="hidden h-8 border-l border-slate-200 sm:block" />

            <div className="hidden items-center gap-2 sm:flex">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700">
                {initials}
              </span>

              <div className="max-w-[150px]">
                <p className="truncate text-sm font-medium text-slate-700">
                  {displayName}
                </p>
                <p className="truncate text-xs text-slate-400">{role}</p>
              </div>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1440px] space-y-8 p-5 sm:p-8">
          {tenantError ? (
            <section className="rounded-xl border border-red-200 bg-white p-8 text-center">
              <AlertCircle className="mx-auto text-red-500" size={32} />
              <h2 className="mt-3 font-semibold text-slate-900">
                Unable to load workspaces
              </h2>
              <p className="mt-2 text-sm text-slate-500">{tenantError}</p>
              <button
                onClick={() => void refreshTenants()}
                className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Retry
              </button>
            </section>
          ) : tenantLoading ? (
            <section className="rounded-xl border border-slate-200 bg-white p-12 text-center">
              <RefreshCw
                className="mx-auto animate-spin text-blue-500"
                size={28}
              />
              <p className="mt-3 text-sm text-slate-500">
                Loading workspace...
              </p>
            </section>
          ) : !activeTenant ? (
            <section className="rounded-xl border border-slate-200 bg-white p-12 text-center">
              <Building2 className="mx-auto text-slate-300" size={36} />
              <h2 className="mt-4 font-semibold text-slate-900">
                No workspace membership found
              </h2>
              <p className="mt-2 text-sm text-slate-500">
                Your account is not currently associated with an active
                workspace. Contact a workspace administrator.
              </p>
            </section>
          ) : (
            <>
              <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                <div>
                  <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
                    Welcome back, {displayName}
                  </h2>

                  <p className="mt-1 text-sm text-slate-500">
                    Here's what's happening in your workspace.
                  </p>

                  <p className="mt-2 text-xs font-medium text-slate-400">
                    {activeTenant.tenant_id} · {role}
                  </p>
                </div>

                {role === "SUBMITTER" && (
                  <button
                    onClick={() => setShowCreateModal(true)}
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
                  >
                    <Plus size={17} />
                    New submission
                  </button>
                )}
              </section>

              {activePage === "Overview" && (
                <>
                  <section className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
                    <MetricCard
                      label="Loaded submissions"
                      value={totalLoaded}
                      description={`Of the first ${PAGE_SIZE} API results`}
                      icon={FileText}
                      iconStyle="bg-blue-50 text-blue-600"
                    />

                    <MetricCard
                      label="Pending review"
                      value={pendingReview}
                      description="Submitted or in review"
                      icon={Clock3}
                      iconStyle="bg-amber-50 text-amber-600"
                    />

                    <MetricCard
                      label="Approved"
                      value={approved}
                      description="In loaded submissions"
                      icon={CheckCircle2}
                      iconStyle="bg-emerald-50 text-emerald-600"
                    />

                    <MetricCard
                      label="Needs changes"
                      value={needsChanges}
                      description="In loaded submissions"
                      icon={AlertCircle}
                      iconStyle="bg-red-50 text-red-600"
                    />
                  </section>

                  <section className="grid gap-6 xl:grid-cols-[1.65fr_1fr]">
                    {submissionsPanel}

                    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
                      <div className="border-b border-slate-100 px-5 py-5">
                        <h3 className="font-semibold text-slate-900">
                          Document overview
                        </h3>
                        <p className="mt-1 text-xs text-slate-500">
                          Document counts from loaded submissions.
                        </p>
                      </div>

                      <div className="space-y-5 p-5">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <div className="rounded-lg bg-emerald-50 p-2 text-emerald-600">
                              <CheckCircle2 size={19} />
                            </div>
                            <span className="text-sm text-slate-600">
                              Uploaded documents
                            </span>
                          </div>

                          <span className="text-xl font-semibold text-slate-900">
                            {uploadedDocuments}
                          </span>
                        </div>

                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <div className="rounded-lg bg-amber-50 p-2 text-amber-600">
                              <Clock3 size={19} />
                            </div>
                            <span className="text-sm text-slate-600">
                              Pending uploads
                            </span>
                          </div>

                          <span className="text-xl font-semibold text-slate-900">
                            {pendingDocuments}
                          </span>
                        </div>

                        <div className="border-t border-slate-100 pt-4">
                          <p className="text-xs leading-5 text-slate-500">
                            These figures are derived from the submission list.
                            They are not workspace-wide totals.
                          </p>
                        </div>

                        <div className="rounded-lg bg-blue-50 p-4">
                          <div className="flex items-center gap-2 text-blue-700">
                            <ShieldCheck size={18} />
                            <span className="text-sm font-semibold">
                              Workspace access
                            </span>
                          </div>

                          <p className="mt-2 text-xs leading-5 text-blue-800">
                            Your current membership role is {role}. API
                            authorization is enforced by the backend.
                          </p>
                        </div>
                      </div>
                    </div>
                  </section>
                </>
              )}
              {activePage === "Submissions" && submissionsPanel}
              {activePage === "Team members" && (
                <TeamMembersPanel
                  tenantId={activeTenant.tenant_id}
                  currentUserId={userId ?? ""}
                  role={role}
                />
              )}

              {activePage === "Audit activity" && (
                <TenantAuditPanel
                  tenantId={activeTenant.tenant_id}
                  userId={userId ?? ""}
                  role={role}
                />
              )}

              <section className="flex flex-col justify-between gap-4 rounded-xl border border-blue-100 bg-blue-50/70 p-5 sm:flex-row sm:items-center">
                <div className="flex items-start gap-3">
                  <div className="rounded-lg bg-blue-100 p-2 text-blue-700">
                    <ShieldCheck size={20} />
                  </div>

                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">
                      Your workspace is protected
                    </h3>

                    <p className="mt-1 text-xs leading-5 text-slate-600">
                      Tenant membership, workflow permissions and document
                      access are enforced by the backend.
                    </p>
                  </div>
                </div>

                <span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
                  <CheckCircle2 size={14} />
                  Security controls enabled
                </span>
              </section>
            </>
          )}
        </main>
      </div>

      {showCreateModal && activeTenant && userId && role === "SUBMITTER" && (
        <CreateSubmissionModal
          tenantId={activeTenant.tenant_id}
          userId={userId}
          onClose={() => setShowCreateModal(false)}
        />
      )}
    </div>
  );
}
