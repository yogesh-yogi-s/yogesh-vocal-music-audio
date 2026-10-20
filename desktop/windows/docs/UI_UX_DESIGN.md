# VMA Windows Desktop — UI/UX Design

## Design approach

Reuse `frontend/index.html`, `frontend/css/style.css`, and `frontend/js/app.js` as the visible application. The desktop shell adds only a native window, startup state, application title, and failure dialog. It must not create a second set of controls or duplicate workflow logic.

## Window

- Initial size about 1280 × 800 px, minimum about 900 × 650 px; resizable and centered.
- App title: `VMA — Vocal Music Audio`.
- Existing sidebar: Home, Create VMA, Open VMA, Inspect & Validate, Playback, Extract, Format Guide, Help / FAQ.
- Keep existing dark/light theme setting and responsive layout.
- Retain visible file names, duration/format summaries, upload progress text, validation badges, and error statuses.

## First launch

The window stays hidden while the backend initializes. On success it displays Home. If readiness fails, show one clear error with an option to close; no blank white page or endless spinner.

## Create and playback states

- Create remains disabled only while its request is active; success reveals the VMA download and next actions.
- Inspect communicates playable, partially playable, and non-playable stream states without implying that V2 `FORMAT_ID` guarantees codec support.
- Playback controls remain those already implemented in Web Audio, including seek preview and committed seek.
- Extract remains available for V2 even when playback cannot decode a stream.

## Accessibility

Preserve current semantic labels, keyboard navigation, visible focus, live status announcements, and color contrast. Desktop packaging must not suppress file chooser or download interactions.
