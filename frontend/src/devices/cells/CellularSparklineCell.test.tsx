import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CellularSparklineCell } from "./CellularSparklineCell";

describe("CellularSparklineCell", () => {
  it("shows dash when not cellular", () => {
    render(<CellularSparklineCell hasCellular={false} item={undefined} />);
    expect(screen.getByText("—")).toBeTruthy();
  });

  it("shows quality dot and Datatype sparkline when data present", () => {
    render(
      <CellularSparklineCell
        hasCellular
        item={{
          device_id: 1,
          has_cellular: true,
          points: [{ t: 1, v: -70 }],
          latest_rssi: -70,
          quality: "good",
        }}
      />,
    );
    expect(screen.getByLabelText(/RSSI -70 dBm/)).toBeTruthy();
    expect(screen.getByText("{l:71}")).toBeTruthy();
  });
});
