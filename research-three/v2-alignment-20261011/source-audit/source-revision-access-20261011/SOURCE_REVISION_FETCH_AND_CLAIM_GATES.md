# Public source revision check: access handoff and evidence gates

**Date:** 2026-10-11 UTC  
**Status:** Candidate review and parent fetch request. No actual NWS CAP event payload was obtained in this environment, so no real-message trial is claimed.

## Decision in brief

The current repo inventory contains useful public or request-access industrial datasets, but none presently offers a versioned alarm-message stream suitable for testing Alert → Update → Cancel on one message chain:

| Candidate | Access and evidence from existing inventory/current official page | Best claim it could support | Why it is not the current revision trial |
|---|---|---|---|
| MIMII (Zenodo 3384388) | Public download, CC BY-SA 4.0. The current Zenodo record describes normal and anomalous machine recordings across valves, pumps, fans, and slide rails; its present file listing totals 100.2 GB. The repository inventory's earlier ~68 GB estimate is stale. | A limited acoustic-observation / anomaly-input prototype, after choosing a small licensed subset. | Individual sound recordings are not an alert revision or delivery log. The record does not expose an Alert/Update/Cancel history, message receipt, or user-visible card chronology. Do not download the multi-GB bundles for this revision question. |
| SWaT / iTrust testbeds | SUTD says testbed data are available without charge after a request (up to three working days). Terms require attribution and prohibit sharing the dataset; access is not anonymous direct download. | A later sensor-state / attack progression prototype after an authorized request, with source-only custody. | Not currently accessible to this read-only audit; it is not a public redistribution source, and the published dataset page does not provide message-version chains. |
| Tennessee Eastman Process (TEP) | The repo inventory lists a CC0 process-simulation dataset (Harvard Dataverse DOI `10.7910/DVN/6C3JR1`; ~1.8 GB, not locally present). | A simulation-only evolving-process state/card update demonstration, if a small trace is obtained. | Simulated process traces and fault labels are not real plant event messages, notice revisions, user delivery, or industrial safety outcomes. Harvard Dataverse's live page was blocked by its JavaScript anti-bot interstitial in this environment. |
| NWS CAP alerts | NWS documents CAP v1.2 products, JSON-LD/ATOM indexes and original CAP retrieval. OASIS CAP defines `Update` and `Cancel` as acting on the earlier message(s) named in `<references>`. | The strongest available candidate for a narrowly scoped message-revision/card-history test. | This environment could read the documentation but not the live API response or CAP Atom feed. This is an access-path limit, not evidence the NWS service is down. It is a public-alert lifecycle proxy, not industrial safety evidence. |

The official USGS sample audited in the preceding note remains a schema/time-field example only. It is not evidence of industrial hazards or their safety consequences.

## Parent fetch request: exact public URLs

Please inspect these through the ordinary web channel and return one complete CAP revision series if available:

1. Updates: <https://api.weather.gov/alerts?status=actual&message_type=Update&limit=10>
2. Cancellations: <https://api.weather.gov/alerts?status=actual&message_type=Cancel&limit=10>
3. Unfiltered actual alerts fallback: <https://api.weather.gov/alerts?status=actual&limit=100>
4. API specification (the browser connector could not parse its vendor OpenAPI content type): <https://api.weather.gov/openapi.json>
5. NWS Atom CAP feed (this connector returned HTTP 502): <https://alerts.weather.gov/cap/us.php?x=0>
6. User-provided NWS cache directory: <https://tgftp.nws.noaa.gov/SL.us008001/DF.xml/DC.cap/>
7. User-provided Cancel XML: <https://tgftp.nws.noaa.gov/SL.us008001/DF.xml/DC.cap/T_XOAK51_C_KWBC_20261001142454_urn:oid:2.49.0.1.840.0.0142b0389798c01d5bb5f28f9aa7320092c5196d.001.1-O-CAN-PAFC-FG-Y-0013.xml>
8. User-provided NEW XML: <https://tgftp.nws.noaa.gov/SL.us008001/DF.xml/DC.cap/T_XOAK51_C_KWBC_20261001064420_urn:oid:2.49.0.1.840.0.0fad6b84fb446e26e7fd80e35cd6ee85cda474d5.001.1-O-NEW-PAFC-FG-Y-0013.xml>

