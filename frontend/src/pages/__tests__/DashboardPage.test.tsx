import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "../../features/auth/useAuth";
import { useTenant } from "../../features/tenants/useTenant";
import { submissionService } from "../../lib/apiServices";
import DashboardPage from "../DashboardPage";

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../features/tenants/useTenant", () => ({
  useTenant: vi.fn(),
}));

vi.mock("../../lib/apiServices", () => ({
  submissionService: {
    list: vi.fn(),
  },
}));

vi.mock("../../features/tenants/TeamMembersPanel", () => ({
  default: ({
    tenantId,
    currentUserId,
    role,
  }: {
    tenantId: string;
    currentUserId: string;
    role: string;
  }) => (
    <div data-testid="team-members-panel">
      Team panel: {tenantId} / {currentUserId} / {role}
    </div>
  ),
}));

vi.mock("../../features/audit/TenantAuditPanel", () => ({
  default: ({
    tenantId,
    userId,
    role,
  }: {
    tenantId: string;
    userId: string;
    role: string;
  }) => (
    <div data-testid="tenant-audit-panel">
      Audit panel: {tenantId} / {userId} / {role}
    </div>
  ),
}));

vi.mock("../../features/submissions/CreateSubmissionModal", () => ({
  default: ({
    tenantId,
    userId,
    onClose,
  }: {
    tenantId: string;
    userId: string;
    onClose: () => void;
  }) => (
    <div data-testid="create-submission-modal">
      <p>
        Create submission: {tenantId} / {userId}
      </p>
      <button onClick={onClose}>Close modal</button>
    </div>
  ),
}));

const mockUseAuth = vi.mocked(useAuth);
const mockUseTenant = vi.mocked(useTenant);
const mockSubmissionService = vi.mocked(submissionService);

const TENANT_ID = "tenant-123";
const SECOND_TENANT_ID = "tenant-456";
const USER_ID = "user-123";

type TestRole = "SUBMITTER" | "REVIEWER" | "TENANT_ADMIN";

const submissions = [
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-1",
    title: "Security assessment",
    status: "DRAFT" as const,
    created_at: "2026-11-18T10:00:00Z",
    updated_at: "2026-11-18T11:00:00Z",
    version: 1,
    pending_document_count: 2,
    uploaded_document_count: 3,
  },
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-2",
    title: "Infrastructure review",
    status: "SUBMITTED" as const,
    created_at: "2026-11-17T10:00:00Z",
    updated_at: "2026-11-18T12:00:00Z",
    version: 2,
    pending_document_count: 1,
    uploaded_document_count: 4,
  },
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-3",
    title: "Application security review",
    status: "IN_REVIEW" as const,
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-18T13:00:00Z",
    version: 3,
    pending_document_count: 0,
    uploaded_document_count: 2,
  },
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-4",
    title: "Cloud compliance review",
    status: "APPROVED" as const,
    created_at: "2026-11-15T10:00:00Z",
    updated_at: "2026-11-18T14:00:00Z",
    version: 4,
    pending_document_count: 0,
    uploaded_document_count: 5,
  },
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-5",
    title: "Access control assessment",
    status: "NEEDS_CHANGES" as const,
    created_at: "2026-11-14T10:00:00Z",
    updated_at: "2026-11-18T15:00:00Z",
    version: 5,
    pending_document_count: 3,
    uploaded_document_count: 1,
  },
  {
    tenant_id: TENANT_ID,
    submission_id: "submission-6",
    title: "Network security assessment",
    status: "REJECTED" as const,
    created_at: "2026-11-13T10:00:00Z",
    updated_at: "2026-11-18T16:00:00Z",
    version: 1,
    pending_document_count: 0,
    uploaded_document_count: 2,
  },
];

