import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiFetch, ApiError } from "../client";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns JSON for a 200 response", async () => {
    const mockData = { id: 1, name: "test" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(mockData),
      }),
    );

    const result = await apiFetch("/test");
    expect(result).toEqual(mockData);
  });

  it("returns undefined for a 204 response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        json: () => Promise.resolve(null),
      }),
    );

    const result = await apiFetch("/test");
    expect(result).toBeUndefined();
  });

  it("throws ApiError for a 4xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: () => Promise.resolve({ message: "Not found" }),
      }),
    );

    await expect(apiFetch("/test")).rejects.toThrow(ApiError);
    try {
      await apiFetch("/test");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).message).toBe("Not found");
    }
  });

  it("throws ApiError with fallback message when response body has no message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve(null),
      }),
    );

    await expect(apiFetch("/test")).rejects.toThrow("Request failed: 500");
  });
});
