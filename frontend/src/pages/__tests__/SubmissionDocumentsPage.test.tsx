import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "../../features/auth/useAuth";
import { useTenant } from "../../features/tenants/useTenant";
import { documentService, submissionService } from "../../lib/apiServices";
import SubmissionDocumentsPage from "../SubmissionDocumentsPage";
import type { SubmissionStatus } from "../../types/api";

vi.mock("../../features/auth/useAuth", () => ({
  useAuth: vi.fn(),
}));

vi.mock("../../features/tenants/useTenant", () => ({
  useTenant: vi.fn(),
}));

vi.mock("../../lib/apiServices", () => ({
  documentService: {
    list: vi.fn(),
    requestUpload: vi.fn(),
    uploadToS3: vi.fn(),
    completeUpload: vi.fn(),
    getDownloadUrl: vi.fn(),
  },
  submissionService: {
    get: vi.fn(),
  },
}));

const mockUseAuth = vi.mocked(useAuth);
const mockUseTenant = vi.mocked(useTenant);
const mockSubmissionService = vi.mocked(submissionService);
const mockDocumentService = vi.mocked(documentService);

const TENANT_ID = "tenant-123";
const USER_ID = "user-123";
const SUBMISSION_ID = "submission-123";

const submission = {
  tenant_id: TENANT_ID,
  submission_id: SUBMISSION_ID,
  title: "Security assessment",
  description: "Assessment documents",
  status: "DRAFT" as SubmissionStatus,
  created_at: "2026-11-18T10:00:00Z",
  updated_at: "2026-11-18T10:00:00Z",
  version: 1,
  pending_document_count: 0,
  uploaded_document_count: 0,
};

const uploadedDocument = {
  document_id: "document-123",
  submission_id: SUBMISSION_ID,
  filename: "assessment.pdf",
  content_type: "application/pdf",
  size_bytes: 1024,
  status: "UPLOADED" as const,
  created_at: "2026-11-18T10:00:00Z",
};

const pendingDocument = {
  ...uploadedDocument,
  document_id: "document-456",
  filename: "pending.pdf",
  status: "PENDING_UPLOAD" as const,
};

const uploadResponse = {
  document_id: "document-new",
  upload_url: "https://s3.example.com/upload",
  upload_fields: {
    key: "tenant/submission/document",
    policy: "test-policy",
  },
  expires_in: 300,
};

type TestRole = "SUBMITTER" | "REVIEWER" | "TENANT_ADMIN";

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

