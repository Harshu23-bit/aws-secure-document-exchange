export type TenantRole = "SUBMITTER" | "REVIEWER" | "TENANT_ADMIN";

export type MemberRole = Exclude<TenantRole, "TENANT_ADMIN">;

export type MemberStatus = "ACTIVE" | "INACTIVE";

export type SubmissionStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "IN_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "NEEDS_CHANGES"
  | "CLOSED";

export type SubmissionActorRole = "SUBMITTER" | "REVIEWER";
export type TenantAdminActorRole = "TENANT_ADMIN";
export type MembershipRole = "SUBMITTER" | "REVIEWER";
export type MembershipStatus = "ACTIVE" | "INACTIVE";
export type DocumentStatus = "PENDING_UPLOAD" | "UPLOADED";

export type DocumentContentType =
  "application/pdf" | "image/jpeg" | "image/png";

export interface TenantMembership {
  tenant_id: string;
  role: TenantRole;
}

export interface TenantContext {
  tenant_id: string;
  user_id: string;
  role: TenantRole;
}

export interface TenantMember {
  user_id: string;
  tenant_id: string;
  role: TenantRole;
  status: MemberStatus;
  created_at: string | null;
}

export interface MembershipMutationResponse {
  user_id: string;
  tenant_id: string;
  role: MemberRole;
  status: MemberStatus;
  updated_at: string;
}

export interface ChangeMemberRoleRequest {
  expected_role: MemberRole;
  new_role: MemberRole;
}

export interface DeactivateMemberRequest {
  expected_role: MemberRole;
}

export interface SubmissionCreateRequest {
  title: string;
  description?: string | null;
}

export interface SubmissionListItem {
  tenant_id: string;
  submission_id: string;
  title: string;
  status: SubmissionStatus;
  created_at: string;
  updated_at: string;
  version: number;
  pending_document_count: number;
  uploaded_document_count: number;
}

export interface SubmissionResponse extends Omit<SubmissionListItem, "title"> {
  title: string | null;
  description: string | null;
}

export interface SubmissionListResponse {
  items: SubmissionListItem[];
  next_cursor: string | null;
}

export interface DocumentUploadRequest {
  filename: string;
  content_type: DocumentContentType;
  size_bytes: number;
}

export interface DocumentUploadResponse {
  document_id: string;
  upload_url: string;
  upload_fields: Record<string, string>;
  expires_in: number;
}

export interface DocumentResponse {
  document_id: string;
  submission_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
}

export interface DocumentListResponse {
  items: DocumentResponse[];
  next_cursor: string | null;
}

export interface DocumentDownloadResponse {
  document_id: string;
  download_url: string;
  expires_in: number;
}

export interface SubmissionTransitionRequest {
  target_status: SubmissionStatus;
  expected_version: number;
  reason?: string | null;
}

export interface SubmissionTransitionResponse {
  tenant_id: string;
  submission_id: string;
  previous_status: SubmissionStatus;
  status: SubmissionStatus;
  version: number;
  updated_at: string;
}

export interface AuditEvent {
  event_id: string;
  event_type: string;
  tenant_id: string;
  submission_id: string;
  actor_id: string;
  actor_role: string;
  previous_status: string;
  new_status: string;
  previous_version: number;
  new_version: number;
  timestamp: string;
  request_id: string;
  reason: string | null;
}

export interface AuditEventListResponse {
  items: AuditEvent[];
  next_cursor: string | null;
}

export interface TenantAuditEventBase {
  event_id: string;
  tenant_id: string;
  actor_id: string;
  actor_role: string;
  timestamp: string;
  request_id: string;
}

export interface TenantSubmissionAuditEvent extends TenantAuditEventBase {
  event_type: "SUBMISSION_STATUS_CHANGED";
  submission_id: string;
  previous_status: string;
  new_status: string;
  previous_version: number;
  new_version: number;
  reason: string | null;
}

export interface TenantMembershipRoleAuditEvent extends TenantAuditEventBase {
  event_type: "MEMBERSHIP_ROLE_CHANGED";
  target_user_id: string;
  previous_role: string;
  new_role: string;
}

export interface TenantMembershipDeactivationAuditEvent extends TenantAuditEventBase {
  event_type: "MEMBERSHIP_DEACTIVATED";
  target_user_id: string;
  previous_status: string;
  new_status: string;
}

export type TenantAuditEvent =
  | TenantSubmissionAuditEvent
  | TenantMembershipRoleAuditEvent
  | TenantMembershipDeactivationAuditEvent;

export interface TenantAuditEventListResponse {
  items: TenantAuditEvent[];
  next_cursor: string | null;
}

export interface PaginatedRequest {
  limit?: number;
  cursor?: string | null;
}