NWS documentation says the API has JSON-LD defaults, supports CAP v1.2 via content negotiation, requires an identifying `User-Agent` for application requests, and asks clients not to request more often than every 30 seconds. A direct CAP request should use `Accept: application/cap+xml`; do not poll in a loop.

### Exact response requested

For one event-message series, return:

- The complete JSON-LD feature(s) for the `Alert`, each `Update`, and, if present, `Cancel` message. Preserve the original response body and URL.
- The corresponding complete CAP v1.2 XML for the newest `Update` or `Cancel` and every predecessor its `<references>` names (at minimum one original `Alert` plus one `Update`/`Cancel`). Preserve `identifier`, `sender`, `sent`, `status`, `msgType`, `references`, `source`, `scope`, and all `info` fields, especially `event`, `severity`, `urgency`, `certainty`, `headline`, `description`, `effective`, `onset`, `expires`, `ends`, and `area`.
- For each exact body, the fetched URL and available response headers (`Date`, `ETag`, `Last-Modified`, content type). If the ordinary web interface gives a local observation time, record it; otherwise leave local receive time unknown. Do not infer client receipt from CAP `sent` or HTTP `Date`.
- If raw body export is available, keep its SHA-256 alongside the bytes. If the ordinary web interface only returns rendered content, say so; do not reconstruct or hash a made-up body.

The API query endpoint may return no item for one filter. If so, return the unfiltered response and select a feature whose source-provided `messageType` is `Update` or `Cancel`; do not infer a revision from separate IDs alone.

## What a real series can and cannot validate

NWS documentation says its alert API provides CAP v1.2 products and indexes, and its Atom index is intended to track active messages. The NWS change log says the `<references>` field includes earlier messages in a series, except Flood Warnings, which reference only the previous message. The OASIS CAP v1.2 standard defines `Update` as superseding referenced earlier messages and `Cancel` as cancelling referenced earlier messages. These support a source-declared **message-series** relation; they do not prove transport receipt, independent acquisition, or physical-world identity.

| Claim | Minimum evidence to start/validate | Required conclusion limit |
|---|---|---|
| Stable display card with version history | One authentic CAP `Alert` plus a CAP `Update` whose `references` names the earlier identifier/sender/sent; preserve both complete records. | Validate only that the adapter can keep one display thread and append a revision for this source-declared message chain. No two-sided receipt is required. This is not UI rendering or delivery validation. |
| Exact replay deduplication | The exact same frozen message bytes/identifier processed twice, with a saved content digest. | If the source did not itself deliver a duplicate, the second input is a code-level replay probe, not an observed duplicate-delivery rate. Keep the immutable source message ID and display-card ID distinct. |
| Risk severity update | An authentic Update whose published `severity`, `urgency`, or relevant `info` changes relative to the prior message. | Validate deterministic field-to-card revision mapping only. Do not infer that NWS severity is an industrial hazard threshold or that the alert is calibrated for workplace risk. |
| Cancel/retract state | An authentic CAP `Cancel` with `references` to a prior message. | Validate that current card state can become `CANCELLED`/`RETRACTED` while the prior revision remains auditable. A CAP cancellation is not evidence the physical hazard ended or that all recipients received the cancellation. |
| Arrival ordering and first-alert timeliness | A receiver/client capture time for each body (or append-only receipt log) plus the CAP `sent` field. | Without receiver-side time, latency and “immediate” first-alert claims stay `UNKNOWN`. Message `sent` is not client arrival. |
| Source independence / acquisition lineage | Distinct, attributable acquisition paths with retained boundary receipts or equivalent verifiable logs; source identity and scope must be reviewed. | If unavailable, retain `UNKNOWN`. CAP references establish the issuing authority's declared message chain, not independence among evidence sources. Repeated CAP versions are one source family, never multiple corroborating sources. |
| Event identity accuracy | Independent, qualified adjudication for same/different physical events, kept separate from method-visible messages, plus a fixed eligible denominator. | No labels are inferred from `identifier`, references, title, or matching severity. If unavailable, mark `NOT_SCORED_UNIDENTIFIABLE`. |
| Industrial safety effect | Authorized industrial records with reviewed hazard semantics and outcomes, qualified safety review, and an appropriate comparison design. | NWS weather warnings, USGS earthquake catalog metadata, MIMII acoustic anomaly labels, and TEP simulation cannot establish industrial workplace safety effectiveness. |

