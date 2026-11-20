import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { tenantService } from "../../../lib/apiServices";
import TeamMembersPanel from "../TeamMembersPanel";
import type { TenantMember, TenantRole } from "../../../types/api";

vi.mock("../../../lib/apiServices", () => ({
  tenantService: {
    listMembers: vi.fn(),
    changeMemberRole: vi.fn(),
    deactivateMember: vi.fn(),
  },
}));

const mockTenantService = vi.mocked(tenantService);

const TENANT_ID = "tenant-123";
const CURRENT_USER_ID = "admin-123";

type TestRole = TenantRole | "Unknown";

const members = [
  {
    user_id: CURRENT_USER_ID,
    role: "TENANT_ADMIN",
    status: "ACTIVE",
    created_at: "2026-11-01T10:00:00Z",
  },
  {
    user_id: "submitter-123",
    role: "SUBMITTER",
    status: "ACTIVE",
    created_at: "2026-11-02T10:00:00Z",
  },
  {
    user_id: "reviewer-123",
    role: "REVIEWER",
    status: "ACTIVE",
    created_at: "2026-11-03T10:00:00Z",
  },
  {
    user_id: "inactive-123",
    role: "SUBMITTER",
    status: "INACTIVE",
    created_at: "2026-11-04T10:00:00Z",
  },
] as TenantMember[];

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

function renderPanel(role: TestRole = "TENANT_ADMIN") {
  const queryClient = createQueryClient();

  return render(
    <QueryClientProvider client={queryClient}>
      <TeamMembersPanel
        tenantId={TENANT_ID}
        currentUserId={CURRENT_USER_ID}
        role={role}
      />
    </QueryClientProvider>,
  );
}

function getMemberRow(userId: string) {
  return screen.getByText(userId).closest("tr") as HTMLTableRowElement;
}

