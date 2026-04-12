/* Claw-STU Chrome Extension — popup script.
 *
 * Sends the question to the local Claw-STU server at POST /api/ask
 * and displays the response. Pre-fills with any text selected via
 * the context menu.
 */
"use strict";

const BASE_URL = "http://localhost:8000";

const questionEl = document.getElementById("question");
const askBtn = document.getElementById("ask-btn");
const responseEl = document.getElementById("response");
const errorEl = document.getElementById("error");

// Pre-fill from context menu selection
if (typeof chrome !== "undefined" && chrome.storage) {
  chrome.storage.local.get("selectedText", (data) => {
    if (data.selectedText) {
      questionEl.value = data.selectedText;
      chrome.storage.local.remove("selectedText");
    }
  });
}

askBtn.addEventListener("click", async () => {
  const question = questionEl.value.trim();
  if (!question) return;

  askBtn.disabled = true;
  askBtn.textContent = "Thinking...";
  responseEl.classList.remove("visible");
  errorEl.classList.remove("visible");

  try {
    const resp = await fetch(BASE_URL + "/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question }),
    });

    if (!resp.ok) {
      let detail = "";
      try {
        const body = await resp.json();
        detail = body.detail || JSON.stringify(body);
      } catch (_e) {
        detail = resp.statusText;
      }
      throw new Error(detail);
    }

    const data = await resp.json();
    responseEl.textContent = data.response;
    responseEl.classList.add("visible");
  } catch (err) {
    errorEl.textContent = err.message || "Cannot reach server. Is clawstu serve running?";
    errorEl.classList.add("visible");
  } finally {
    askBtn.disabled = false;
    askBtn.textContent = "Ask Stuart";
  }
});

// Enter key submits
questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    askBtn.click();
  }
});
