import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "../../features/auth/useAuth";
import { useTenant } from "../../features/tenants/useTenant";
import {
  auditService,
  submissionService,
  workflowService,
} from "../../lib/apiServices";
import SubmissionDetailPage from "../SubmissionDetailPage";
import type { SubmissionStatus } from "../../types/api";

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../features/tenants/useTenant", () => ({
  useTenant: vi.fn(),
}));

vi.mock("../../lib/apiServices", () => ({
  auditService: {
    listSubmissionEvents: vi.fn(),
  },
  submissionService: {
    get: vi.fn(),
  },
  workflowService: {
    transition: vi.fn(),
  },
}));

const mockUseAuth = vi.mocked(useAuth);
const mockUseTenant = vi.mocked(useTenant);
const mockSubmissionService = vi.mocked(submissionService);
const mockAuditService = vi.mocked(auditService);
const mockWorkflowService = vi.mocked(workflowService);

const TENANT_ID = "tenant-123";
const USER_ID = "user-123";
const SUBMISSION_ID = "submission-123";

type TestRole = "SUBMITTER" | "REVIEWER" | "TENANT_ADMIN";

const submission = {
  tenant_id: TENANT_ID,
  submission_id: SUBMISSION_ID,
  title: "Security assessment",
  description: "Review the uploaded security evidence.",
  status: "DRAFT" as SubmissionStatus,
  created_at: "2026-11-18T10:00:00Z",
  updated_at: "2026-11-18T11:00:00Z",
  version: 4,
  pending_document_count: 0,
  uploaded_document_count: 2,
};

const auditEvent = {
  event_id: "event-123",
  tenant_id: TENANT_ID,
  submission_id: SUBMISSION_ID,
  event_type: "SUBMISSION_STATUS_CHANGED" as const,
  actor_id: USER_ID,
  actor_role: "REVIEWER",
  previous_status: "SUBMITTED",
  new_status: "IN_REVIEW",
  previous_version: 1,
  new_version: 2,
  timestamp: "2026-11-18T12:00:00Z",
  request_id: "request-123",
  reason: "Beginning review.",
};

