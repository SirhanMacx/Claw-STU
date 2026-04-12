/* Claw-STU Chrome Extension — content script.
 *
 * Listens for text selection and makes it available to the background
 * service worker. The actual "Ask Stuart about this" context menu is
 * created by the background worker; this script just ensures the
 * selection is captured reliably across all page types.
 */
"use strict";

document.addEventListener("mouseup", () => {
  const selection = window.getSelection();
  if (selection && selection.toString().trim().length > 0) {
    if (typeof chrome !== "undefined" && chrome.storage) {
      chrome.storage.local.set({ selectedText: selection.toString().trim() });
    }
  }
});