function setUserAndTenant(
  role: TestRole = "SUBMITTER",
  options: {
    activeTenant?: boolean;
    loading?: boolean;
    error?: string | null;
    tenants?: { tenant_id: string; role: TestRole }[];
    tenantContextRole?: TestRole | null;
  } = {},
) {
  const tenants = options.tenants ?? [
    { tenant_id: TENANT_ID, role },
    { tenant_id: SECOND_TENANT_ID, role },
  ];

  mockUseAuth.mockReturnValue({
    user: {
      userId: USER_ID,
      username: "harsh.maurya",
    },
    logout: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useAuth>);

  mockUseTenant.mockReturnValue({
    tenants,
    activeTenant: options.activeTenant === false ? null : (tenants[0] ?? null),
    tenantContext:
      options.tenantContextRole === null
        ? null
        : {
            tenant_id: tenants[0]?.tenant_id ?? TENANT_ID,
            user_id: USER_ID,
            role: options.tenantContextRole ?? role,
          },
    loading: options.loading ?? false,
    error: options.error ?? null,
    selectTenant: vi.fn(),
    refreshTenants: vi.fn().mockResolvedValue(undefined),
  } as unknown as ReturnType<typeof useTenant>);
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

function LocationDisplay() {
  const location = useLocation();

  return <p data-testid="current-location">{location.pathname}</p>;
}

function renderPage() {

    const queryClient = createQueryClient();

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/submissions/:submissionId" element={<h1>Submission destination</h1>} />
          <Route path="/login" element={<h1>Login destination</h1>} />
        </Routes>
        <LocationDisplay />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  return {
    ...result,
    queryClient,
  };
}

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();

    setUserAndTenant();

    mockSubmissionService.list.mockResolvedValue({
      items: submissions,
      next_cursor: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the dashboard for the authenticated user", async () => {
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Welcome back, harsh.maurya",
      }),
    ).toBeInTheDocument();

    expect(screen.getByText(TENANT_ID)).toBeInTheDocument();
    expect(screen.getAllByText("SUBMITTER")).toHaveLength(2);
  });

  it("requests submissions using the active tenant and page size", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(mockSubmissionService.list).toHaveBeenCalledWith(TENANT_ID, {
      limit: 20,
    });
  });

  it("does not request submissions without an authenticated user", async () => {
    mockUseAuth.mockReturnValue({
      user: null,
      logout: vi.fn(),
    } as unknown as ReturnType<typeof useAuth>);

    renderPage();

    expect(await screen.findByText("Welcome back, User")).toBeInTheDocument();

    expect(mockSubmissionService.list).not.toHaveBeenCalled();
  });

  it("displays the four submission metrics", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(screen.getByText("Loaded submissions")).toBeInTheDocument();
    expect(screen.getByText("Pending review")).toBeInTheDocument();
    expect(screen.getByText("Approved", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Needs changes")).toBeInTheDocument();
  });

  it("calculates submission metrics from loaded submissions", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const loadedCard = screen
      .getByText("Loaded submissions")
      .closest(".rounded-xl") as HTMLElement;

    const pendingCard = screen
      .getByText("Pending review")
      .closest(".rounded-xl") as HTMLElement;

    const approvedCard = screen
      .getByText("Approved", { selector: "p" })
      .closest(".rounded-xl") as HTMLElement;

    const changesCard = screen
      .getByText("Needs changes")
      .closest(".rounded-xl") as HTMLElement;

    expect(within(loadedCard).getByText("6")).toBeInTheDocument();
    expect(within(pendingCard).getByText("2")).toBeInTheDocument();
    expect(within(approvedCard).getByText("1")).toBeInTheDocument();
    expect(within(changesCard).getByText("1")).toBeInTheDocument();
  });

  it("calculates uploaded and pending document counts", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const documentOverview = screen
      .getByRole("heading", { name: "Document overview" })
      .closest("div.rounded-xl") as HTMLElement;

    expect(
      within(documentOverview).getByText("Uploaded documents"),
    ).toBeInTheDocument();

    expect(
      within(documentOverview).getByText("Pending uploads"),
    ).toBeInTheDocument();

    expect(within(documentOverview).getByText("17")).toBeInTheDocument();
    expect(within(documentOverview).getByText("6")).toBeInTheDocument();
  });

  it("shows the five most recent loaded submissions on the overview", async () => {
    renderPage();

    expect(await screen.findByText("Security assessment")).toBeInTheDocument();
    expect(screen.getByText("Access control assessment")).toBeInTheDocument();

    expect(
      screen.queryByText("Network security assessment"),
    ).not.toBeInTheDocument();
  });

  it("shows all loaded submissions after selecting Submissions", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Submissions" }));

    const table = await screen.findByRole("table");

    await waitFor(() => {
      expect(within(table).getAllByRole("link")).toHaveLength(6);
    });

    expect(
      within(table).getByText("Network security assessment"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Submissions", level: 1 }),
    ).toBeInTheDocument();
  });

  it("isolates dashboard submissions when switching tenants", async () => {

    const tenantBSubmission = {
      ...submissions[0],
      tenant_id: SECOND_TENANT_ID,
      submission_id: "tenant-b-submission-1",
      title: "Tenant B security assessment",
    };

    mockSubmissionService.list.mockImplementation(async (tenantId) => {
      if (tenantId === TENANT_ID) {
        return {
          items: submissions,
          next_cursor: "tenant-a-cursor",
        };
      }

      if (tenantId === SECOND_TENANT_ID) {
        return {
          items: [tenantBSubmission],
          next_cursor: null,
        };
      }

      throw new Error("Unexpected tenant ID");
    });

    const { rerender, queryClient } = renderPage();

    expect(
      await screen.findByText("Security assessment"),
    ).toBeInTheDocument();

    expect(mockSubmissionService.list).toHaveBeenCalledWith(TENANT_ID, {
      limit: 20,
    });

    const secondTenant = {
      tenant_id: SECOND_TENANT_ID,
      role: "SUBMITTER" as const,
    };

    mockUseTenant.mockReturnValue({
      tenants: [
        { tenant_id: TENANT_ID, role: "SUBMITTER" },
        secondTenant,
      ],
      activeTenant: secondTenant,
      tenantContext: {
        tenant_id: SECOND_TENANT_ID,
        user_id: USER_ID,
        role: "SUBMITTER",
      },
      loading: false,
      error: null,
      selectTenant: vi.fn(),
      refreshTenants: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useTenant>);

    rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route
              path="/submissions/:submissionId"
              element={<h1>Submission destination</h1>}
            />
            <Route path="/login" element={<h1>Login destination</h1>} />
          </Routes>
          <LocationDisplay />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Tenant B security assessment"),
    ).toBeInTheDocument();

    expect(
      screen.queryByText("Security assessment"),
    ).not.toBeInTheDocument();

    expect(mockSubmissionService.list).toHaveBeenCalledWith(
      SECOND_TENANT_ID,
      { limit: 20 },
    );

    expect(
      screen.getByRole("combobox", { name: "Select workspace" }),
    ).toHaveValue(SECOND_TENANT_ID);
  });

  it("calls selectTenant when the workspace selector changes", async () => {
    const user = userEvent.setup();
    const selectTenant = vi.fn();

    mockUseTenant.mockReturnValue({
      tenants: [
        { tenant_id: TENANT_ID, role: "SUBMITTER" },
        { tenant_id: SECOND_TENANT_ID, role: "SUBMITTER" },
      ],
      activeTenant: {
        tenant_id: TENANT_ID,
        role: "SUBMITTER",
      },
      tenantContext: {
        tenant_id: TENANT_ID,
        user_id: USER_ID,
        role: "SUBMITTER",
      },
      loading: false,
      error: null,
      selectTenant,
      refreshTenants: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useTenant>);

    renderPage();

    const selector = await screen.findByRole("combobox", {
      name: "Select workspace",
    });

    await user.selectOptions(selector, SECOND_TENANT_ID);

    expect(selectTenant).toHaveBeenCalledWith(SECOND_TENANT_ID);
  });

  it("loads and appends the next page of submissions", async () => {
    const user = userEvent.setup();

    const nextSubmission = {
      ...submissions[0],
      submission_id: "submission-7",
      title: "Additional security assessment",
    };

    mockSubmissionService.list
      .mockResolvedValueOnce({
        items: submissions,
        next_cursor: "page-2-cursor",
      })
      .mockResolvedValueOnce({
        items: [nextSubmission],
        next_cursor: null,
      });

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Submissions" }));

    expect(
      await screen.findByText("Network security assessment"),
    ).toBeInTheDocument();

    const loadMoreButton = screen.getByRole("button", {
      name: "Load more submissions",
    });

    await user.click(loadMoreButton);

    expect(
      await screen.findByText("Additional security assessment"),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Security assessment"),
    ).toBeInTheDocument();

    expect(mockSubmissionService.list).toHaveBeenNthCalledWith(2, TENANT_ID, {
      limit: 20,
      cursor: "page-2-cursor",
    });

    expect(
      screen.queryByRole("button", { name: "Load more submissions" }),
    ).not.toBeInTheDocument();
  });

  it("preserves loaded submissions when loading the next page fails and supports retry", async () => {
    const user = userEvent.setup();

    const nextSubmission = {
      ...submissions[0],
      submission_id: "submission-7",
      title: "Additional security assessment",
    };

    mockSubmissionService.list
      .mockResolvedValueOnce({
        items: submissions,
        next_cursor: "page-2-cursor",
      })
      .mockRejectedValueOnce(new Error("Temporary network failure"))
      .mockRejectedValueOnce(new Error("Temporary network failure"))
      .mockResolvedValueOnce({
        items: [nextSubmission],
        next_cursor: null,
      });

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Submissions" }));

    await screen.findByText("Network security assessment");

    await user.click(
      screen.getByRole("button", { name: "Load more submissions" }),
    );

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("Previously loaded submissions are still available.");

    expect(screen.getByText("Security assessment")).toBeInTheDocument();

    expect(
      screen.getByText("Network security assessment"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Retry loading more" }),
    );

    expect(
      await screen.findByText("Additional security assessment"),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Security assessment"),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("alert"),
    ).not.toBeInTheDocument();

    expect(
      screen.queryByRole("button", { name: "Load more submissions" }),
    ).not.toBeInTheDocument();
  });

  it("does not show Load More when there are no additional pages", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(
      screen.queryByRole("button", { name: "Load more submissions" }),
    ).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no submissions", async () => {
    mockSubmissionService.list.mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    renderPage();

    expect(await screen.findByText("No submissions yet")).toBeInTheDocument();

    expect(
      screen.getByText(
        "Submissions created in this workspace will appear here.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the loading state while submissions are loading", async () => {
    mockSubmissionService.list.mockReturnValue(new Promise(() => {}));

    renderPage();

    expect(
      await screen.findByText("Loading submissions..."),
    ).toBeInTheDocument();
  });

  it("shows an error state when submission loading fails", async () => {
    mockSubmissionService.list
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockRejectedValueOnce(new Error("Submission service unavailable"));

    renderPage();

    expect(
      await screen.findByText(
        "Unable to load submissions",
        {},
        { timeout: 5000 },
      ),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Submission service unavailable"),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();

    expect(mockSubmissionService.list).toHaveBeenCalledTimes(2);
  });

  it("allows manually refreshing submissions", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(
      screen.getByRole("button", { name: "Refresh submissions" }),
    );

    await waitFor(() => {
      expect(mockSubmissionService.list).toHaveBeenCalledTimes(2);
    });
  });

  it("shows the View all action on the overview", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(
      screen.getByRole("button", { name: /View all/i }),
    ).toBeInTheDocument();
  });

  it("opens the Submissions section using View all", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: /View all/i }));

    expect(
      screen.getByRole("heading", { name: "Submissions", level: 1 }),
    ).toBeInTheDocument();
  });

  it("navigates to a submission when its row is clicked", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(
      screen.getByRole("link", {
        name: "Open documents for Security assessment",
      }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Submission destination",
      }),
    ).toBeInTheDocument();

    expect(screen.getByTestId("current-location")).toHaveTextContent(
      "/submissions/submission-1",
    );
  });

  it("supports keyboard navigation from a submission row", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    const row = screen.getByRole("link", {
      name: "Open documents for Security assessment",
    });

    row.focus();
    await user.keyboard("{Enter}");

    expect(
      await screen.findByRole("heading", {
        name: "Submission destination",
      }),
    ).toBeInTheDocument();
  });

  it("shows the New submission action only to submitters", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(
      screen.getByRole("button", { name: "New submission" }),
    ).toBeInTheDocument();
  });

  it.each(["REVIEWER", "TENANT_ADMIN"] as const)(
    "does not show New submission to %s users",
    async (role) => {
      setUserAndTenant(role);

      renderPage();

      await screen.findByText("Security assessment");

      expect(
        screen.queryByRole("button", { name: "New submission" }),
      ).not.toBeInTheDocument();
    },
  );

  it("opens the create submission modal for a submitter", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "New submission" }));

    expect(screen.getByTestId("create-submission-modal")).toHaveTextContent(
      `${TENANT_ID} / ${USER_ID}`,
    );
  });

  it("closes the create submission modal", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "New submission" }));

    await user.click(screen.getByRole("button", { name: "Close modal" }));

    expect(
      screen.queryByTestId("create-submission-modal"),
    ).not.toBeInTheDocument();
  });

  it("opens the Team members panel", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Team members" }));

    expect(screen.getByTestId("team-members-panel")).toHaveTextContent(
      `${TENANT_ID} / ${USER_ID} / SUBMITTER`,
    );
  });

  it("opens the Audit activity panel", async () => {
    const user = userEvent.setup();

    setUserAndTenant("TENANT_ADMIN");

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Audit activity" }));

    expect(screen.getByTestId("tenant-audit-panel")).toHaveTextContent(
      `${TENANT_ID} / ${USER_ID} / TENANT_ADMIN`,
    );
  });

  it("does not navigate to the unavailable Documents section", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("Security assessment");

    const documentsButton = screen.getByRole("button", {
      name: /Documents/,
    });

    expect(documentsButton).toBeDisabled();

    await user.click(documentsButton);

    expect(
      screen.getByRole("heading", { name: "Overview" }),
    ).toBeInTheDocument();
  });

  it("displays the active tenant membership role from tenant context", async () => {
    setUserAndTenant("SUBMITTER", {
      tenantContextRole: "REVIEWER",
    });

    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Welcome back, harsh.maurya",
      }),
    ).toBeInTheDocument();

    expect(screen.getAllByText("REVIEWER")).toHaveLength(2);

    expect(
      screen.queryByRole("button", { name: "New submission" }),
    ).not.toBeInTheDocument();
  });

  it("falls back to the active tenant role when tenant context is unavailable", async () => {
    setUserAndTenant("REVIEWER", {
      tenantContextRole: null,
    });

    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Welcome back, harsh.maurya",
      }),
    ).toBeInTheDocument();

    expect(screen.getAllByText("REVIEWER")).toHaveLength(2);
  });

  it("shows the workspace loading state", () => {
    setUserAndTenant("SUBMITTER", {
      loading: true,
    });

    renderPage();

    expect(screen.getByText("Loading workspace...")).toBeInTheDocument();

    expect(mockSubmissionService.list).toHaveBeenCalledWith(TENANT_ID, {
      limit: 20,
    });
  });

  it("shows the workspace error and allows retrying", async () => {
    const user = userEvent.setup();

    const refreshTenants = vi.fn().mockResolvedValue(undefined);

    setUserAndTenant("SUBMITTER", {
      error: "Unable to retrieve workspace memberships.",
    });

    mockUseTenant.mockReturnValue({
      tenants: [{ tenant_id: TENANT_ID, role: "SUBMITTER" }],
      activeTenant: null,
      tenantContext: null,
      loading: false,
      error: "Unable to retrieve workspace memberships.",
      selectTenant: vi.fn(),
      refreshTenants,
    } as unknown as ReturnType<typeof useTenant>);

    renderPage();

    expect(
      screen.getByRole("heading", { name: "Unable to load workspaces" }),
    ).toBeInTheDocument();

    expect(
      screen.getByText("Unable to retrieve workspace memberships."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(refreshTenants).toHaveBeenCalledTimes(1);
  });

  it("shows the no workspace membership state", () => {
    setUserAndTenant("SUBMITTER", {
      activeTenant: false,
      tenants: [],
    });

    renderPage();

    expect(
      screen.getByRole("heading", {
        name: "No workspace membership found",
      }),
    ).toBeInTheDocument();

    expect(mockSubmissionService.list).not.toHaveBeenCalled();
  });

  it("allows signing out and redirects to the login page", async () => {
    const user = userEvent.setup();
    const logout = vi.fn().mockResolvedValue(undefined);

    mockUseAuth.mockReturnValue({
      user: {
        userId: USER_ID,
        username: "harsh.maurya",
      },
      logout,
    } as unknown as ReturnType<typeof useAuth>);

    renderPage();

    await screen.findByText("Security assessment");

    await user.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(logout).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByTestId("current-location")).toHaveTextContent("/login");
  });

  it("displays the workspace security status", async () => {
    renderPage();

    await screen.findByText("Security controls enabled");

    expect(screen.getByText("Your workspace is protected")).toBeInTheDocument();

    expect(
      screen.getByText(
        "Tenant membership, workflow permissions and document access are enforced by the backend.",
      ),
    ).toBeInTheDocument();
  });
});