function setUserAndTenant(role: TestRole) {
  mockUseAuth.mockReturnValue({
    user: { userId: USER_ID },
  } as ReturnType<typeof useAuth>);

  mockUseTenant.mockReturnValue({
    activeTenant: {
      tenant_id: TENANT_ID,
      role,
    },
    tenantContext: {
      tenant_id: TENANT_ID,
      user_id: USER_ID,
      role,
    },
  } as ReturnType<typeof useTenant>);
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

function getWorkflowSection() {
  return screen
    .getByRole("heading", { name: "Workflow actions" })
    .closest("section") as HTMLElement;
}

function getActionButtons() {
  return within(getWorkflowSection()).getAllByRole("button");
}

function renderPage(
  options: {
    role?: TestRole;
    status?: SubmissionStatus;
    events?: (typeof auditEvent)[];
    nextCursor?: string | null;
  } = {},
) {
  const queryClient = createQueryClient();
  const role = options.role ?? "SUBMITTER";
  const status = options.status ?? "DRAFT";

  setUserAndTenant(role);

  mockSubmissionService.get.mockResolvedValue({
    ...submission,
    status,
  });

  mockAuditService.listSubmissionEvents.mockResolvedValue({
    items: options.events ?? [],
    next_cursor: options.nextCursor ?? null,
  });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/submissions/${SUBMISSION_ID}`]}>
        <Routes>
          <Route
            path="/submissions/:submissionId"
            element={<SubmissionDetailPage />}
          />
          <Route path="/" element={<h1>Dashboard destination</h1>} />
          <Route
            path="/submissions/:submissionId/documents"
            element={<h1>Documents destination</h1>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  return {
    ...result,
    queryClient,
  };
}

describe("SubmissionDetailPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();

    mockSubmissionService.get.mockResolvedValue(submission);

    mockAuditService.listSubmissionEvents.mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    mockWorkflowService.transition.mockResolvedValue({
      tenant_id: TENANT_ID,
      submission_id: SUBMISSION_ID,
      previous_status: "DRAFT",
      status: "SUBMITTED",
      version: 5,
      updated_at: "2026-11-19T10:00:00Z",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads and displays submission details", async () => {
    renderPage();

    expect(await screen.findByText("Security assessment")).toBeInTheDocument();
    expect(
      screen.getByText("Review the uploaded security evidence."),
    ).toBeInTheDocument();

    expect(screen.getByText(SUBMISSION_ID)).toBeInTheDocument();
    expect(screen.getByText(TENANT_ID)).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("requests the submission using the active tenant and submission IDs", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(mockSubmissionService.get).toHaveBeenCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
    );
  });

  it("requests submission audit history using the correct IDs and page size", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    await waitFor(() => {
      expect(mockAuditService.listSubmissionEvents).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        { limit: 20 },
      );
    });
  });

  it("shows the submitter action for a draft", async () => {
    renderPage({
      role: "SUBMITTER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    expect(getActionButtons()).toHaveLength(1);
  });

  it("shows the submitter action for a submission needing changes", async () => {
    renderPage({
      role: "SUBMITTER",
      status: "NEEDS_CHANGES",
    });

    await screen.findByText("Security assessment");

    expect(getActionButtons()).toHaveLength(1);
  });

  it("does not show workflow actions to a submitter for submitted work", async () => {
    renderPage({
      role: "SUBMITTER",
      status: "SUBMITTED",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.getByText(/No workflow actions are currently available/),
    ).toBeInTheDocument();
  });

  it("shows the reviewer action for submitted work", async () => {
    renderPage({
      role: "REVIEWER",
      status: "SUBMITTED",
    });

    await screen.findByText("Security assessment");

    expect(getActionButtons()).toHaveLength(1);
  });

  it("shows three reviewer actions for work under review", async () => {
    renderPage({
      role: "REVIEWER",
      status: "IN_REVIEW",
    });

    await screen.findByText("Security assessment");

    expect(getActionButtons()).toHaveLength(3);
  });

  it("shows the reviewer action for approved work", async () => {
    renderPage({
      role: "REVIEWER",
      status: "APPROVED",
    });

    await screen.findByText("Security assessment");

    expect(getActionButtons()).toHaveLength(1);
  });

  it("does not show workflow actions to a reviewer for a draft", async () => {
    renderPage({
      role: "REVIEWER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.getByText(/No workflow actions are currently available/),
    ).toBeInTheDocument();
  });

  it("does not show workflow actions to a tenant administrator", async () => {
    renderPage({
      role: "TENANT_ADMIN",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.getByText(/No workflow actions are currently available/),
    ).toBeInTheDocument();
  });

  it("opens and cancels a workflow confirmation", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "SUBMITTER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[0]);

    expect(
      screen.getByRole("button", { name: "Confirm transition" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      screen.queryByRole("button", { name: "Confirm transition" }),
    ).not.toBeInTheDocument();

    expect(mockWorkflowService.transition).not.toHaveBeenCalled();
  });

  it("submits a draft transition with the current expected version", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "SUBMITTER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[0]);
    await user.click(
      screen.getByRole("button", { name: "Confirm transition" }),
    );

    await waitFor(() => {
      expect(mockWorkflowService.transition).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        {
          target_status: "SUBMITTED",
          expected_version: 4,
        },
      );
    });
  });

  it("refreshes submission and audit history after a stale-version conflict", async () => {
    const user = userEvent.setup();

    mockWorkflowService.transition.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: "Submission has changed. Refresh and retry.",
        },
      },
    });

    const { queryClient } = renderPage({
      role: "SUBMITTER",
      status: "DRAFT",
    });

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[0]);

    await user.click(
      screen.getByRole("button", { name: "Confirm transition" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Submission has changed. Refresh and retry."),
      ).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: ["submission", USER_ID, TENANT_ID, SUBMISSION_ID],
        }),
      );

      expect(invalidateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          queryKey: ["audit-events", USER_ID, TENANT_ID, SUBMISSION_ID],
        }),
      );
    });
  });

  it("requires a reason for a rejection", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "REVIEWER",
      status: "IN_REVIEW",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[1]);

    expect(screen.getByLabelText("Reason (required)")).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Confirm transition" }),
    ).toBeDisabled();

    expect(mockWorkflowService.transition).not.toHaveBeenCalled();
  });

  it("does not submit a whitespace-only reason", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "REVIEWER",
      status: "IN_REVIEW",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[1]);

    await user.type(screen.getByLabelText("Reason (required)"), "     ");

    expect(
      screen.getByRole("button", { name: "Confirm transition" }),
    ).toBeDisabled();

    expect(mockWorkflowService.transition).not.toHaveBeenCalled();
  });

  it("trims and submits the reason for a rejection", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "REVIEWER",
      status: "IN_REVIEW",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[1]);

    await user.type(
      screen.getByLabelText("Reason (required)"),
      "  Insufficient evidence  ",
    );

    await user.click(
      screen.getByRole("button", { name: "Confirm transition" }),
    );

    await waitFor(() => {
      expect(mockWorkflowService.transition).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        {
          target_status: "REJECTED",
          expected_version: 4,
          reason: "Insufficient evidence",
        },
      );
    });
  });

  it("requires a reason for requesting changes", async () => {
    const user = userEvent.setup();

    renderPage({
      role: "REVIEWER",
      status: "IN_REVIEW",
    });

    await screen.findByText("Security assessment");

    await user.click(getActionButtons()[2]);

    expect(screen.getByLabelText("Reason (required)")).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Confirm transition" }),
    ).toBeDisabled();
  });

  it("shows an audit event with its details", async () => {
    renderPage({
      events: [auditEvent],
    });

    expect(await screen.findByText("Beginning review.")).toBeInTheDocument();

    expect(screen.getByText(USER_ID)).toBeInTheDocument();
    expect(screen.getByText("request-123")).toBeInTheDocument();
  });

  it("shows the empty audit history state", async () => {
    renderPage();

    expect(
      await screen.findByText("No audit events are available yet."),
    ).toBeInTheDocument();
  });

  it("loads another audit history page", async () => {
    const user = userEvent.setup();

    mockAuditService.listSubmissionEvents
      .mockResolvedValueOnce({
        items: [auditEvent],
        next_cursor: "next-page",
      })
      .mockResolvedValueOnce({
        items: [
          {
            ...auditEvent,
            event_id: "event-456",
            reason: "Second audit event.",
          },
        ],
        next_cursor: null,
      });

    renderPage();

    expect(await screen.findByText("Beginning review.")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Load more audit events" }),
    );

    expect(await screen.findByText("Second audit event.")).toBeInTheDocument();

    expect(mockAuditService.listSubmissionEvents).toHaveBeenLastCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
      {
        limit: 20,
        cursor: "next-page",
      },
    );
  });

  it("navigates to the document management page", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: /Manage documents/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Documents destination",
      }),
    ).toBeInTheDocument();
  });

  it("navigates back to the dashboard", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: /Back to dashboard/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Dashboard destination",
      }),
    ).toBeInTheDocument();
  });

  it("shows a submission loading error and allows retry", async () => {
    const user = userEvent.setup();

    mockSubmissionService.get
      .mockRejectedValueOnce(new Error("Unable to load submission"))
      .mockResolvedValueOnce(submission);

    renderPage();

    expect(
      await screen.findByText("Unable to load submission"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Security assessment")).toBeInTheDocument();

    expect(mockSubmissionService.get).toHaveBeenCalledTimes(2);
  });

  it("shows an audit history error and allows retry", async () => {
    const user = userEvent.setup();

    mockAuditService.listSubmissionEvents
      .mockRejectedValueOnce(new Error("Audit service unavailable"))
      .mockResolvedValueOnce({
        items: [auditEvent],
        next_cursor: null,
      });

    renderPage();

    expect(
      await screen.findByText("Audit service unavailable"),
    ).toBeInTheDocument();

    const auditSection = screen
      .getByRole("heading", {
        name: "Audit history",
      })
      .closest("section") as HTMLElement;

    await user.click(
      within(auditSection).getByRole("button", { name: "Retry" }),
    );

    expect(await screen.findByText("Beginning review.")).toBeInTheDocument();
  });
});