function renderPage(
  options: {
    role?: TestRole;
    status?: SubmissionStatus;
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

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[`/submissions/${SUBMISSION_ID}/documents`]}
      >
        <Routes>
          <Route
            path="/submissions/:submissionId/documents"
            element={<SubmissionDocumentsPage />}
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

describe("SubmissionDocumentsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();

    mockSubmissionService.get.mockResolvedValue(submission);

    mockDocumentService.list.mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    mockDocumentService.requestUpload.mockResolvedValue(uploadResponse);
    mockDocumentService.uploadToS3.mockResolvedValue(undefined);
    mockDocumentService.completeUpload.mockResolvedValue(uploadedDocument);
    mockDocumentService.getDownloadUrl.mockResolvedValue({
      document_id: uploadedDocument.document_id,
      download_url: "https://s3.example.com/download",
      expires_in: 300,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads and displays the submission and documents", async () => {
    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument, pendingDocument],
      next_cursor: null,
    });

    renderPage();

    expect(await screen.findByText("Security assessment")).toBeInTheDocument();

    expect(await screen.findByText("assessment.pdf")).toBeInTheDocument();
    expect(screen.getByText("pending.pdf")).toBeInTheDocument();
    expect(screen.getByText("Uploaded")).toBeInTheDocument();
    expect(screen.getByText("Pending upload")).toBeInTheDocument();
  });

  it("requests the submission using the active tenant and submission IDs", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    expect(mockSubmissionService.get).toHaveBeenCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
    );
  });

  it("requests documents using the active tenant and submission IDs", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    await waitFor(() => {
      expect(mockDocumentService.list).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        {
          limit: 20,
        },
      );
    });
  });

  it("shows the upload input for a submitter when the submission is a draft", async () => {
    renderPage({
      role: "SUBMITTER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    expect(fileInput).toBeInTheDocument();
    expect(fileInput.accept).toContain("application/pdf");
  });

  it("does not show the upload button for a submitter when the submission is not a draft", async () => {
    renderPage({
      role: "SUBMITTER",
      status: "SUBMITTED",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.queryByRole("button", { name: /upload/i }),
    ).not.toBeInTheDocument();
  });

  it("does not show the upload button for a reviewer", async () => {
    renderPage({
      role: "REVIEWER",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.queryByRole("button", { name: /upload/i }),
    ).not.toBeInTheDocument();
  });

  it("does not show the upload button for a tenant admin", async () => {
    renderPage({
      role: "TENANT_ADMIN",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");

    expect(
      screen.queryByRole("button", { name: /upload/i }),
    ).not.toBeInTheDocument();
  });

  it("rejects unsupported file types without requesting an upload", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["test content"], "evidence.txt", {
      type: "text/plain",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only PDF, JPEG, and PNG files are supported.",
    );

    expect(mockDocumentService.requestUpload).not.toHaveBeenCalled();
    expect(mockDocumentService.uploadToS3).not.toHaveBeenCalled();
    expect(mockDocumentService.completeUpload).not.toHaveBeenCalled();
  });

  it("rejects empty files without requesting an upload", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File([], "empty.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "File size must be greater than 0 and at most 10 MB.",
    );

    expect(mockDocumentService.requestUpload).not.toHaveBeenCalled();
  });

  it("rejects files larger than 10 MB without requesting an upload", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "large.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "File size must be greater than 0 and at most 10 MB.",
    );

    expect(mockDocumentService.requestUpload).not.toHaveBeenCalled();
  });

  it("completes the upload workflow in the correct order", async () => {
    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["%PDF-1.7"], "evidence.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    await waitFor(() => {
      expect(mockDocumentService.completeUpload).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        uploadResponse.document_id,
      );
    });

    expect(mockDocumentService.requestUpload).toHaveBeenCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
      {
        filename: "evidence.pdf",
        content_type: "application/pdf",
        size_bytes: file.size,
      },
    );

    expect(mockDocumentService.uploadToS3).toHaveBeenCalledWith(
      uploadResponse,
      file,
    );

    expect(
      mockDocumentService.requestUpload.mock.invocationCallOrder[0],
    ).toBeLessThan(mockDocumentService.uploadToS3.mock.invocationCallOrder[0]);

    expect(
      mockDocumentService.uploadToS3.mock.invocationCallOrder[0],
    ).toBeLessThan(
      mockDocumentService.completeUpload.mock.invocationCallOrder[0],
    );
  });

  it("does not upload to S3 when requesting an upload fails", async () => {
    mockDocumentService.requestUpload.mockRejectedValueOnce(
      new Error("Upload request failed"),
    );

    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["%PDF-1.7"], "evidence.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Upload request failed",
    );

    expect(mockDocumentService.uploadToS3).not.toHaveBeenCalled();
    expect(mockDocumentService.completeUpload).not.toHaveBeenCalled();
  });

  it("does not complete the upload when the S3 upload fails", async () => {
    mockDocumentService.uploadToS3.mockRejectedValueOnce(
      new Error("S3 upload failed"),
    );

    renderPage();

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["%PDF-1.7"], "evidence.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "S3 upload failed",
    );

    expect(mockDocumentService.requestUpload).toHaveBeenCalled();
    expect(mockDocumentService.uploadToS3).toHaveBeenCalled();
    expect(mockDocumentService.completeUpload).not.toHaveBeenCalled();
  });

  it("does not invalidate document queries when the upload fails", async () => {
    mockDocumentService.requestUpload.mockRejectedValueOnce(
      new Error("Upload request failed"),
    );

    const { queryClient } = renderPage();

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await screen.findByText("Security assessment");

    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;

    const file = new File(["%PDF-1.7"], "evidence.pdf", {
      type: "application/pdf",
    });

    fireEvent.change(fileInput, {
      target: {
        files: [file],
      },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Upload request failed",
    );

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("downloads an uploaded document using its returned download URL", async () => {
    const user = userEvent.setup();

    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument],
      next_cursor: null,
    });

    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    renderPage();

    await screen.findByText("Security assessment");

    const downloadButton = await screen.findByRole("button", {
      name: "Download assessment.pdf",
    });

    await user.click(downloadButton);

    await waitFor(() => {
      expect(mockDocumentService.getDownloadUrl).toHaveBeenCalledWith(
        TENANT_ID,
        SUBMISSION_ID,
        uploadedDocument.document_id,
      );
    });

    expect(clickSpy).toHaveBeenCalled();
  });

  it("prevents duplicate download requests while a download is pending", async () => {
    const user = userEvent.setup();

    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument],
      next_cursor: null,
    });

    let resolveDownload!: (value: {
      document_id: string;
      download_url: string;
      expires_in: number;
    }) => void;

    mockDocumentService.getDownloadUrl.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveDownload = resolve;
        }),
    );

    renderPage();

    await screen.findByText("Security assessment");

    const downloadButton = await screen.findByRole("button", {
      name: "Download assessment.pdf",
    });

    await user.click(downloadButton);

    expect(
      await screen.findByRole("button", {
        name: "Downloading assessment.pdf",
      }),
    ).toBeDisabled();

    expect(mockDocumentService.getDownloadUrl).toHaveBeenCalledTimes(1);

    resolveDownload({
      document_id: uploadedDocument.document_id,
      download_url: "https://s3.example.com/download",
      expires_in: 300,
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "Download assessment.pdf",
        }),
      ).toBeEnabled();
    });

    expect(mockDocumentService.getDownloadUrl).toHaveBeenCalledTimes(1);
  });

  it("shows an error when requesting a download URL fails", async () => {
    const user = userEvent.setup();

    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument],
      next_cursor: null,
    });

    mockDocumentService.getDownloadUrl.mockRejectedValueOnce(
      new Error("Download request failed"),
    );

    renderPage();

    await screen.findByText("Security assessment");

    const downloadButton = await screen.findByRole("button", {
      name: "Download assessment.pdf",
    });

    await user.click(downloadButton);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Download request failed",
    );
  });

  it("does not provide a download button for a pending document", async () => {
    mockDocumentService.list.mockResolvedValue({
      items: [pendingDocument],
      next_cursor: null,
    });

    renderPage();

    await screen.findByText("Security assessment");
    await screen.findByText("pending.pdf");

    expect(
      screen.queryByRole("button", {
        name: "Download pending.pdf",
      }),
    ).not.toBeInTheDocument();
  });

  it("does not provide a download button for a tenant admin", async () => {
    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument],
      next_cursor: null,
    });

    renderPage({
      role: "TENANT_ADMIN",
      status: "DRAFT",
    });

    await screen.findByText("Security assessment");
    await screen.findByText("assessment.pdf");

    expect(
      screen.queryByRole("button", {
        name: "Download assessment.pdf",
      }),
    ).not.toBeInTheDocument();

    expect(
      mockDocumentService.getDownloadUrl,
    ).not.toHaveBeenCalled();
  });

  it("loads the next document page when more documents are available", async () => {
    const user = userEvent.setup();

    mockDocumentService.list
      .mockResolvedValueOnce({
        items: [uploadedDocument],
        next_cursor: "next-page-cursor",
      })
      .mockResolvedValueOnce({
        items: [
          {
            ...uploadedDocument,
            document_id: "document-next",
            filename: "next-page.pdf",
          },
        ],
        next_cursor: null,
      });

    renderPage();

    await screen.findByText("Security assessment");
    expect(await screen.findByText("assessment.pdf")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: /load more/i,
      }),
    );

    expect(await screen.findByText("next-page.pdf")).toBeInTheDocument();

    expect(mockDocumentService.list).toHaveBeenLastCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
      {
        limit: 20,
        cursor: "next-page-cursor",
      },
    );
  });

  it("preserves loaded documents and allows retry when the next page fails", async () => {
    const user = userEvent.setup();

    const nextDocument = {
      ...uploadedDocument,
      document_id: "document-next",
      filename: "next-page.pdf",
    };

    mockDocumentService.list
      .mockResolvedValueOnce({
        items: [uploadedDocument],
        next_cursor: "next-page-cursor",
      })
      .mockRejectedValueOnce(
        new Error("Next page request failed"),
      )
      .mockResolvedValueOnce({
        items: [nextDocument],
        next_cursor: null,
      });

    renderPage();

    await screen.findByText("Security assessment");
    expect(await screen.findByText("assessment.pdf")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "Load more documents",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Next page request failed",
    );

    expect(screen.getByText("assessment.pdf")).toBeInTheDocument();

    const retryButton = screen.getByRole("button", {
      name: "Retry loading more documents",
    });

    await user.click(retryButton);

    expect(await screen.findByText("next-page.pdf")).toBeInTheDocument();

    expect(screen.getByText("assessment.pdf")).toBeInTheDocument();

    expect(screen.getAllByText("assessment.pdf")).toHaveLength(1);

    expect(mockDocumentService.list).toHaveBeenLastCalledWith(
      TENANT_ID,
      SUBMISSION_ID,
      {
        limit: 20,
        cursor: "next-page-cursor",
      },
    );
  });

  it("refreshes the document list when the refresh control is clicked", async () => {
    const user = userEvent.setup();

    mockDocumentService.list.mockResolvedValue({
      items: [uploadedDocument],
      next_cursor: null,
    });

    renderPage();

    await screen.findByText("Security assessment");
    await screen.findByText("assessment.pdf");

    const initialCallCount = mockDocumentService.list.mock.calls.length;

    await user.click(
      screen.getByRole("button", {
        name: "Refresh documents",
      }),
    );

    await waitFor(() => {
      expect(mockDocumentService.list.mock.calls.length).toBeGreaterThan(
        initialCallCount,
      );
    });
  });
});
