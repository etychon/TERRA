import { describe, expect, it } from "vitest";

import { COLUMN_META, SORTABLE_COLUMN_IDS } from "./columnMeta";

describe("columnMeta", () => {
  it("has stable unique column ids", () => {
    const ids = COLUMN_META.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("includes cellular and hostname as sortable", () => {
    expect(SORTABLE_COLUMN_IDS.has("hostname")).toBe(true);
    expect(SORTABLE_COLUMN_IDS.has("cellular")).toBe(false);
  });
});
