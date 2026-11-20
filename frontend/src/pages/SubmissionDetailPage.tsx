import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  ArrowLeft,
  ArrowRight,
  Clock,
  FileText,
  History,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  auditService,
  submissionService,
  workflowService,
} from "../lib/apiServices";

import { useAuth } from "../features/auth/useAuth";
import { useTenant } from "../features/tenants/useTenant";

import type { AuditEvent, SubmissionStatus, TenantRole } from "../types/api";

const PAGE_SIZE = 20;

interface WorkflowAction {
  target: SubmissionStatus;
  label: string;
  description: string;
}

function getAvailableActions(
  role: TenantRole | undefined,
  status: SubmissionStatus,
): WorkflowAction[] {
  if (role === "SUBMITTER") {
    if (status === "DRAFT") {
      return [
        {
          target: "SUBMITTED",
          label: "Submit submission",
          description: "Send this submission for review.",
        },
      ];
    }

    if (status === "NEEDS_CHANGES") {
      return [
        {
          target: "DRAFT",
          label: "Return to draft",
          description: "Make the requested changes before resubmitting.",
        },
      ];
    }
  }

  if (role === "REVIEWER") {
    if (status === "SUBMITTED") {
      return [
        {
          target: "IN_REVIEW",
          label: "Start review",
          description: "Move this submission into review.",
        },
      ];
    }

    if (status === "IN_REVIEW") {
      return [
        {
          target: "APPROVED",
          label: "Approve",
          description: "Approve this submission.",
        },
        {
          target: "REJECTED",
          label: "Reject",
          description: "Reject this submission with a reason.",
        },
        {
          target: "NEEDS_CHANGES",
          label: "Request changes",
          description: "Return this submission to its owner with feedback.",
        },
      ];
    }

    if (status === "APPROVED") {
      return [
        {
          target: "CLOSED",
          label: "Close submission",
          description: "Close this approved submission.",
        },
      ];
    }
  }

  return [];
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (error.response?.status === 409) {
      return "The submission changed or this transition is no longer valid. Its latest state has been refreshed.";
    }
  }

  return error instanceof Error
    ? error.message
    : "An unexpected error occurred.";
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

function formatStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function StatusBadge({ status }: { status: SubmissionStatus }) {
  const styles: Record<SubmissionStatus, string> = {
    DRAFT: "bg-slate-100 text-slate-700",
    SUBMITTED: "bg-blue-50 text-blue-700",
    IN_REVIEW: "bg-amber-50 text-amber-700",
    APPROVED: "bg-emerald-50 text-emerald-700",
    REJECTED: "bg-red-50 text-red-700",
    NEEDS_CHANGES: "bg-orange-50 text-orange-700",
    CLOSED: "bg-slate-200 text-slate-700",
  };

  return (
    <span
      className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${styles[status]}`}
    >
      {formatStatus(status)}
    </span>
  );
}

function AuditEventCard({ event }: { event: AuditEvent }) {
  return (
    <div className="border-b border-slate-100 px-5 py-5 last:border-0">
      <div className="flex flex-col justify-between gap-3 sm:flex-row">
        <div>
          <p className="text-sm font-semibold text-slate-800">
            {formatStatus(event.previous_status)} →{" "}
            {formatStatus(event.new_status)}
          </p>

          <p className="mt-1 text-xs text-slate-500">
            {event.event_type.replaceAll("_", " ")}
          </p>
        </div>

        <span className="flex items-center gap-1 text-xs text-slate-500">
          <Clock size={13} />
          {formatDate(event.timestamp)}
        </span>
      </div>

      <div className="mt-3 grid gap-2 text-xs text-slate-500 sm:grid-cols-2">
        <p>
          Actor:{" "}
          <span className="font-medium text-slate-700">{event.actor_id}</span>
        </p>

        <p>
          Role:{" "}
          <span className="font-medium text-slate-700">{event.actor_role}</span>
        </p>

        <p>
          Version: {event.previous_version} → {event.new_version}
        </p>

        <p>
          Request ID: <span className="break-all">{event.request_id}</span>
        </p>
      </div>

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
    </div>
  );
}

export default function SubmissionDetailPage() {
  const { submissionId } = useParams<{ submissionId: string }>();
  const { activeTenant, tenantContext } = useTenant();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [selectedTarget, setSelectedTarget] = useState<SubmissionStatus | null>(
    null,
  );

  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const tenantId = activeTenant?.tenant_id;
  const userId = user?.userId;
  const role = tenantContext?.role ?? activeTenant?.role;

  const enabled = Boolean(tenantId && submissionId && userId);

  const submissionQuery = useQuery({
    queryKey: ["submission", userId, tenantId, submissionId],
    queryFn: () => submissionService.get(tenantId!, submissionId!),
    enabled,
  });

  const auditQuery = useInfiniteQuery({
    queryKey: ["audit-events", userId, tenantId, submissionId, PAGE_SIZE],
    enabled,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      auditService.listSubmissionEvents(tenantId!, submissionId!, {
        limit: PAGE_SIZE,
        ...(pageParam ? { cursor: pageParam } : {}),
      }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const auditEvents =
    auditQuery.data?.pages.flatMap((page) => page.items) ?? [];

  const transitionMutation = useMutation({
    mutationFn: async ({
      target,
      transitionReason,
    }: {
      target: SubmissionStatus;
      transitionReason?: string;
    }) => {
      const submission = submissionQuery.data;

      if (!submission) {
        throw new Error(
          "Submission details are unavailable. Refresh and retry.",
        );
      }

      return workflowService.transition(tenantId!, submissionId!, {
        target_status: target,
        expected_version: submission.version,
        ...(transitionReason ? { reason: transitionReason } : {}),
      });
    },

    onSuccess: async () => {
      setSelectedTarget(null);
      setReason("");
      setActionError(null);

      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["submission", userId, tenantId, submissionId],
        }),

        queryClient.invalidateQueries({
          queryKey: ["submissions", userId, tenantId],
        }),

        queryClient.invalidateQueries({
          queryKey: ["audit-events", userId, tenantId, submissionId],
        }),
      ]);
    },

    onError: async (error) => {
      setActionError(getErrorMessage(error));

      if (isAxiosError(error) && error.response?.status === 409) {
        await Promise.all([
          queryClient.invalidateQueries({
            queryKey: ["submission", userId, tenantId, submissionId],
          }),

          queryClient.invalidateQueries({
            queryKey: ["audit-events", userId, tenantId, submissionId],
          }),
        ]);
      }
    },
  });

  const submission = submissionQuery.data;

  const availableActions = submission
    ? getAvailableActions(role, submission.status)
    : [];

  function handleTransition() {
    if (!selectedTarget) {
      return;
    }

    const requiresReason =
      selectedTarget === "REJECTED" || selectedTarget === "NEEDS_CHANGES";

    if (requiresReason && !reason.trim()) {
      setActionError("A reason is required for this transition.");
      return;
    }

    setActionError(null);

    transitionMutation.mutate({
      target: selectedTarget,
      ...(reason.trim() ? { transitionReason: reason.trim() } : {}),
    });
  }

  if (!submissionId || !tenantId) {
    return (
      <div className="rounded-xl border border-red-200 bg-white p-8 text-center">
        <p className="text-sm text-red-700">
          No active workspace or submission was selected.
        </p>

        <button
          onClick={() => navigate("/")}
          className="mt-4 text-sm font-medium text-blue-600"
        >
          Return to dashboard
        </button>
      </div>
    );
  }

  if (submissionQuery.isLoading) {
    return (
      <div className="flex justify-center py-20">
        <LoaderCircle className="animate-spin text-blue-600" size={30} />
      </div>
    );
  }

  if (submissionQuery.isError || !submission) {
    return (
      <div className="rounded-xl border border-red-200 bg-white p-8 text-center">
        <p className="text-sm text-red-700">
          {getErrorMessage(submissionQuery.error)}
        </p>

        <button
          onClick={() => void submissionQuery.refetch()}
          className="mt-4 text-sm font-medium text-blue-600"
        >
          Retry
        </button>
      </div>
    );
  }

  const requiresReason =
    selectedTarget === "REJECTED" || selectedTarget === "NEEDS_CHANGES";

  return (
    <div className="space-y-6">
      <div>
        <button
          onClick={() => navigate("/")}
          className="mb-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"
        >
          <ArrowLeft size={16} />
          Back to dashboard
        </button>

        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <div className="flex items-center gap-2">
              <FileText size={22} className="text-blue-600" />

              <h1 className="text-2xl font-semibold text-slate-900">
                {submission.title || "Untitled submission"}
              </h1>
            </div>

            <p className="mt-2 break-all text-xs text-slate-400">
              {submission.submission_id}
            </p>
          </div>

          <StatusBadge status={submission.status} />
        </div>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 className="font-semibold text-slate-900">Submission overview</h2>

          <button
            onClick={() => void submissionQuery.refetch()}
            disabled={submissionQuery.isFetching}
            aria-label="Refresh submission"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            <RefreshCw
              size={17}
              className={submissionQuery.isFetching ? "animate-spin" : ""}
            />
          </button>
        </div>

        <div className="grid gap-5 p-5 sm:grid-cols-2">
          <div>
            <p className="text-xs text-slate-500">Created</p>
            <p className="mt-1 text-sm font-medium text-slate-800">
              {formatDate(submission.created_at)}
            </p>
          </div>

          <div>
            <p className="text-xs text-slate-500">Last updated</p>
            <p className="mt-1 text-sm font-medium text-slate-800">
              {formatDate(submission.updated_at)}
            </p>
          </div>

          <div>
            <p className="text-xs text-slate-500">Current version</p>
            <p className="mt-1 text-sm font-medium text-slate-800">
              {submission.version}
            </p>
          </div>

          <div>
            <p className="text-xs text-slate-500">Workspace</p>
            <p className="mt-1 break-all text-sm font-medium text-slate-800">
              {submission.tenant_id}
            </p>
          </div>
        </div>

        <div className="border-t border-slate-100 px-5 py-4">
          <p className="text-xs font-medium text-slate-500">Description</p>

          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">
            {submission.description || "No description provided."}
          </p>
        </div>

        <div className="border-t border-slate-100 px-5 py-4">
          <button
            onClick={() =>
              navigate(
                `/submissions/${encodeURIComponent(submissionId)}/documents`,
              )
            }
            className="inline-flex items-center gap-2 text-sm font-medium text-blue-600 hover:text-blue-800"
          >
            <FileText size={16} />
            Manage documents
            <ArrowRight size={15} />
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-4">
          <ShieldCheck size={19} className="text-blue-600" />

          <h2 className="font-semibold text-slate-900">Workflow actions</h2>
        </div>

        <div className="space-y-4 p-5">
          {availableActions.length === 0 ? (
            <p className="text-sm text-slate-500">
              No workflow actions are currently available for your role and this
              submission status.
            </p>
          ) : (
            <>
              <p className="text-sm text-slate-500">
                Select an action to change the submission workflow state.
              </p>

              <div className="grid gap-3 sm:grid-cols-2">
                {availableActions.map((action) => (
                  <button
                    key={action.target}
                    type="button"
                    onClick={() => {
                      setSelectedTarget(action.target);
                      setReason("");
                      setActionError(null);
                    }}
                    disabled={transitionMutation.isPending}
                    className={`rounded-lg border p-4 text-left transition disabled:opacity-50 ${
                      selectedTarget === action.target
                        ? "border-blue-500 bg-blue-50"
                        : "border-slate-200 hover:border-blue-300 hover:bg-slate-50"
                    }`}
                  >
                    <p className="text-sm font-semibold text-slate-800">
                      {action.label}
                    </p>

                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {action.description}
                    </p>
                  </button>
                ))}
              </div>

              {selectedTarget && (
                <div className="space-y-3 rounded-lg bg-slate-50 p-4">
                  <p className="text-sm font-semibold text-slate-800">
                    Confirm: {formatStatus(selectedTarget)}
                  </p>

                  {requiresReason && (
                    <div>
                      <label
                        htmlFor="transition-reason"
                        className="mb-2 block text-sm font-medium text-slate-700"
                      >
                        Reason (required)
                      </label>

                      <textarea
                        id="transition-reason"
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        maxLength={2000}
                        rows={4}
                        placeholder="Explain the reason for this decision..."
                        className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      />

                      <p className="mt-1 text-right text-xs text-slate-400">
                        {reason.length}/2000
                      </p>
                    </div>
                  )}

                  {actionError && (
                    <p role="alert" className="text-sm text-red-700">
                      {actionError}
                    </p>
                  )}

                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={handleTransition}
                      disabled={
                        transitionMutation.isPending ||
                        (requiresReason && !reason.trim())
                      }
                      className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {transitionMutation.isPending
                        ? "Processing..."
                        : "Confirm transition"}
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setSelectedTarget(null);
                        setReason("");
                        setActionError(null);
                      }}
                      disabled={transitionMutation.isPending}
                      className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-white"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {transitionMutation.isError && !actionError && (
            <p role="alert" className="text-sm text-red-700">
              {getErrorMessage(transitionMutation.error)}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2">
            <History size={19} className="text-blue-600" />

            <h2 className="font-semibold text-slate-900">Audit history</h2>
          </div>

          <button
            onClick={() => void auditQuery.refetch()}
            disabled={auditQuery.isFetching}
            aria-label="Refresh audit history"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            <RefreshCw
              size={17}
              className={auditQuery.isFetching ? "animate-spin" : ""}
            />
          </button>
        </div>

        {auditQuery.isLoading ? (
          <div className="flex justify-center p-10">
            <LoaderCircle className="animate-spin text-blue-600" size={25} />
          </div>
        ) : auditQuery.isError ? (
          <div className="p-6 text-center">
            <p className="text-sm text-red-700">
              {getErrorMessage(auditQuery.error)}
            </p>

            <button
              onClick={() => void auditQuery.refetch()}
              className="mt-3 text-sm font-medium text-blue-600"
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            {auditEvents.length === 0 ? (
              <div className="p-10 text-center">
                <History className="mx-auto text-slate-300" size={30} />

                <p className="mt-3 text-sm text-slate-500">
                  No audit events are available yet.
                </p>
              </div>
            ) : (
              <div>
                {auditEvents.map((event) => (
                  <AuditEventCard key={event.event_id} event={event} />
                ))}
              </div>
            )}

            {auditQuery.hasNextPage && (
              <div className="flex justify-center border-t border-slate-100 px-5 py-4">
                <button
                  type="button"
                  onClick={() => void auditQuery.fetchNextPage()}
                  disabled={auditQuery.isFetchingNextPage}
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {auditQuery.isFetchingNextPage
                    ? "Loading..."
                    : "Load more audit events"}
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
