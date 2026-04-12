# Chrome Extension Setup

Claw-STU ships a Manifest V3 Chrome extension in the `extension/` directory
that lets students interact with Stuart from any web page.

## Loading the Extension

1. Open `chrome://extensions` in Chrome or any Chromium-based browser.
2. Enable **Developer mode** (toggle in the top-right corner).
3. Click **Load unpacked** and select the `extension/` directory from
   this repository.
4. The Claw-STU icon should appear in your toolbar.

## Configuring the Server URL

The extension defaults to `http://localhost:8000`. To change it:

1. Click the Claw-STU extension icon in the toolbar.
2. In the popup, enter the server URL (e.g. `https://stu.example.com`).
3. Click **Save**.

The URL is persisted in `chrome.storage.local` and survives browser restarts.

## Setting the Auth Token

When the server runs in `enforce` or `generate` auth mode, every request
must carry a Bearer token.

1. Obtain a token from the server (see `docs/CONFIG_RESOLUTION.md` for
   auth mode details).
2. Open the extension popup and paste the token into the **Auth Token**
   field.
3. Click **Save**. The token is stored in `chrome.storage.local` and sent
   as an `Authorization: Bearer <token>` header on every API call.

## Required Permissions

The extension declares four permissions in `manifest.json`:

| Permission       | Why                                                       |
|------------------|-----------------------------------------------------------|
| `contextMenus`   | Right-click menu items (e.g. "Ask Stuart about this")    |
| `activeTab`      | Read selected text on the current page when invoked       |
| `storage`        | Persist server URL and auth token across sessions         |
| `host_permissions` | Allows requests to the configured server URL            |

No data leaves the browser except to the server URL you configure.
