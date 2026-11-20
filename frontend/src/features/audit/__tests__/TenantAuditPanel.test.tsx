import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { auditService } from "../../../lib/apiServices";
import TenantAuditPanel from "../TenantAuditPanel";

import type { TenantAuditEvent, TenantRole } from "../../../types/api";

const { mockNavigate } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
}));

vi.mock("../../../lib/apiServices", () => ({
  auditService: {
    listTenantEvents: vi.fn(),
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

const mockAuditService = vi.mocked(auditService);

const TENANT_ID = "tenant-123";
const USER_ID = "admin-123";

const submissionEvent: TenantAuditEvent = {
  event_id: "event-submission-001",
  tenant_id: TENANT_ID,
  actor_id: "reviewer-123",
  actor_role: "REVIEWER",
  timestamp: "2026-11-18T10:30:00Z",
  request_id: "request-submission-001",
  event_type: "SUBMISSION_STATUS_CHANGED",
  submission_id: "submission-123",
  previous_status: "SUBMITTED",
  new_status: "IN_REVIEW",
  previous_version: 1,
  new_version: 2,
  reason: "Documents verified",
};

const roleChangeEvent: TenantAuditEvent = {
  event_id: "event-role-001",
  tenant_id: TENANT_ID,
  actor_id: USER_ID,
  actor_role: "TENANT_ADMIN",
  timestamp: "2026-11-18T11:00:00Z",
  request_id: "request-role-001",
  event_type: "MEMBERSHIP_ROLE_CHANGED",
  target_user_id: "submitter-123",
  previous_role: "SUBMITTER",
  new_role: "REVIEWER",
};

const deactivationEvent: TenantAuditEvent = {
  event_id: "event-deactivation-001",
  tenant_id: TENANT_ID,
  actor_id: USER_ID,
  actor_role: "TENANT_ADMIN",
  timestamp: "2026-11-18T11:30:00Z",
  request_id: "request-deactivation-001",
  event_type: "MEMBERSHIP_DEACTIVATED",
  target_user_id: "inactive-123",
  previous_status: "ACTIVE",
  new_status: "INACTIVE",
};

const events: TenantAuditEvent[] = [
  submissionEvent,
  roleChangeEvent,
  deactivationEvent,
];

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryDelay: 0,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

function renderPanel(role: TenantRole | "Unknown" = "TENANT_ADMIN") {
  const queryClient = createQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <TenantAuditPanel tenantId={TENANT_ID} userId={USER_ID} role={role} />
    </QueryClientProvider>,
  );
}

function createAxiosError(status: number) {
  return Object.assign(new Error("Request failed"), {
    isAxiosError: true,
    response: {
      status,
    },
  });
}

beforeEach(() => {
  vi.resetAllMocks();

  mockAuditService.listTenantEvents.mockResolvedValue({
    items: events,
    next_cursor: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TenantAuditPanel", () => {
  it.each(["SUBMITTER", "REVIEWER", "Unknown"] as const)(
    "denies workspace-wide audit access to %s users",
    async (role) => {
      renderPanel(role);

      expect(
        screen.getByText("Administrator access required"),
      ).toBeInTheDocument();

      expect(
        screen.getByText(
          "Workspace-wide audit activity is available only to tenant administrators.",
        ),
      ).toBeInTheDocument();

      expect(mockAuditService.listTenantEvents).not.toHaveBeenCalled();
    },
  );

  it("loads workspace audit activity for a tenant administrator", async () => {
    renderPanel();

    expect(
      await screen.findByText("Workspace audit activity"),
    ).toBeInTheDocument();

    expect(mockAuditService.listTenantEvents).toHaveBeenCalledWith(TENANT_ID, {
      limit: 20,
    });
  });

  it("renders submission status change events", async () => {
    renderPanel();

    expect(
      await screen.findByText("Submission status changed"),
    ).toBeInTheDocument();

    expect(screen.getByText("SUBMITTED")).toBeInTheDocument();
    expect(screen.getByText("IN REVIEW")).toBeInTheDocument();

    expect(screen.getByText("Version 1 → 2")).toBeInTheDocument();

    expect(screen.getByText("Documents verified")).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Open submission",
      }),
    ).toBeInTheDocument();
  });

  it("renders membership role change events", async () => {
    renderPanel();

    expect(await screen.findByText("Member role changed")).toBeInTheDocument();

    expect(screen.getByText("submitter-123")).toBeInTheDocument();
    expect(screen.getByText("SUBMITTER")).toBeInTheDocument();

    expect(screen.getAllByText("REVIEWER")).toHaveLength(2);
  });

  it("renders membership deactivation events", async () => {
    renderPanel();

    expect(
      await screen.findByText("Workspace membership deactivated"),
    ).toBeInTheDocument();

    expect(screen.getByText("inactive-123")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("INACTIVE")).toBeInTheDocument();
  });

  it("renders actor, role, event ID and request ID metadata", async () => {
    renderPanel();

    const eventHeading = await screen.findByText("Submission status changed");

    const article = eventHeading.closest("article");

    expect(article).not.toBeNull();

    expect(within(article!).getByText("reviewer-123")).toBeInTheDocument();

    expect(within(article!).getByText("Role:")).toBeInTheDocument();

    expect(
      within(article!).getByText("Event ID: event-submission-001"),
    ).toBeInTheDocument();

    expect(
      within(article!).getByText("Request ID: request-submission-001"),
    ).toBeInTheDocument();
  });

  it("does not render the reason section when a submission event has no reason", async () => {
    mockAuditService.listTenantEvents.mockResolvedValueOnce({
      items: [
        {
          ...submissionEvent,
          reason: null,
        },
      ],
      next_cursor: null,
    });

    renderPanel();

    expect(
      await screen.findByText("Submission status changed"),
    ).toBeInTheDocument();

    expect(screen.queryByText("Reason / feedback")).not.toBeInTheDocument();
  });

  it("navigates to the submission when Open submission is clicked", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("Submission status changed");

    await user.click(
      screen.getByRole("button", {
        name: "Open submission",
      }),
    );

    expect(mockNavigate).toHaveBeenCalledWith("/submissions/submission-123");
  });

  it("URL-encodes the submission ID before navigation", async () => {
    const user = userEvent.setup();

    mockAuditService.listTenantEvents.mockResolvedValueOnce({
      items: [
        {
          ...submissionEvent,
          submission_id: "submission/with spaces",
        },
      ],
      next_cursor: null,
    });

    renderPanel();

    await screen.findByText("Submission status changed");

    await user.click(
      screen.getByRole("button", {
        name: "Open submission",
      }),
    );

    expect(mockNavigate).toHaveBeenCalledWith(
      "/submissions/submission%2Fwith%20spaces",
    );
  });

  it("does not show submission navigation for membership events", async () => {
    mockAuditService.listTenantEvents.mockResolvedValueOnce({
      items: [roleChangeEvent, deactivationEvent],
      next_cursor: null,
    });

    renderPanel();

    await screen.findByText("Member role changed");

    expect(
      screen.queryByRole("button", {
        name: "Open submission",
      }),
    ).not.toBeInTheDocument();
  });

  it("loads the next page of audit events", async () => {
    const user = userEvent.setup();

    mockAuditService.listTenantEvents
      .mockResolvedValueOnce({
        items: [submissionEvent],
        next_cursor: "cursor-page-2",
      })
      .mockResolvedValueOnce({
        items: [roleChangeEvent],
        next_cursor: null,
      });

    renderPanel();

    expect(
      await screen.findByText("Submission status changed"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "Load more activity",
      }),
    );

    expect(await screen.findByText("Member role changed")).toBeInTheDocument();

    expect(mockAuditService.listTenantEvents).toHaveBeenNthCalledWith(
      2,
      TENANT_ID,
      {
        limit: 20,
        cursor: "cursor-page-2",
      },
    );

    expect(screen.getByText("Submission status changed")).toBeInTheDocument();
  });

  it("shows the empty state when there are no audit events", async () => {
    mockAuditService.listTenantEvents.mockResolvedValueOnce({
      items: [],
      next_cursor: null,
    });

    renderPanel();

    expect(
      await screen.findByText("No audit events found"),
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        "Workspace activity will appear here when auditable actions occur.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the loading state while audit events are being retrieved", () => {
    mockAuditService.listTenantEvents.mockReturnValueOnce(
      new Promise(() => {}),
    );

    renderPanel();

    expect(screen.getByText("Loading audit activity...")).toBeInTheDocument();
  });

  it("shows a generic error when audit events cannot be retrieved", async () => {
    mockAuditService.listTenantEvents
      .mockRejectedValueOnce(new Error("Service unavailable"))
      .mockRejectedValueOnce(new Error("Service unavailable"));

    renderPanel();

    expect(
      await screen.findByText("Unable to load audit activity"),
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        "Unable to retrieve audit activity. Check your connection and try again.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a specific error for unauthorized audit requests", async () => {
    mockAuditService.listTenantEvents
      .mockRejectedValueOnce(createAxiosError(403))
      .mockRejectedValueOnce(createAxiosError(403));

    renderPanel();

    expect(
      await screen.findByText(
        "Your account is not authorized to view workspace-wide audit activity.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a specific error when the audit endpoint is unavailable", async () => {
    mockAuditService.listTenantEvents
      .mockRejectedValueOnce(createAxiosError(404))
      .mockRejectedValueOnce(createAxiosError(404));

    renderPanel();

    expect(
      await screen.findByText(
        "The audit endpoint could not be found. Verify the backend deployment.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a specific error for server failures", async () => {
    mockAuditService.listTenantEvents
      .mockRejectedValueOnce(createAxiosError(500))
      .mockRejectedValueOnce(createAxiosError(500));

    renderPanel();

    expect(
      await screen.findByText(
        "The audit service encountered an internal error. Please try again.",
      ),
    ).toBeInTheDocument();
  });

  it("allows retrying after an audit request fails", async () => {
    const user = userEvent.setup();

    mockAuditService.listTenantEvents
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValueOnce({
        items: events,
        next_cursor: null,
      });

    renderPanel();

    expect(
      await screen.findByText("Unable to load audit activity"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "Try again",
      }),
    );

    expect(
      await screen.findByText("Submission status changed"),
    ).toBeInTheDocument();

    expect(mockAuditService.listTenantEvents).toHaveBeenCalledTimes(3);
  });

  it("allows manually refreshing audit activity", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("Submission status changed");

    await user.click(
      screen.getByRole("button", {
        name: "Refresh",
      }),
    );

    await waitFor(() => {
      expect(mockAuditService.listTenantEvents).toHaveBeenCalledTimes(2);
    });

    expect(mockAuditService.listTenantEvents).toHaveBeenLastCalledWith(
      TENANT_ID,
      {
        limit: 20,
      },
    );
  });
});
