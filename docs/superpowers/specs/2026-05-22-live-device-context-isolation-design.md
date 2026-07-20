# Live Device Context Isolation Design

## Goal

Realtime acquisition views must never mix data from different devices.

When the operator selects a device in the realtime device list:

- Device settings show the selected device profile.
- Realtime session state, overview, curves, events, and parameter monitoring show only data that belongs to that selected device.
- If the selected device has no active realtime data, realtime panels show an explicit empty state and zero counts instead of data from another device.

## Current Problem

The current implementation has two device concepts but does not keep their boundaries explicit:

- The frontend has a selected device id used by the device list and device editor.
- The backend acquisition service has one active session with one set of `_current_values`, `_history`, `_events`, and recorder state.

Realtime endpoints currently return the active service state without a strict selected-device projection. After the operator changes the selected device, some frontend views switch to the new device profile while realtime payloads can still belong to the previous active session. That creates mixed pages: new device settings next to old device status, curves, or parameters.

## Decision

Use a single active acquisition session with strict device-view isolation.

This version will not add parallel acquisition for multiple devices. The single-session model matches the existing backend service and keeps the first correction focused on correctness.

## Alternatives Considered

### Multi-device acquisition service

Each device would have its own poller, values cache, history, event queue, recorder, and export state. Every realtime endpoint would be keyed by `deviceId`.

This is the long-term option if the workbench must collect multiple devices at the same time. It is not selected now because it changes acquisition lifecycle, serial resource handling, export behavior, and API contracts together.

### Device switch automatically restarts acquisition

Clicking another device would stop the previous active session and start acquisition for the newly selected device.

This avoids mixed data but gives a navigation click a disruptive side effect. A wrong click would interrupt acquisition. It is not selected.

## Device Context Model

The realtime module must keep these contexts separate:

| Context | Meaning | Owner |
| --- | --- | --- |
| `selectedDeviceId` | Device the operator is inspecting and editing | frontend device view |
| `activeDeviceId` | Device currently owned by the single live acquisition session | backend acquisition service |
| `viewDeviceId` | Device id attached to each realtime payload rendered into the page | API response and frontend guard |

The frontend may render live data only when:

```text
selectedDeviceId == viewDeviceId == activeDeviceId
```

When the equality does not hold, device settings remain visible for the selected device, but all realtime payloads project to empty data.

## User-visible Behavior

### Device switch

Selecting a device:

1. Updates the device editor immediately.
2. Loads or derives realtime payloads for the selected context.
3. Shows active realtime data only when that device is the active acquisition device.
4. Clears status counters, overview values, events, curves, and parameter values when the selected device has no matching live data.

### Start acquisition

Starting acquisition from the selected device:

1. Uses the selected device profile.
2. Stops any existing single active session through the backend lifecycle.
3. Starts a fresh session for the selected device.
4. Replaces live caches and recorder state with data for that device only.

### Stop acquisition

Stopping acquisition leaves the selected device profile visible. The last active session state may remain available only when it still belongs to the selected device and the UI labels it as stopped. A different selected device still receives empty realtime panels.

### Device-scoped actions

The realtime toolbar actions are all scoped to the selected device only:

1. `liveStartBtn` controls only the currently selected device.
2. `liveStopBtn` stops only the currently active session for the currently selected device. If the selected device is not the active device, the UI must not present another device session as stoppable.
3. `liveRefreshBtn` refreshes the catalog and live projection for the selected device context. It must not repaint the page with another device session payload.
4. `liveExportBtn` exports only the current selected device session data, never all devices.
5. `liveAnalyzeBtn` exports and analyzes only the current selected device session data.

No toolbar action may operate on an implicit global device target.

### No data state

Empty realtime state must be explicit:

- Session state says the selected device is not currently collecting.
- Overview metrics show no values.
- Curve host shows no data for the selected device.
- Event and status sections show no rows.
- Parameter monitor shows no current values.

No panel may silently reuse another device payload.

## Backend Design

### Active session identity

`LiveAcquisitionService` remains the single active acquisition owner. Its status remains the source of truth for the active session device id.

### API contract

