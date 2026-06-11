# URL Router

<p align="center">
  <img src="icon.png" width="96" alt="URL Router icon"/>
</p>
<p align="center">
  A lightweight Windows app that intercepts links and routes them to the right browser automatically.
</p>
<p align="center">
There's an [android app](https://github.com/vdb86/urlrouter) as well.
</p>

Route every link opened on Windows to the right browser automatically —
based on configurable rules, with a floating chooser popup as fallback.

Portable, no installer, no telemetry, entirely local.

### Instant by design

URL Router lives in the system tray and stays warm. Many similar tools spawn a
fresh process for every link — taking several seconds to start up and show a
window before they can route anything. URL Router doesn't: the running tray
instance handles each link the moment it arrives, so routing and the chooser
popup appear **instantly**, with no cold-start delay.

This is also why the app is built in PyInstaller onedir mode rather than a
single .exe (see the build note below) — onefile would re-extract its archive
on every launch and reintroduce exactly the lag this design avoids.

---

## Quick start

### Prerequisites
- Windows 10 or 11
- Python 3.11+ (only needed to build; the final app has no runtime dependency)

### Build the portable app

```bat
build.bat
```

This installs `PyQt6`, `pywin32`, and `pyinstaller`, then produces a
self-contained folder:

```
dist\URLRouter\
   URLRouter.exe
   _internal\        (bundled Python runtime + Qt — do not separate)
```

Copy the **whole `dist\URLRouter\` folder** anywhere you like (Desktop,
`C:\Tools\`, a USB stick, etc.) and run `URLRouter.exe` inside it.
On first run it writes `config.json` next to the exe — keep it with the folder.

> **Note on the build layout:** the app is built in PyInstaller **onedir**
> mode (a folder), not a single .exe. This is deliberate — onefile mode
> re-extracts the whole archive to a temp directory on *every* launch, which
> added a multi-second delay before the window appeared. Onedir launches
> near-instantly. The trade-off is that `URLRouter.exe` must stay inside its
> `URLRouter\` folder alongside `_internal\`.

> **If you move the folder:** because Windows registers the default browser
> by absolute path, re-confirm URL Router as the default (Settings → General)
> after relocating it.

---

## First-time setup

1. **Run** `URLRouter.exe` — a small icon appears in the system tray.
2. **Right-click the tray icon → Open Settings**.
3. Go to the **Browsers** tab and confirm your browsers were discovered.
4. Go to the **General** tab and click **"Open Windows Default Apps Settings →"**.
5. In Windows Settings, choose **URL Router** as the default browser for HTTP and HTTPS.

From that point on every link opened system-wide — from Slack, Teams, Outlook,
the Start menu, anywhere — is intercepted by URL Router and routed by your rules.

---

## How routing works

When a link is opened, URL Router decides where it goes in this order:

1. **Matching rule** → opens in the rule's browser.
2. **Default fallback browser** (if you set one) → opens there directly.
3. **Otherwise** → shows the chooser popup so you can pick.

### Routing rules

Rules are evaluated top to bottom; the first match wins:

| Priority | Type | Example pattern |
|---|---|---|
| 1 | Exact hostname | `google.com` |
| 2 | Wildcard hostname | `*.youtube.com` |
| 3 | URL prefix | `https://youtube.com/watch` |
| 4 | Contains | `reddit` |
| 5 | Regex | `.*github\.com\/.*issues.*` |

Add, edit, reorder, and delete rules in **Settings → Rules**.

**Quick rule from the chooser:** when the chooser popup appears, press-and-hold
a browser button for ~0.6 s. URL Router silently creates an *exact hostname*
rule for that site and browser, then opens the URL. A small toast confirms it.

---

## The chooser popup

Appears when no rule matches and no default fallback is set.

- Opens on **the monitor where the cursor currently is**.
- Shows the full URL at the top. Click the **pencil** to edit it in place
  before opening; click the **clipboard** icon to copy it.
- The URL field wraps long links and grows up to ~4 lines, scrolling beyond that.
- **Browser buttons** are laid out either horizontally (icon on top, name below)
  or vertically (icon left, name right) — your choice in Appearance.
- **Private / incognito buttons:** any browser you mark as "Private" (Browsers
  tab) gets a second, purple-tinted button with an incognito badge. In
  horizontal layout it sits directly **beneath** the normal button; in vertical
  layout it sits in a **second column** to the right. Clicking it launches that
  browser in private mode (`--incognito`, `--inprivate`, or `--private-window`
  depending on the browser).
