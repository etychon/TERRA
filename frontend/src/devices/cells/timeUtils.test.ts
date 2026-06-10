import { describe, expect, it } from "vitest";

import { formatSince } from "./timeUtils";

describe("formatSince", () => {
  it("labels reachable devices as Online", () => {
    const iso = new Date(Date.now() - 120_000).toISOString();
    expect(formatSince(iso, "reachable")).toMatch(/^Online · /);
  });

  it("returns dash for empty iso", () => {
    expect(formatSince("", "reachable")).toBe("—");
  });
});
