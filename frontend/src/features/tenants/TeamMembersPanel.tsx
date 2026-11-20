import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import {
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  UserRound,
  UserX,
  Users,
} from "lucide-react";

import { tenantService } from "../../lib/apiServices";
import type { MemberRole, TenantMember, TenantRole } from "../../types/api";

interface TeamMembersPanelProps {
  tenantId: string;
  currentUserId: string;
  role: TenantRole | "Unknown";
}

function formatDate(value: string | null): string {
  if (!value) return "Unknown";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
  }).format(date);
}

function getErrorMessage(error: unknown): string {
  if (isAxiosError<{ detail?: string }>(error)) {
    if (error.response?.status === 409) {
      return "This membership changed before your update was completed. The member list has been refreshed. Please review the current role and try again.";
    }

    const detail = error.response?.data?.detail;

    if (typeof detail === "string") {
      return detail;
    }

    if (error.response?.status === 403) {
      return "You are not authorized to manage members in this workspace.";
    }
  }

  return "An unexpected error occurred. Please try again.";
}

function MemberStatusBadge({ status }: { status: string }) {
  const active = status === "ACTIVE";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
        active
          ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-600/20"
          : "bg-slate-100 text-slate-600 ring-1 ring-slate-500/20"
      }`}
    >
      {active ? "Active" : "Inactive"}
    </span>
  );
}

export default function TeamMembersPanel({
  tenantId,
  currentUserId,
  role,
}: TeamMembersPanelProps) {
  const queryClient = useQueryClient();
  const [mutationError, setMutationError] = useState<string | null>(null);

  const isAdmin = role === "TENANT_ADMIN";

  const membersQueryKey = ["tenant-members", currentUserId, tenantId];

  const membersQuery = useQuery({
    queryKey: membersQueryKey,
    queryFn: () => tenantService.listMembers(tenantId),
    enabled: Boolean(isAdmin && currentUserId && tenantId),
    staleTime: 15_000,
    retry: 1,
  });

  const refreshMembers = async () => {
    await queryClient.invalidateQueries({
      queryKey: membersQueryKey,
    });
  };

  const roleMutation = useMutation({
    mutationFn: ({
      userId,
      expectedRole,
      newRole,
    }: {
      userId: string;
      expectedRole: MemberRole;
      newRole: MemberRole;
    }) =>
      tenantService.changeMemberRole(tenantId, userId, {
        expected_role: expectedRole,
        new_role: newRole,
      }),

    onSuccess: async () => {
      setMutationError(null);
      await refreshMembers();
    },

    onError: async (error) => {
      setMutationError(getErrorMessage(error));
      await refreshMembers();
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: ({
      userId,
      expectedRole,
    }: {
      userId: string;
      expectedRole: MemberRole;
    }) =>
      tenantService.deactivateMember(tenantId, userId, {
        expected_role: expectedRole,
      }),

    onSuccess: async () => {
      setMutationError(null);
      await refreshMembers();
    },

    onError: async (error) => {
      setMutationError(getErrorMessage(error));
      await refreshMembers();
    },
  });

  const isMutating = roleMutation.isPending || deactivateMutation.isPending;

  function handleRoleChange(member: TenantMember, newRole: MemberRole) {
    if (
      member.role === "TENANT_ADMIN" ||
      member.status !== "ACTIVE" ||
      member.role === newRole ||
      isMutating
    ) {
      return;
    }

    setMutationError(null);

    roleMutation.mutate({
      userId: member.user_id,
      expectedRole: member.role,
      newRole,
    });
  }

  function handleDeactivate(member: TenantMember) {
    if (
      member.role === "TENANT_ADMIN" ||
      member.status !== "ACTIVE" ||
      member.user_id === currentUserId ||
      isMutating
    ) {
      return;
    }

    const confirmed = window.confirm(
      `Deactivate this member?\n\n${member.user_id}\n\nThey will lose active membership in this workspace.`,
    );

    if (!confirmed) return;

    setMutationError(null);

    deactivateMutation.mutate({
      userId: member.user_id,
      expectedRole: member.role,
    });
  }

  if (!isAdmin) {
    return (
      <section className="rounded-xl border border-amber-200 bg-white p-8 shadow-sm">
        <ShieldCheck className="mx-auto text-amber-500" size={32} />

        <h2 className="mt-3 text-center font-semibold text-slate-900">
          Administrator access required
        </h2>

        <p className="mt-2 text-center text-sm text-slate-500">
          Only tenant administrators can view and manage workspace members.
        </p>
      </section>
    );
  }

  const members = membersQuery.data ?? [];

  const activeCount = members.filter(
    (member) => member.status === "ACTIVE",
  ).length;

  const inactiveCount = members.filter(
    (member) => member.status === "INACTIVE",
  ).length;

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col justify-between gap-4 border-b border-slate-100 px-5 py-5 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Users className="text-blue-600" size={20} />

            <h2 className="font-semibold text-slate-900">Workspace members</h2>
          </div>

          <p className="mt-1 text-xs text-slate-500">
            Manage membership roles and access status.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void membersQuery.refetch()}
          disabled={membersQuery.isFetching}
          aria-label="Refresh members"
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw
            size={15}
            className={membersQuery.isFetching ? "animate-spin" : ""}
          />
          Refresh
        </button>
      </div>

      <div className="grid gap-4 border-b border-slate-100 p-5 sm:grid-cols-2">
        <div className="rounded-lg bg-emerald-50 p-4">
          <p className="text-xs font-medium text-emerald-700">Active members</p>

          <p className="mt-1 text-2xl font-semibold text-emerald-800">
            {membersQuery.isPending ? "—" : activeCount}
          </p>
        </div>

        <div className="rounded-lg bg-slate-100 p-4">
          <p className="text-xs font-medium text-slate-600">Inactive members</p>

          <p className="mt-1 text-2xl font-semibold text-slate-800">
            {membersQuery.isPending ? "—" : inactiveCount}
          </p>
        </div>
      </div>

      {mutationError && (
        <div
          role="alert"
          className="mx-5 mt-5 flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4"
        >
          <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-600" />

          <p className="text-sm text-red-700">{mutationError}</p>
        </div>
      )}

      {membersQuery.isPending ? (
        <div className="px-5 py-16 text-center">
          <RefreshCw className="mx-auto animate-spin text-blue-500" size={28} />

          <p className="mt-3 text-sm text-slate-500">
            Loading workspace members...
          </p>
        </div>
      ) : membersQuery.isError ? (
        <div className="px-5 py-14 text-center">
          <AlertCircle className="mx-auto text-red-500" size={30} />

          <h3 className="mt-3 font-semibold text-slate-800">
            Unable to load members
          </h3>

          <p className="mt-2 text-sm text-slate-500">
            {getErrorMessage(membersQuery.error)}
          </p>

          <button
            type="button"
            onClick={() => void membersQuery.refetch()}
            className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Try again
          </button>
        </div>
      ) : members.length === 0 ? (
        <div className="px-5 py-14 text-center">
          <UserRound className="mx-auto text-slate-300" size={34} />

          <p className="mt-3 font-medium text-slate-800">No members found</p>

          <p className="mt-1 text-sm text-slate-500">
            No membership records were returned for this workspace.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-3">Member</th>
                <th className="px-5 py-3">Role</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Joined</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100">
              {members.map((member) => {
                const isSelf = member.user_id === currentUserId;
                const isTenantAdmin = member.role === "TENANT_ADMIN";
                const canManage =
                  !isTenantAdmin && member.status === "ACTIVE" && !isSelf;

                return (
                  <tr key={member.user_id}>
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-700">
                          {member.user_id.slice(0, 2).toUpperCase()}
                        </div>

                        <div className="min-w-0">
                          <p className="max-w-[260px] truncate text-sm font-medium text-slate-800">
                            {member.user_id}
                          </p>

                          {isSelf && (
                            <p className="mt-0.5 text-xs text-blue-600">You</p>
                          )}
                        </div>
                      </div>
                    </td>

                    <td className="px-5 py-4">
                      {isTenantAdmin ? (
                        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700">
                          <ShieldCheck size={15} />
                          Tenant Admin
                        </span>
                      ) : (
                        <select
                          aria-label={`Role for ${member.user_id}`}
                          value={member.role}
                          disabled={!canManage || isMutating}
                          onChange={(event) =>
                            handleRoleChange(
                              member,
                              event.target.value as MemberRole,
                            )
                          }
                          className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-700 outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
                        >
                          <option value="SUBMITTER">Submitter</option>
                          <option value="REVIEWER">Reviewer</option>
                        </select>
                      )}
                    </td>

                    <td className="px-5 py-4">
                      <MemberStatusBadge status={member.status} />
                    </td>

                    <td className="px-5 py-4 text-sm text-slate-500">
                      {formatDate(member.created_at)}
                    </td>

                    <td className="px-5 py-4 text-right">
                      {canManage ? (
                        <button
                          type="button"
                          onClick={() => handleDeactivate(member)}
                          disabled={isMutating}
                          aria-label={`Deactivate ${member.user_id}`}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          <UserX size={14} />
                          Deactivate
                        </button>
                      ) : isSelf ? (
                        <span className="text-xs text-slate-400">
                          Current account
                        </span>
                      ) : isTenantAdmin ? (
                        <span className="text-xs text-slate-400">
                          Protected account
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs text-slate-400">
                          <CheckCircle2 size={13} />
                          Inactive
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="border-t border-slate-100 px-5 py-3">
        <p className="text-xs leading-5 text-slate-400">
          Member management uses backend authorization and expected-role checks.
          Tenant administrator accounts and your current account cannot be
          modified through this interface.
        </p>
      </div>
    </section>
  );
}