- **Escape** or **clicking outside** the popup dismisses it without opening anything.
- **Hold** a browser button (~0.6 s) → creates a rule + opens the URL + toast.

---

## Settings tabs

| Tab | What you can do |
|---|---|
| **Browsers** | Enable/disable browsers, mark browsers for a **Private** button, set display order, designate a default fallback, rescan for newly installed browsers, edit display names inline |
| **Rules** | Add · Edit · Delete · Reorder routing rules |
| **Appearance** | Chooser position, background colour & opacity, corner radius, padding, icon size, label font size, URL font size, layout (horizontal/vertical), show/hide icons & names — all with a **live preview** beside the controls |
| **General** | Launch on startup, open Windows Default Apps settings |
| **Import / Export** | Export config to JSON, import from JSON, reset appearance & rules to defaults |
| **Diagnostics** | Paste any URL and see exactly which rule would match and which browser would open it |

### Live appearance preview

The Appearance tab shows a **real-time preview** of the actual chooser popup
on the right side of the tab (not a mock-up). It renders a genuine chooser
using your real browsers, icons, colours, and layout, and updates instantly as
you drag any slider or toggle any option — including changes made on the
Browsers tab (enabling a browser, toggling Private). The controls scroll
independently on the left while the preview stays pinned in view.

### Appearance options explained

- **Padding** controls both the margin between the buttons and the popup edge,
  *and* the spacing between buttons.
- **Label font size** sizes the browser names; **URL font size** is independent
  and sizes the URL field text.
- **Popup width** can be a fixed pixel value, or `0` for **auto** — the popup
  sizes itself to fit the browser buttons (accounting for private columns/rows).
- Each browser button sizes to fit whichever is larger, its icon or its name.

---

## Technical notes

| Topic | Detail |
|---|---|
| Stack | Python 3.11 + PyQt6, packaged with PyInstaller (onedir) |
| Registry | Writes to `HKCU` only — no administrator rights required |
| Single instance | Windows named mutex; a second launch forwards the URL to the running instance over a named pipe, then exits |
| Config | `config.json` next to the exe — plain JSON, human-editable |
| Startup | Optional `HKCU\...\Run` entry, toggleable in Settings → General |
| App icon | Loads `icon.png` next to the exe if present, else a generated icon; the exe itself is built with `icon.ico` |
| Telemetry | None. Entirely local. |
| Installer | None. Portable folder. |

### Project structure

| File | Role |
|---|---|
| `main.py` | Entry point: single-instance gate, DPI awareness, Qt bootstrap |
| `app.py` | Core app: owns config, IPC server, tray, chooser, settings; routing & browser launching |
| `config.py` | JSON config load/save and defaults |
| `ipc.py` | Qt-free client side: mutex + send URL to existing instance |
| `ipc_server.py` | Qt IPC server (first instance only) |
| `registry.py` | Browser discovery, HKCU registration, startup key, Default Apps launcher |
| `router.py` | Rule engine + diagnostics |
| `browser_utils.py` | Browser icon extraction, app icon |
| `theme.py` | Light/dark Qt stylesheets |
| `tray.py` | System tray icon + menu |
| `chooser.py` | Floating chooser popup (URL field, browser/private buttons) |
| `settings_window.py` | Six-tab settings UI + live preview |
| `toast.py` | Corner fade notification |
| `URLRouter.spec` | PyInstaller build spec (onedir) |
| `build.bat` | One-command build script |
| `requirements.txt` | Build/runtime Python dependencies |
| `icon.png`, `icon.ico` | App icons |

---

## Uninstall

1. Exit URL Router (tray → Exit).
2. Open **Windows Default Apps Settings** and choose a different default browser.
3. Delete the `URLRouter\` folder (which contains `URLRouter.exe`, `_internal\`,
   and `config.json`).

Registry entries under `HKCU\Software\Classes\URLRouterHTML` and
`HKCU\Software\Clients\StartMenuInternet\URLRouter` can be removed with
`regedit` if desired, but Windows stops routing to them automatically once a
new default browser is set. If you enabled "Launch on startup", also remove the
`URLRouter` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
(or just toggle it off in Settings before uninstalling).
