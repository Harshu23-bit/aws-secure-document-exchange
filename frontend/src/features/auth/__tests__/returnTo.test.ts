import { beforeEach, describe, expect, it } from "vitest";

import {
  consumeReturnTo,
  getSafeReturnPath,
  saveReturnTo,
} from "../returnTo";

describe("returnTo", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  describe("getSafeReturnPath", () => {
    it("accepts a valid internal path", () => {
      expect(getSafeReturnPath("/submissions/123")).toBe(
        "/submissions/123",
      );
    });

    it("preserves query parameters and fragments", () => {
      expect(
        getSafeReturnPath("/submissions/123?tab=history#documents"),
      ).toBe("/submissions/123?tab=history#documents");
    });

    it("rejects external URLs", () => {
      expect(
        getSafeReturnPath("https://evil.example"),
      ).toBeNull();
    });

    it("rejects protocol-relative URLs", () => {
      expect(getSafeReturnPath("//evil.example")).toBeNull();
    });

    it("rejects paths containing backslashes", () => {
      expect(getSafeReturnPath("/\\evil.example")).toBeNull();
    });

    it("rejects control characters", () => {
      expect(getSafeReturnPath("/submissions/\n123")).toBeNull();
    });

    it("rejects non-string values", () => {
      expect(getSafeReturnPath(null)).toBeNull();
      expect(getSafeReturnPath(undefined)).toBeNull();
      expect(getSafeReturnPath(123)).toBeNull();
    });
  });

  describe("saveReturnTo and consumeReturnTo", () => {
    it("saves and consumes a valid internal path", () => {
      saveReturnTo("/submissions/123");

      expect(consumeReturnTo()).toBe("/submissions/123");
    });

    it("removes the saved destination after consumption", () => {
      saveReturnTo("/submissions/123");

      consumeReturnTo();

      expect(sessionStorage.length).toBe(0);
      expect(consumeReturnTo()).toBe("/");
    });

    it("does not save an unsafe destination", () => {
      saveReturnTo("https://evil.example");

      expect(sessionStorage.length).toBe(0);
      expect(consumeReturnTo()).toBe("/");
    });

    it("validates the destination again when consuming it", () => {
      sessionStorage.setItem(
        "cloudsecure.auth.returnTo",
        "//evil.example",
      );

      expect(consumeReturnTo()).toBe("/");
      expect(sessionStorage.length).toBe(0);
    });

    it("defaults to the dashboard when no destination exists", () => {
      expect(consumeReturnTo()).toBe("/");
    });
  });
});
