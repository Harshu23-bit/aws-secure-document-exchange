import { useInfiniteQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  AlertCircle,
  ArrowRight,
  Clock,
  FileText,
  History,
  RefreshCw,
  ShieldCheck,
  UserRound,
  Users,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { auditService } from "../../lib/apiServices";
import type { TenantAuditEvent, TenantRole } from "../../types/api";

const PAGE_SIZE = 20;

interface TenantAuditPanelProps {
  tenantId: string;
  userId: string;
  role: TenantRole | "Unknown";
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

function formatValue(value: string): string {
  return value.replaceAll("_", " ");
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    if (error.response?.status === 403) {
      return "Your account is not authorized to view workspace-wide audit activity.";
    }

    if (error.response?.status === 404) {
      return "The audit endpoint could not be found. Verify the backend deployment.";
    }

    if (error.response?.status && error.response.status >= 500) {
      return "The audit service encountered an internal error. Please try again.";
    }
  }

  return "Unable to retrieve audit activity. Check your connection and try again.";
}

function EventDescription({ event }: { event: TenantAuditEvent }) {
  switch (event.event_type) {
    case "SUBMISSION_STATUS_CHANGED":
      return (
        <>
          <p className="text-sm font-semibold text-slate-800">
            Submission status changed
          </p>

          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span>{formatValue(event.previous_status)}</span>
            <ArrowRight size={14} />
            <span className="font-medium text-slate-800">
              {formatValue(event.new_status)}
            </span>
          </p>

          <p className="mt-2 text-xs text-slate-500">
            Version {event.previous_version} → {event.new_version}
          </p>

          {event.reason && (
            <div className="mt-3 rounded-lg bg-slate-50 p-3">
              <p className="text-xs font-semibold text-slate-600">
                Reason / feedback
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                {event.reason}
              </p>
            </div>
          )}
        </>
      );

    case "MEMBERSHIP_ROLE_CHANGED":
      return (
        <>
          <p className="text-sm font-semibold text-slate-800">
            Member role changed
          </p>

          <p className="mt-1 text-sm text-slate-600">
            <span className="font-medium text-slate-800">
              {event.target_user_id}
            </span>
          </p>

          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            {formatValue(event.previous_role)}
            <ArrowRight size={14} />
            <span className="font-medium text-slate-800">
              {formatValue(event.new_role)}
            </span>
          </p>
        </>
      );

    case "MEMBERSHIP_DEACTIVATED":
      return (
        <>
          <p className="text-sm font-semibold text-slate-800">
            Workspace membership deactivated
          </p>

          <p className="mt-1 text-sm text-slate-600">
            <span className="font-medium text-slate-800">
              {event.target_user_id}
            </span>
          </p>

          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            {formatValue(event.previous_status)}
            <ArrowRight size={14} />
            <span className="font-medium text-red-600">
              {formatValue(event.new_status)}
            </span>
          </p>
        </>
      );
  }
}

function EventIcon({ event }: { event: TenantAuditEvent }) {
  if (event.event_type === "SUBMISSION_STATUS_CHANGED") {
    return <FileText size={18} />;
  }

  if (event.event_type === "MEMBERSHIP_ROLE_CHANGED") {
    return <ShieldCheck size={18} />;
  }

  return <UserRound size={18} />;
}

function AuditEventCard({
  event,
  onOpenSubmission,
}: {
  event: TenantAuditEvent;
  onOpenSubmission: (submissionId: string) => void;
}) {
  const isSubmissionEvent = event.event_type === "SUBMISSION_STATUS_CHANGED";

  return (
    <article className="border-b border-slate-100 px-5 py-5 last:border-0">
      <div className="flex flex-col justify-between gap-3 sm:flex-row">
        <div className="flex min-w-0 gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            <EventIcon event={event} />
          </div>

          <div className="min-w-0 flex-1">
            <EventDescription event={event} />

            <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
              <p>
                Actor:{" "}
                <span className="break-all font-medium text-slate-700">
                  {event.actor_id}
                </span>
              </p>

              <p>
                Role:{" "}
                <span className="font-medium text-slate-700">
                  {formatValue(event.actor_role)}
                </span>
              </p>

              <p className="break-all">Event ID: {event.event_id}</p>

              <p className="break-all">Request ID: {event.request_id}</p>
            </div>

            {isSubmissionEvent && (
              <button
                type="button"
                onClick={() => onOpenSubmission(event.submission_id)}
                className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-800"
              >
                Open submission
                <ArrowRight size={13} />
              </button>
            )}
          </div>
        </div>

        <span className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
          <Clock size={13} />
          {formatDate(event.timestamp)}
        </span>
      </div>
    </article>
  );
}

export default function TenantAuditPanel({
  tenantId,
  userId,
  role,
}: TenantAuditPanelProps) {
  const navigate = useNavigate();

  const isAdmin = role === "TENANT_ADMIN";

  const auditQuery = useInfiniteQuery({
    queryKey: ["tenant-audit-events", userId, tenantId, PAGE_SIZE],
    enabled: Boolean(isAdmin && userId && tenantId),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      auditService.listTenantEvents(tenantId, {
        limit: PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: 15_000,
    retry: 1,
  });

  if (!isAdmin) {
    return (
      <section className="rounded-xl border border-amber-200 bg-white p-8 shadow-sm">
        <ShieldCheck className="mx-auto text-amber-500" size={32} />

        <h2 className="mt-3 text-center font-semibold text-slate-900">
          Administrator access required
        </h2>

        <p className="mt-2 text-center text-sm text-slate-500">
          Workspace-wide audit activity is available only to tenant
          administrators.
        </p>
      </section>
    );
  }

  const events = auditQuery.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <History className="text-blue-600" size={20} />
            <h2 className="font-semibold text-slate-900">
              Workspace audit activity
            </h2>
          </div>

          <p className="mt-1 text-xs text-slate-500">
            Submission workflow and membership-management events.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void auditQuery.refetch()}
          disabled={auditQuery.isFetching}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw
            size={15}
            className={auditQuery.isFetching ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </div>

      {auditQuery.isPending ? (
        <div className="px-5 py-16 text-center">
          <RefreshCw className="mx-auto animate-spin text-blue-500" size={28} />
          <p className="mt-3 text-sm text-slate-500">
            Loading audit activity...
          </p>
        </div>
      ) : auditQuery.isError ? (
        <div className="px-5 py-14 text-center">
          <AlertCircle className="mx-auto text-red-500" size={30} />

          <h3 className="mt-3 font-semibold text-slate-800">
            Unable to load audit activity
          </h3>

          <p className="mt-2 text-sm text-slate-500">
            {getErrorMessage(auditQuery.error)}
          </p>

          <button
            type="button"
            onClick={() => void auditQuery.refetch()}
            className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Try again
          </button>
        </div>
      ) : events.length === 0 ? (
        <div className="px-5 py-16 text-center">
          <Users className="mx-auto text-slate-300" size={34} />

          <p className="mt-3 font-medium text-slate-800">
            No audit events found
          </p>

          <p className="mt-1 text-sm text-slate-500">
            Workspace activity will appear here when auditable actions occur.
          </p>
        </div>
      ) : (
        <>
          <div>
            {events.map((event) => (
              <AuditEventCard
                key={event.event_id}
                event={event}
                onOpenSubmission={(submissionId) =>
                  navigate(`/submissions/${encodeURIComponent(submissionId)}`)
                }
              />
            ))}
          </div>

          <div className="border-t border-slate-100 px-5 py-4 text-center">
            {auditQuery.hasNextPage ? (
              <button
                type="button"
                onClick={() => void auditQuery.fetchNextPage()}
                disabled={auditQuery.isFetchingNextPage}
                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {auditQuery.isFetchingNextPage
                  ? "Loading..."
                  : "Load more activity"}
              </button>
            ) : (
              <p className="text-xs text-slate-400">
                All available events have been loaded.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