Realtime responses must carry device identity clearly:

- Session status returns `activeDeviceId`.
- Snapshot responses carry the active session device id for the snapshot.
- Series, events, parameters, and session meta either carry the active device id or are wrapped by the dashboard API with that id.
- Export and analyze responses carry the exported device id and device name.

Endpoints that are requested while the selected device does not match the active device should return a safe empty projection, or enough identity for the frontend guard to discard them. The preferred behavior is server-side empty projection because it prevents accidental misuse by future views.

Action endpoints must validate device scope:

- `start` uses the posted or selected device id and records it as the active session device.
- `stop` succeeds only for the active session device; otherwise it returns a selected-device mismatch response.
- `export` and `analyze` operate only on the active session that matches the selected device.

### Empty projection

The backend should expose helpers that build empty realtime payloads with:

- selected device id
- active device id
- `matchesSelectedDevice: false`
- empty rows, values, events, and parameter sections

This avoids repeating incompatible fallback shapes in each endpoint.

### Export layout

Realtime export artifacts must be stored by device name.

The export root remains shared, but each device writes into its own subdirectory, for example:

```text
real_time_data/
  live_exports/
    device_name/
      20260522_220135/
        config.json
        data_0/
        breath_data/
        run/
```

If two devices share the same display name, the backend should sanitize the name and append a stable disambiguator such as the device id. The device-scoped export path must be included in API responses so the frontend can present the exact exported location.

## Frontend Design

### State split

Realtime frontend state should separate:

- device catalog and selected device draft
- active session identity
- selected device live projection
- selected device action target identity used by start, stop, export, and analyze

The selected live projection owns the data rendered by:

- session summary
- realtime overview
- trend chart
- recent events
- parameter monitor

### Render guard

All realtime render functions read only from the selected live projection. They do not read a raw global service payload when device identity does not match.

### Switch flow

When a device item is clicked:

1. Set `selectedDeviceId`.
2. Replace the selected device draft from the profile.
3. Immediately reset the live projection to the empty model for that device.
4. Request fresh status and live projection data.
5. Render only responses whose device identity still matches the current selection.

The immediate reset prevents the old device from flashing while asynchronous requests complete.

### Action guard

Before invoking `start`, `stop`, `export`, or `analyze`, the frontend must resolve the target from the current `selectedDeviceId`.

- If the selected device is not the active device, `stop`, `export`, and `analyze` must show an explicit no-active-session message for that selected device.
- Success messages and exported paths shown in the UI must reference the selected device name, not a generic global session.

## Error Handling

- A deleted or missing selected device shows an empty device editor state.
- A stale response for a device that is no longer selected is ignored.
- Failure to refresh live data leaves the selected device editor intact and shows a realtime notice.
- Starting acquisition without a valid selected device returns a visible error and does not reuse the previous session view.
- Exporting or analyzing when the selected device is not the active session device returns a visible device mismatch notice.

## Tests

### Backend

Add tests for:

- Empty projection when selected device differs from active device.
- Matching projection when selected and active device match.
- Starting a new session resets values, history, events, and recorder identity.
- API responses include the identity fields needed by the view.
- Export and analyze reject device mismatch and return the selected and active device identities.
- Export paths are grouped by device name and disambiguated safely when needed.

### Frontend

Add focused coverage or browser verification for:

- Switching from active device A to inactive device B clears realtime cards, status, curve, events, and parameters.
- Device settings switch to B without starting B.
- Switching back to A restores the active A live projection.
- Stale async payloads cannot repaint a device after selection changes.
- Export and analyze from inactive device B do not export A.
- Toolbar success and failure notices name the correct selected device.

## Implementation Boundaries

The first implementation should touch only the live acquisition module:

- `dashboard_server.py`
- `live_acquisition_service.py`
- live-related tests
- `web/app.js`

The chart renderer should not need another display rewrite for device isolation. It should receive either matching series rows or an empty series projection.

## Deferred Work

- Parallel acquisition of multiple devices.
- Persisted historical browsing of old per-device sessions inside the realtime view.
- Cross-device comparison charts.
- Automatic acquisition restart on simple device selection.
