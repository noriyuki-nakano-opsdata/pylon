import { describe, it, expect } from "vitest";
import {
  formatDuration,
  formatElapsed,
  formatDate,
  formatDateTime,
  formatUptime,
  formatTimestamp,
  timeAgo,
} from "../time";

describe("formatDuration", () => {
  it("returns 0s for 0ms", () => {
    expect(formatDuration(0)).toBe("0s");
  });

  it("returns 5s for 5000ms", () => {
    expect(formatDuration(5000)).toBe("5s");
  });

  it("returns 1m 5s for 65000ms", () => {
    expect(formatDuration(65000)).toBe("1m 5s");
  });

  it("returns 60m 0s for 3600000ms", () => {
    expect(formatDuration(3600000)).toBe("60m 0s");
  });
});

describe("formatElapsed", () => {
  it("returns 0s for 0ms", () => {
    expect(formatElapsed(0)).toBe("0s");
  });

  it("returns 30s for 30000ms", () => {
    expect(formatElapsed(30000)).toBe("30s");
  });

  it("returns 1:30 for 90000ms", () => {
    expect(formatElapsed(90000)).toBe("1:30");
  });
});

describe("formatDate", () => {
  it("formats ISO string to YYYY/MM/DD", () => {
    expect(formatDate("2025-03-15T10:30:00Z")).toBe("2025/03/15");
  });

  it("pads single-digit month and day", () => {
    expect(formatDate("2025-01-05T00:00:00Z")).toBe("2025/01/05");
  });
});

describe("formatDateTime", () => {
  it("formats ISO string to YYYY/MM/DD HH:MM", () => {
    const result = formatDateTime("2025-06-15T09:05:00Z");
    // The output depends on local timezone, so check format pattern
    expect(result).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/);
  });
});

describe("formatUptime", () => {
  it("returns 0h 0m for 0 seconds", () => {
    expect(formatUptime(0)).toBe("0h 0m");
  });

  it("returns 1h 1m for 3661 seconds", () => {
    expect(formatUptime(3661)).toBe("1h 1m");
  });
});

describe("formatTimestamp", () => {
  it("formats ISO string to HH:MM:SS pattern", () => {
    const result = formatTimestamp("2025-03-15T10:30:45Z");
    // Locale-dependent, so just check pattern
    expect(result).toMatch(/\d{1,2}:\d{2}:\d{2}/);
  });

  it("returns 'Invalid Date' for invalid input", () => {
    // new Date("invalid") does not throw; toLocaleTimeString returns "Invalid Date"
    expect(formatTimestamp("invalid")).toBe("Invalid Date");
  });
});

describe("timeAgo", () => {
  it('returns "just now" for recent dates', () => {
    const now = new Date().toISOString();
    expect(timeAgo(now)).toBe("just now");
  });

  it('returns "Xh ago" for hours-old dates', () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
    expect(timeAgo(twoHoursAgo)).toBe("2h ago");
  });

  it('returns "Xd ago" for days-old dates', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString();
    expect(timeAgo(threeDaysAgo)).toBe("3d ago");
  });

  it('returns "Xmo ago" for months-old dates', () => {
    const sixtyDaysAgo = new Date(Date.now() - 60 * 24 * 3600 * 1000).toISOString();
    expect(timeAgo(sixtyDaysAgo)).toBe("2mo ago");
  });
});
