import axios from "axios";
import api from "./api";

import type {
  TenantMembership,
  TenantContext,
  TenantMember,
  MembershipMutationResponse,
  ChangeMemberRoleRequest,
  DeactivateMemberRequest,
  SubmissionCreateRequest,
  SubmissionResponse,
  SubmissionListResponse,
  DocumentUploadRequest,
  DocumentUploadResponse,
  DocumentResponse,
  DocumentDownloadResponse,
  SubmissionTransitionRequest,
  SubmissionTransitionResponse,
  AuditEventListResponse,
  PaginatedRequest,
  DocumentListResponse,
  TenantAuditEventListResponse,
} from "../types/api";

const tenantPath = (tenantId: string) =>
  `/tenants/${encodeURIComponent(tenantId)}`;

const submissionPath = (tenantId: string, submissionId: string) =>
  `${tenantPath(tenantId)}/submissions/${encodeURIComponent(submissionId)}`;

export const tenantService = {
  async listTenants(): Promise<TenantMembership[]> {
    const response = await api.get<TenantMembership[]>("/tenants");
    return response.data;
  },

  async getContext(tenantId: string): Promise<TenantContext> {
    const response = await api.get<TenantContext>(
      `${tenantPath(tenantId)}/context`,
    );
    return response.data;
  },

  async listMembers(tenantId: string): Promise<TenantMember[]> {
    const response = await api.get<TenantMember[]>(
      `${tenantPath(tenantId)}/members`,
    );
    return response.data;
  },

  async changeMemberRole(
    tenantId: string,
    userId: string,
    request: ChangeMemberRoleRequest,
  ): Promise<MembershipMutationResponse> {
    const response = await api.patch<MembershipMutationResponse>(
      `${tenantPath(tenantId)}/members/${encodeURIComponent(userId)}/role`,
      request,
    );
    return response.data;
  },

  async deactivateMember(
    tenantId: string,
    userId: string,
    request: DeactivateMemberRequest,
  ): Promise<MembershipMutationResponse> {
    const response = await api.post<MembershipMutationResponse>(
      `${tenantPath(tenantId)}/members/${encodeURIComponent(userId)}/deactivate`,
      request,
    );
    return response.data;
  },
};

export const submissionService = {
  async list(
    tenantId: string,
    options: PaginatedRequest = {},
  ): Promise<SubmissionListResponse> {
    const response = await api.get<SubmissionListResponse>(
      `${tenantPath(tenantId)}/submissions`,
      {
        params: {
          limit: options.limit ?? 20,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        },
      },
    );
    return response.data;
  },

  async get(
    tenantId: string,
    submissionId: string,
  ): Promise<SubmissionResponse> {
    const response = await api.get<SubmissionResponse>(
      submissionPath(tenantId, submissionId),
    );
    return response.data;
  },

  async create(
    tenantId: string,
    request: SubmissionCreateRequest,
  ): Promise<SubmissionResponse> {
    const response = await api.post<SubmissionResponse>(
      `${tenantPath(tenantId)}/submissions`,
      request,
    );
    return response.data;
  },
};

export const documentService = {
  async list(
    tenantId: string,
    submissionId: string,
    options: PaginatedRequest = {},
  ): Promise<DocumentListResponse> {
    const response = await api.get<DocumentListResponse>(
      `${submissionPath(tenantId, submissionId)}/documents`,
      {
        params: {
          limit: options.limit ?? 20,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        },
      },
    );
    return response.data;
  },

  async requestUpload(
    tenantId: string,
    submissionId: string,
    request: DocumentUploadRequest,
  ): Promise<DocumentUploadResponse> {
    const response = await api.post<DocumentUploadResponse>(
      `${submissionPath(tenantId, submissionId)}/documents`,
      request,
    );
    return response.data;
  },

  async uploadToS3(upload: DocumentUploadResponse, file: File): Promise<void> {
    const formData = new FormData();

    for (const [key, value] of Object.entries(upload.upload_fields)) {
      formData.append(key, value);
    }

    formData.append("file", file);

    // This is a direct presigned S3 POST.
    // Do not attach the Cognito API bearer token here.
    await axios.post(upload.upload_url, formData, {
      timeout: 60000,
    });
  },

  async completeUpload(
    tenantId: string,
    submissionId: string,
    documentId: string,
  ): Promise<DocumentResponse> {
    const response = await api.post<DocumentResponse>(
      `${submissionPath(tenantId, submissionId)}/documents/${encodeURIComponent(documentId)}/complete`,
    );
    return response.data;
  },

  async getDownloadUrl(
    tenantId: string,
    submissionId: string,
    documentId: string,
  ): Promise<DocumentDownloadResponse> {
    const response = await api.get<DocumentDownloadResponse>(
      `${submissionPath(tenantId, submissionId)}/documents/${encodeURIComponent(documentId)}/download`,
    );
    return response.data;
  },
};

export const workflowService = {
  async transition(
    tenantId: string,
    submissionId: string,
    request: SubmissionTransitionRequest,
  ): Promise<SubmissionTransitionResponse> {
    const response = await api.post<SubmissionTransitionResponse>(
      `${submissionPath(tenantId, submissionId)}/transitions`,
      request,
    );
    return response.data;
  },
};

export const auditService = {
  async listSubmissionEvents(
    tenantId: string,
    submissionId: string,
    options: PaginatedRequest = {},
  ): Promise<AuditEventListResponse> {
    const response = await api.get<AuditEventListResponse>(
      `${submissionPath(tenantId, submissionId)}/audit-events`,
      {
        params: {
          limit: options.limit ?? 20,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        },
      },
    );
    return response.data;
  },

  async listTenantEvents(
    tenantId: string,
    options: PaginatedRequest = {},
  ): Promise<TenantAuditEventListResponse> {
    const response = await api.get<TenantAuditEventListResponse>(
      `${tenantPath(tenantId)}/audit-events`,
      {
        params: {
          limit: options.limit ?? 20,
          ...(options.cursor ? { cursor: options.cursor } : {}),
        },
      },
    );
    return response.data;
  },
};