This separation explicitly permits a card-history/replay/escalation prototype to proceed without two-sided source receipts. Only the claims in the lineage and timeliness rows require those extra records.

## Strict read-only mini-trial if the series is returned

1. Freeze the exact public URLs and response bodies; record hashes only for exact bytes supplied by the source or browser export.
2. Parse CAP identifiers, `sent`, `msgType`, and `<references>` without adding inferred event identity or source-family labels.
3. Build a timeline ordered by source `sent`; mark any equal/missing/contradictory ordering as unresolved rather than repairing it.
4. Feed `Alert`, `Update`, and `Cancel` to the existing pure-software event-card/notification preview path: keep display-card ID stable for the explicit message series, append revisions, dedupe only exact same-message replay, apply only the source-provided urgency/severity changes, and preserve Cancel as a terminal/current-state update plus full history.
5. Keep action-emission and user-delivery times `NOT_DELIVERED`/unknown unless separately observed. Keep source independence and physical event identity `UNKNOWN`.
6. Report per-claim pass/unknown/fail; do not compute industrial safety efficacy or event-identity accuracy from this single message series.

This is a single-series mechanism check, not an efficacy experiment and not an independent sample-count claim. It does not run the frozen 1,464-check trial, the old Mac test, a model, or a real notification.

## Retrieval attempts and references

- `https://api.weather.gov/alerts?status=actual&message_type=Update&limit=5`: browser tool returned “URL … is not accessible via this tool.”
- `https://api.weather.gov/openapi.json`: the official API-spec link returned “Unsupported content-type: application/vnd.oai.openapi+json” in the browser connector.
- `https://alerts.weather.gov/cap/us.php?x=0`: browser tool returned HTTP 502 Bad Gateway.
- The two user-supplied `tgftp.nws.noaa.gov` XML URLs were each requested once with ordinary HTTPS/curl, no login, no elevated permissions, and 37 seconds between request starts. Both failed before reaching a confirmed origin response: `curl: (56) CONNECT tunnel failed, response 403`, curl HTTP status `000`, download size `0` bytes. The proxy response headers were `HTTP/1.1 403 Forbidden`, `content-length: 16`, `content-type: text/plain`, `server: envoy`, and a `Date` header matching each attempt. Exact local UTC times, timings, URLs, and response headers are saved in [`NWS_CAP_FETCH_ATTEMPT_RESULTS.json`](NWS_CAP_FETCH_ATTEMPT_RESULTS.json).
- No CAP XML bytes or CAP hash were obtained. No `references` parse was performed, and the matching filename token was not treated as proof of an event-message relation. No retry was made. The 403 came from this environment's CONNECT tunnel; it does not establish source outage or lack of NWS Update/Cancel records.

Official references:

- [NWS Alerts Web Service](https://www.weather.gov/documentation/services-web-alerts)
- [NWS API Web Service](https://www.weather.gov/documentation/services-web-api)
- [OASIS Common Alerting Protocol v1.2](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.pdf)
- [MIMII Zenodo record and CC BY-SA 4.0 terms](https://zenodo.org/records/3384388)
- [iTrust datasets](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/) and [dataset terms](https://www.sutd.edu.sg/itrust/itrust-labs/datasets/terms-of-usage/)
- Local inventory for previously scoped TEP/SWaT/MIMII candidates: [`研究方向调研-G1-G8/dataset.md`](../../../../研究方向调研-G1-G8/dataset.md)
