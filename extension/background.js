/* Claw-STU Chrome Extension — background service worker.
 *
 * Creates the "Ask Stuart about this" context menu item and relays
 * selected text to the popup via chrome.storage.local.
 */
"use strict";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "ask-stuart",
    title: "Ask Stuart about this",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "ask-stuart" && info.selectionText) {
    chrome.storage.local.set({ selectedText: info.selectionText });
    chrome.action.openPopup();
  }
});