beforeEach(() => {
  vi.resetAllMocks();

  mockTenantService.listMembers.mockResolvedValue(members);
  mockTenantService.changeMemberRole.mockResolvedValue({} as never);
  mockTenantService.deactivateMember.mockResolvedValue({} as never);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("TeamMembersPanel", () => {
  it("loads and displays workspace members for a tenant administrator", async () => {
    renderPanel();

    expect(await screen.findByText("submitter-123")).toBeInTheDocument();
    expect(screen.getByText("reviewer-123")).toBeInTheDocument();
    expect(screen.getByText("inactive-123")).toBeInTheDocument();

    expect(mockTenantService.listMembers).toHaveBeenCalledWith(TENANT_ID);
  });

  it("does not request member data for a submitter", () => {
    renderPanel("SUBMITTER");

    expect(
      screen.getByText("Administrator access required"),
    ).toBeInTheDocument();

    expect(mockTenantService.listMembers).not.toHaveBeenCalled();
  });

  it("does not request member data for a reviewer", () => {
    renderPanel("REVIEWER");

    expect(
      screen.getByText("Administrator access required"),
    ).toBeInTheDocument();

    expect(mockTenantService.listMembers).not.toHaveBeenCalled();
  });

  it("does not request member data when the role is unknown", () => {
    renderPanel("Unknown");

    expect(
      screen.getByText("Administrator access required"),
    ).toBeInTheDocument();

    expect(mockTenantService.listMembers).not.toHaveBeenCalled();
  });

  it("displays active and inactive member counts", async () => {
    renderPanel();

    await screen.findByText("submitter-123");

    const activeCard = screen.getByText("Active members").parentElement;
    const inactiveCard = screen.getByText("Inactive members").parentElement;

    expect(activeCard).not.toBeNull();
    expect(inactiveCard).not.toBeNull();

    expect(
      within(activeCard as HTMLElement).getByText("3"),
    ).toBeInTheDocument();
    expect(
      within(inactiveCard as HTMLElement).getByText("1"),
    ).toBeInTheDocument();
  });

  it("displays member roles and membership statuses", async () => {
    renderPanel();

    await screen.findByText("submitter-123");

    expect(screen.getByText("Tenant Admin")).toBeInTheDocument();

    expect(
      within(getMemberRow("submitter-123")).getByRole("combobox", {
        name: "Role for submitter-123",
      }),
    ).toHaveValue("SUBMITTER");

    expect(
      within(getMemberRow("reviewer-123")).getByRole("combobox", {
        name: "Role for reviewer-123",
      }),
    ).toHaveValue("REVIEWER");

    expect(screen.getAllByText("Active")).toHaveLength(3);
    expect(screen.getAllByText("Inactive")).toHaveLength(2);
  });

  it("identifies the current administrator account", async () => {
    renderPanel();

    await screen.findByText(CURRENT_USER_ID);

    expect(screen.getByText("Current account")).toBeInTheDocument();
  });

  it("does not allow modification of the tenant administrator account", async () => {
    renderPanel();

    await screen.findByText(CURRENT_USER_ID);

    const row = getMemberRow(CURRENT_USER_ID);

    expect(within(row).getByText("Tenant Admin")).toBeInTheDocument();
    expect(within(row).getByText("Current account")).toBeInTheDocument();

    expect(
      within(row).queryByRole("combobox", {
        name: `Role for ${CURRENT_USER_ID}`,
      }),
    ).not.toBeInTheDocument();

    expect(
      within(row).queryByRole("button", {
        name: `Deactivate ${CURRENT_USER_ID}`,
      }),
    ).not.toBeInTheDocument();
  });

  it("does not allow modification of inactive members", async () => {
    renderPanel();

    await screen.findByText("inactive-123");

    const row = getMemberRow("inactive-123");

    expect(
      within(row).getByRole("combobox", {
        name: "Role for inactive-123",
      }),
    ).toBeDisabled();

    expect(
      within(row).queryByRole("button", {
        name: "Deactivate inactive-123",
      }),
    ).not.toBeInTheDocument();
  });

  it("changes a member role using the expected current role", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("reviewer-123");

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Role for reviewer-123",
      }),
      "SUBMITTER",
    );

    await waitFor(() => {
      expect(mockTenantService.changeMemberRole).toHaveBeenCalledWith(
        TENANT_ID,
        "reviewer-123",
        {
          expected_role: "REVIEWER",
          new_role: "SUBMITTER",
        },
      );
    });
  });

  it("does not call the role update API when a member keeps the same role", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("submitter-123");

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Role for submitter-123",
      }),
      "SUBMITTER",
    );

    expect(mockTenantService.changeMemberRole).not.toHaveBeenCalled();
  });

  it("asks for confirmation before deactivating a member", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderPanel();

    await screen.findByText("submitter-123");

    await user.click(
      screen.getByRole("button", {
        name: "Deactivate submitter-123",
      }),
    );

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockTenantService.deactivateMember).not.toHaveBeenCalled();
  });

  it("deactivates a member after confirmation using the expected role", async () => {
    const user = userEvent.setup();

    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPanel();

    await screen.findByText("submitter-123");

    await user.click(
      screen.getByRole("button", {
        name: "Deactivate submitter-123",
      }),
    );

    await waitFor(() => {
      expect(mockTenantService.deactivateMember).toHaveBeenCalledWith(
        TENANT_ID,
        "submitter-123",
        {
          expected_role: "SUBMITTER",
        },
      );
    });
  });

  it("refreshes the member list after a successful role update", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("reviewer-123");

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Role for reviewer-123",
      }),
      "SUBMITTER",
    );

    await waitFor(() => {
      expect(mockTenantService.listMembers).toHaveBeenCalledTimes(2);
    });
  });

  it("refreshes the member list after successful deactivation", async () => {
    const user = userEvent.setup();

    vi.spyOn(window, "confirm").mockReturnValue(true);

    renderPanel();

    await screen.findByText("submitter-123");

    await user.click(
      screen.getByRole("button", {
        name: "Deactivate submitter-123",
      }),
    );

    await waitFor(() => {
      expect(mockTenantService.listMembers).toHaveBeenCalledTimes(2);
    });
  });

  it("shows an error when a role update fails", async () => {
    const user = userEvent.setup();

    mockTenantService.changeMemberRole.mockRejectedValueOnce(
      new Error("Role update failed"),
    );

    renderPanel();

    await screen.findByText("reviewer-123");

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Role for reviewer-123",
      }),
      "SUBMITTER",
    );

    expect(
      await screen.findByText(
        "An unexpected error occurred. Please try again.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error when member deactivation fails", async () => {
    const user = userEvent.setup();

    vi.spyOn(window, "confirm").mockReturnValue(true);

    mockTenantService.deactivateMember.mockRejectedValueOnce(
      new Error("Deactivation failed"),
    );

    renderPanel();

    await screen.findByText("submitter-123");

    await user.click(
      screen.getByRole("button", {
        name: "Deactivate submitter-123",
      }),
    );

    expect(
      await screen.findByText(
        "An unexpected error occurred. Please try again.",
      ),
    ).toBeInTheDocument();
  });

  it("refreshes the member list when a role update fails", async () => {
    const user = userEvent.setup();

    mockTenantService.changeMemberRole.mockRejectedValueOnce(
      new Error("Role update failed"),
    );

    renderPanel();

    await screen.findByText("reviewer-123");

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Role for reviewer-123",
      }),
      "SUBMITTER",
    );

    await waitFor(() => {
      expect(mockTenantService.listMembers).toHaveBeenCalledTimes(2);
    });
  });

  it("shows an empty state when the workspace has no members", async () => {
    mockTenantService.listMembers.mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText("No members found")).toBeInTheDocument();
  });

  it("shows an error when the member list cannot be loaded", async () => {
    mockTenantService.listMembers
      .mockRejectedValueOnce(new Error("Member service unavailable"))
      .mockRejectedValueOnce(new Error("Member service unavailable"));

    renderPanel();

    expect(
      await screen.findByText("Unable to load members"),
    ).toBeInTheDocument();

    expect(
      screen.getByText("An unexpected error occurred. Please try again."),
    ).toBeInTheDocument();
  });

  it("allows retrying when the member list fails to load", async () => {
    const user = userEvent.setup();

    mockTenantService.listMembers
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValueOnce(members);

    renderPanel();

    expect(
      await screen.findByText("Unable to load members"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("submitter-123")).toBeInTheDocument();

    expect(mockTenantService.listMembers).toHaveBeenCalledTimes(3);
  });

  it("allows manually refreshing the member list", async () => {
    const user = userEvent.setup();

    renderPanel();

    await screen.findByText("submitter-123");

    await user.click(screen.getByRole("button", { name: "Refresh members" }));

    await waitFor(() => {
      expect(mockTenantService.listMembers).toHaveBeenCalledTimes(2);
    });
  });
});
