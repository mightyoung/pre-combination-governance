# USGS real public-feed sample: observability audit

**Status:** Read-only field audit of one real public feed row. No lineage prototype or event association experiment was run.

## Sample observed

The official USGS “all earthquakes past day” GeoJSON response exposed `metadata.generated = 1791762287000` (2026-10-11T23:44:47.000Z), `metadata.count = 178`, and API version `2.7.0`. One observed feature was `ci41346535`:

| Field | Observed value | What it supports |
|---|---|---|
| `properties.time` | `1791754093930` = 2026-10-11T21:28:13.930Z | Event-origin time as published by the catalog |
| `properties.updated` | `1791758365040` = 2026-10-11T22:39:25.040Z | Catalog record update time |
| `metadata.generated` | `1791762287000` = 2026-10-11T23:44:47.000Z | Feed generation time |
| `properties.net` / `code` | `ci` / `41346535` | The catalog’s preferred network and event code |
| `id` | `ci41346535` | Feed feature identifier |
| `properties.ids` | `,ci41346535,us6000u1mg,` | Catalog-listed identifiers for this event record |
| `properties.sources` | `,ci,us,` | Catalog-listed source labels |
| `properties.types` | `,nearby-cities,origin,phase-data,scitech-link,` | Product/data-type labels present in this record |
| `properties.detail` | `https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/ci41346535.geojson` | Link to the event detail representation, not evidence that it was retrieved here |

A standalone normalized copy of only these observed values is in `REAL_PUBLIC_FEED_SAMPLE.json`. It is marked as real public-source data, not synthetic. The SVG is an explanatory field map, not a reconstruction of a delivery trace.

## Observability decision

This row is sufficient for a small **read-only schema and field audit**. It is insufficient for a source-lineage or event-association prototype:

- `time` is the catalog’s event-origin time; this sample contains no local sensor acquisition time or receiver/collector `received_at`.
- `updated` and `metadata.generated` are catalog/feed timestamps. They do not identify when a particular consumer received the bytes.
- `ids` and `sources` are lists on one catalog feature. They do not expose directional parent→child receipts, forwarding hops, queue offsets, or proof of two independent acquisition paths. Different IDs or source labels must not be treated as independent evidence.
- `detail` points to a richer representation, but the linked response and its per-product rows were not retrieved in this session. The schema says that detail representations can expose `products` and product metadata; that potential is not evidence about this row’s actual product records.
- The browser-rendered result did not provide raw response bytes, HTTP receipt time/headers, or a response-body digest. The audit stores those values as unknown instead of fabricating them.

The sample therefore supports chronology labels only. In the diagram, the line between time markers means “ordered timestamps shown together”; it does not represent data transfer or causation.

## Retrieval and failure record

The feed row was observed through the browser-rendered official USGS feed on 2026-10-11 UTC. The rendered content exposed the values above, but not an exact local capture instant or raw bytes. A direct shell request to the USGS detail endpoint failed at the current environment’s network tunnel with `Tunnel connection failed: 403 Forbidden`; the browser tool also reported the detail URL as inaccessible. This is an access-path limitation, not a claim that the USGS endpoint is down.

The official NWS API documentation identifies CAP alerts and their `references` field as a promising explicit message-update chain. However, an actual CAP payload was not obtained in this session: browser access failed (including a 502 response on a CAP endpoint), and direct shell requests hit the same environment tunnel 403. Thus NWS remains a candidate for a later sample, not an audited dataset here.

No raw payload was copied or published. The normalized sample contains only one public-domain feed feature and its source-provided timestamps/metadata. USGS states that its authored or produced data and information are U.S. public domain and requests attribution.

## Next bounded observation

Obtain one locally saved USGS detail JSON or NWS CAP message, with the collector’s actual UTC receipt time and a SHA-256 over the exact saved bytes when available. Preserve the source URL, retrieval time, response headers where available, and any native message/product references. A real source-declared message revision (for example, CAP `Update`/`Cancel` plus its `<references>` chain) is enough to start a narrow read-only card-version, exact-replay, and risk-field mapping prototype. If receiver time is missing, delivery latency remains `UNKNOWN`; if two-sided hop records are missing, transport lineage and source independence remain `UNKNOWN`. Those missing receipts do not block the card lifecycle prototype.

Before making stronger claims, answer:

1. For message-version history, does the source expose stable native message IDs and an explicit revision/reference relation? For byte-exact replay deduplication, are the original bytes or a source-supported digest available?
2. For receipt/latency claims, is there a client-side receive timestamp? For verified transport lineage/independence, are there attributed sender/receiver/broker receipts with timestamps and cursor/offset?
3. What bounded export window or sequence range supports a completeness claim? This is required for completeness, not for a bounded one-series card-version prototype.
4. What independent evidence adjudicates same-event versus different-event status? If unavailable, retain `NOT_SCORED_UNIDENTIFIABLE` while continuing non-identity card lifecycle work.

The existing four-case minimum and scorer-sidecar separation in [`SOURCE_LINEAGE_ACQUISITION_OBSERVABILITY_NOTE.md`](../../SOURCE_LINEAGE_ACQUISITION_OBSERVABILITY_NOTE.md) remain the gate for a future distinguishability study. This audit does not revise prior synthetic metrics, the recorded 1,464-check failure, or any historical Mac status.

## Source references

- [USGS GeoJSON Summary Format](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)
- [USGS past-day GeoJSON feed](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson)
- [USGS GeoJSON Detail Format](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson_detail.php)
- [USGS Copyrights and Credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)
- [NWS API Web Service](https://www.weather.gov/documentation/services-web-api)
- [NWS Alerts Web Service](https://www.weather.gov/documentation/services-web-alerts)
