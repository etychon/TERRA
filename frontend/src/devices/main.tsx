import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { DevicesGrid } from "./DevicesGrid";
import "./devices-grid.css";

const mount = document.getElementById("terra-devices-grid-root");
if (mount) {
  const showOwner = mount.getAttribute("data-show-owner") === "true";
  createRoot(mount).render(
    <StrictMode>
      <DevicesGrid showOwner={showOwner} />
    </StrictMode>,
  );
}
