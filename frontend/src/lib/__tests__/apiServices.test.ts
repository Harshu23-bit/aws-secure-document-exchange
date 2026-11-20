import axios from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { documentService } from "../apiServices";
import type { DocumentUploadResponse } from "../../types/api";

describe("Document upload security", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("uploads directly to S3 without attaching a Cognito bearer token", async () => {
    const postSpy = vi.spyOn(axios, "post").mockResolvedValue({ data: "" });

    const upload: DocumentUploadResponse = {
      document_id: "document-123",
      upload_url: "https://storage.example/upload",
      upload_fields: {
        key: "tenant/document.pdf",
        policy: "test-policy",
        "x-amz-signature": "test-signature",
      },
      expires_in: 300,
    };

    const file = new File(["test PDF content"], "document.pdf", {
      type: "application/pdf",
    });

    await documentService.uploadToS3(upload, file);

    expect(postSpy).toHaveBeenCalledTimes(1);

    const [url, formData, config] = postSpy.mock.calls[0];

    expect(url).toBe(upload.upload_url);
    expect(formData).toBeInstanceOf(FormData);
    expect(config?.timeout).toBe(60000);

    expect(config?.headers?.Authorization).toBeUndefined();
    expect(config?.headers?.authorization).toBeUndefined();
  });

  it("includes the presigned upload fields and file in the form data", async () => {
    const postSpy = vi.spyOn(axios, "post").mockResolvedValue({ data: "" });

    const upload: DocumentUploadResponse = {
      document_id: "document-456",
      upload_url: "https://storage.example/upload",
      upload_fields: {
        key: "tenant/document.png",
        policy: "test-policy",
        "x-amz-signature": "test-signature",
      },
      expires_in: 300,
    };

    const file = new File(["image content"], "document.png", {
      type: "image/png",
    });

    await documentService.uploadToS3(upload, file);

    const formData = postSpy.mock.calls[0][1] as FormData;

    expect(formData.get("key")).toBe("tenant/document.png");
    expect(formData.get("policy")).toBe("test-policy");
    expect(formData.get("x-amz-signature")).toBe("test-signature");
    expect(formData.get("file")).toBe(file);
  });
});
