# Domain concepts (TERRA)

## Core nouns

- **Cluster:** an SD-WAN Manager domain the dashboard monitors (exact mapping to “tenant” / “provider” language TBD).
- **Device (cEdge):** routed appliance under management; primary telemetry subject.
- **Asset / Bus_ID:** customer-owned identifier for rolling stock or field asset correlation (display + search + reports).
- **Uplink profile:** especially **single cellular SIM** scenarios (IR1800 on buses); UI must not assume dual-transport diversity.
- **Release posture:** IOS-XE / image version compared to an operator policy (**out of date** / **unsupported** / **security exception**).

## User journeys (MVP bias)

1. **Morning check:** fleet health, red/yellow/green, version outliers, SIM-heavy sites.
2. **Incident:** drill into **cellular** stats, recent **events**, **alerts**, last known **GPS**.
3. **Compliance / audit:** who acknowledged what, export for operations review.

## Reporting

- **GPS history:** sample every few minutes where device/API allows; retain roughly **one day** of rolling history for operational map playback (exact retention in implementation spec later).
- **Events / alerts:** must be explainable in plain language for non-experts.

## Non-domain (explicit)

- Full SD-WAN **control-plane configuration** education is not a goal.

Update this file when customer language (e.g., Bus_ID rules) stabilizes.
