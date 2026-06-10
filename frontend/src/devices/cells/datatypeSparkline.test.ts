import { describe, expect, it } from "vitest";

import { datatypeSparklineExpression, rssiToSparkHeight } from "./datatypeSparkline";

describe("datatypeSparkline", () => {
  it("maps RSSI endpoints to 0 and 100", () => {
    expect(rssiToSparkHeight(-120)).toBe(0);
    expect(rssiToSparkHeight(-50)).toBe(100);
  });

  it("builds Datatype sparkline syntax", () => {
    expect(datatypeSparklineExpression([{ v: -120 }, { v: -50 }])).toBe("{l:0,100}");
  });

  it("returns null when no points", () => {
    expect(datatypeSparklineExpression([])).toBeNull();
  });
});
