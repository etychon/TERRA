import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { EventsGrid } from "./EventsGrid";
import "../devices/devices-grid.css";
import "./events-grid.css";

const mount = document.getElementById("terra-events-grid-root");
if (mount) {
  createRoot(mount).render(
    <StrictMode>
      <EventsGrid />
    </StrictMode>,
  );
}
