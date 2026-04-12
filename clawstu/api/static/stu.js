/* Stuart Web UI — vanilla JS against the existing HTTP API. */
"use strict";

// ── State ──────────────────────────────────────────────────────────
let state = "idle"; // idle | calibrating | teaching | checking | closed
let sessionId = null;
let sessionTopic = "";
let sessionStart = null;
let calibrationItems = [];
let calibrationIndex = 0;
let currentCheckItem = null;
let currentBlock = null;

// ── DOM refs ───────────────────────────────────────────────────────
const onboardForm = document.getElementById("onboard-form");
const chatDiv = document.getElementById("chat");
const messagesDiv = document.getElementById("messages");
const answerInput = document.getElementById("answer-input");
const sendBtn = document.getElementById("send-btn");
const closeBtn = document.getElementById("close-btn");
const topicDisplay = document.getElementById("topic-display");

// ── Minimal markdown → HTML ────────────────────────────────────────
function md(text) {
  if (!text) return "";
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

// ── Message helpers ────────────────────────────────────────────────
function addStuMsg(html) {
  const div = document.createElement("div");
  div.className = "msg stu-msg";
  div.innerHTML = html;
  messagesDiv.appendChild(div);
  scrollToBottom();
  return div;
}

function addStudentMsg(text) {
  const div = document.createElement("div");
  div.className = "msg student-msg";
  div.textContent = text;
  messagesDiv.appendChild(div);
  scrollToBottom();
}

function addError(text) {
  const div = document.createElement("div");
  div.className = "error-card";
  div.textContent = text;
  messagesDiv.appendChild(div);
  scrollToBottom();
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "typing";
  div.id = "typing-indicator";
  div.textContent = "Stuart is thinking";
  messagesDiv.appendChild(div);
  scrollToBottom();
  return div;
}

function hideTyping() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}

function scrollToBottom() {
  messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function enableInput(placeholder) {
  answerInput.disabled = false;
  sendBtn.disabled = false;
  answerInput.placeholder = placeholder || "Type your answer...";
  answerInput.focus();
}

function disableInput() {
  answerInput.disabled = true;
  sendBtn.disabled = true;
}

// ── API helpers ────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = {
    method: method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (err) {
    throw new Error("Can't reach the server. Is `clawstu serve` running?");
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const errBody = await resp.json();
      detail = errBody.detail || JSON.stringify(errBody);
    } catch (_e) {
      detail = resp.statusText;
    }
    const error = new Error(detail);
    error.status = resp.status;
    throw error;
  }
  return resp.json();
}

// ── Onboarding ─────────────────────────────────────────────────────
document.getElementById("onboard").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("name-input").value.trim();
  const age = parseInt(document.getElementById("age-input").value, 10);
  const topic = document.getElementById("topic-input").value.trim();

  if (!name || !age || !topic) return;

  sessionTopic = topic;
  sessionStart = Date.now();

  // Show chat, hide form
  onboardForm.classList.add("hidden");
  chatDiv.classList.remove("hidden");
  topicDisplay.textContent = topic;

  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions", {
      learner_id: name,
      age: age,
      domain: "other",
      topic: topic,
    });
    hideTyping();
    sessionId = data.session_id;

    if (data.phase === "calibrating" && data.calibration_items && data.calibration_items.length > 0) {
      state = "calibrating";
      calibrationItems = data.calibration_items;
      calibrationIndex = 0;
      addStuMsg("<p>Welcome, <strong>" + md(name) + "</strong>! Let me figure out where you are with <strong>" + md(topic) + "</strong>.</p><p>Answer a few quick questions so I can find your level.</p>");
      showCalibrationItem();
    } else {
      // Skip calibration, go straight to teaching
      state = "teaching";
      await fetchNextDirective();
    }
  } catch (err) {
    hideTyping();
    addError(err.message);
    console.error("Onboard failed:", err);
  }
});

// ── Calibration flow ───────────────────────────────────────────────
function showCalibrationItem() {
  if (calibrationIndex >= calibrationItems.length) {
    finishCalibration();
    return;
  }
  const item = calibrationItems[calibrationIndex];
  let html = "<p>" + md(item.prompt) + "</p>";

  if (item.choices && item.choices.length > 0) {
    // Multiple-choice: render buttons
    html += '<div class="choices">';
    item.choices.forEach(function (choice, i) {
      html += '<button class="choice-btn" data-item-id="' + item.id + '" data-choice="' + i + '">' + md(choice) + '</button>';
    });
    html += "</div>";
    const msgDiv = addStuMsg(html);
    // Attach click handlers
    msgDiv.querySelectorAll(".choice-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const choiceIndex = parseInt(btn.dataset.choice, 10);
        submitCalibrationAnswer(item.id, item.choices[choiceIndex]);
      });
    });
    disableInput();
  } else {
    // Free response
    addStuMsg(html);
    enableInput("Type your answer...");
    pendingCalibrationItemId = item.id;
  }
}

let pendingCalibrationItemId = null;

async function submitCalibrationAnswer(itemId, response) {
  addStudentMsg(response);
  disableInput();
  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions/" + sessionId + "/calibration-answer", {
      item_id: itemId,
      response: response,
    });
    hideTyping();

    if (data.crisis) {
      showCrisis(data.resources);
      return;
    }

    // Show feedback
    if (data.correct) {
      addStuMsg('<p class="correct-indicator">Correct!</p>');
    } else {
      addStuMsg('<p class="incorrect-indicator">Not quite.</p>');
    }

    calibrationIndex++;
    showCalibrationItem();
  } catch (err) {
    hideTyping();
    if (err.status === 400) {
      // Boundary violation — show the restate message
      addStuMsg("<p>" + md(err.message) + "</p>");
      showCalibrationItem();
    } else {
      addError("Something went wrong. Check the console for details.");
      console.error("Calibration answer failed:", err);
    }
  }
}

async function finishCalibration() {
  disableInput();
  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions/" + sessionId + "/finish-calibration");
    hideTyping();
    state = "teaching";
    handleDirective(data);
  } catch (err) {
    hideTyping();
    addError("Something went wrong. Check the console for details.");
    console.error("Finish calibration failed:", err);
  }
}

// ── Teaching / Checking flow ───────────────────────────────────────
function handleDirective(data) {
  if (data.crisis) {
    showCrisis(data.resources);
    return;
  }

  const directive = data.directive;
  const phase = directive.phase;

  if (phase === "closing" || phase === "closed") {
    closeSession();
    return;
  }

  if (phase === "crisis_pause") {
    showCrisis(directive.message || "Session paused.");
    return;
  }

  if (directive.block) {
    currentBlock = directive.block;
    state = "teaching";

    let html = "<p><strong>" + md(directive.block.title) + "</strong></p>";
    html += "<p>" + md(directive.block.body) + "</p>";
    html += '<button class="ready-btn" id="ready-btn">I\'m ready for a question</button>';

    const msgDiv = addStuMsg(html);
    disableInput();

    const readyBtn = msgDiv.querySelector("#ready-btn");
    if (readyBtn) {
      readyBtn.addEventListener("click", function () {
        readyBtn.disabled = true;
        readyBtn.textContent = "Loading...";
        showCheckItem(directive);
      });
    }
  } else if (directive.check_item) {
    showCheckFromDirective(directive);
  } else if (directive.message) {
    addStuMsg("<p>" + md(directive.message) + "</p>");
    fetchNextDirective();
  } else {
    // No block, no check, no message — fetch next
    fetchNextDirective();
  }
}

function showCheckItem(directive) {
  if (directive.check_item) {
    showCheckFromDirective(directive);
  } else {
    // Need to fetch a check from /next
    fetchNextDirective();
  }
}

function showCheckFromDirective(directive) {
  const item = directive.check_item;
  currentCheckItem = item;
  state = "checking";

  let html = "<p>" + md(item.prompt) + "</p>";

  if (item.choices && item.choices.length > 0) {
    html += '<div class="choices">';
    item.choices.forEach(function (choice, i) {
      html += '<button class="choice-btn" data-item-id="' + item.id + '" data-choice="' + i + '">' + md(choice) + '</button>';
    });
    html += "</div>";
    const msgDiv = addStuMsg(html);
    disableInput();
    msgDiv.querySelectorAll(".choice-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const choiceIndex = parseInt(btn.dataset.choice, 10);
        submitCheckAnswer(item.id, item.choices[choiceIndex]);
      });
    });
  } else {
    addStuMsg(html);
    enableInput("Type your answer...");
  }
}

async function submitCheckAnswer(itemId, response) {
  addStudentMsg(response);
  disableInput();
  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions/" + sessionId + "/check-answer", {
      item_id: itemId,
      response: response,
    });
    hideTyping();
    currentCheckItem = null;
    handleDirective(data);
  } catch (err) {
    hideTyping();
    if (err.status === 400) {
      addStuMsg("<p>" + md(err.message) + "</p>");
      enableInput("Try again...");
    } else {
      addError("Something went wrong. Check the console for details.");
      console.error("Check answer failed:", err);
    }
  }
}

async function fetchNextDirective() {
  disableInput();
  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions/" + sessionId + "/next");
    hideTyping();
    handleDirective(data);
  } catch (err) {
    hideTyping();
    addError("Something went wrong. Check the console for details.");
    console.error("Next directive failed:", err);
  }
}

// ── Send button / Enter key ────────────────────────────────────────
function handleSend() {
  const text = answerInput.value.trim();
  if (!text) return;
  answerInput.value = "";

  if (state === "calibrating" && pendingCalibrationItemId) {
    const itemId = pendingCalibrationItemId;
    pendingCalibrationItemId = null;
    submitCalibrationAnswer(itemId, text);
  } else if (state === "checking" && currentCheckItem) {
    submitCheckAnswer(currentCheckItem.id, text);
  }
}

sendBtn.addEventListener("click", handleSend);
answerInput.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
});

// ── Close session ──────────────────────────────────────────────────
closeBtn.addEventListener("click", function () {
  closeSession();
});

async function closeSession() {
  if (!sessionId) return;
  disableInput();
  const typing = showTyping();
  try {
    const data = await api("POST", "/sessions/" + sessionId + "/close");
    hideTyping();
    showSummary(data.summary);
  } catch (err) {
    hideTyping();
    // Session may already be closed — show summary anyway
    showSummary("Session ended.");
    console.error("Close session:", err);
  }
}

function showSummary(summary) {
  state = "closed";
  const elapsed = sessionStart ? Math.round((Date.now() - sessionStart) / 60000) : 0;

  chatDiv.classList.add("hidden");

  const summaryDiv = document.createElement("div");
  summaryDiv.className = "summary-card";
  summaryDiv.innerHTML =
    "<h2>Session complete</h2>" +
    "<p><strong>Topic:</strong> " + md(sessionTopic) + "</p>" +
    "<p><strong>Duration:</strong> " + elapsed + " minute" + (elapsed !== 1 ? "s" : "") + "</p>" +
    "<p>" + md(summary) + "</p>" +
    '<p class="muted">Run <code>clawstu progress</code> in the terminal for your full dashboard.</p>' +
    '<button onclick="resetToIdle()">Start a new session</button>';

  document.getElementById("app").appendChild(summaryDiv);
}

// ── Crisis handling ────────────────────────────────────────────────
function showCrisis(resources) {
  state = "closed";
  disableInput();
  const div = document.createElement("div");
  div.className = "crisis-card";
  div.innerHTML = "<p>" + md(resources || "Session paused. If you are in crisis, please reach out to the resources below.") + "</p>";
  messagesDiv.appendChild(div);
  scrollToBottom();
}

// ── Reset ──────────────────────────────────────────────────────────
/* exported */ // eslint-disable-line
window.resetToIdle = function () {
  state = "idle";
  sessionId = null;
  sessionTopic = "";
  sessionStart = null;
  calibrationItems = [];
  calibrationIndex = 0;
  currentCheckItem = null;
  currentBlock = null;
  pendingCalibrationItemId = null;

  // Clear messages
  messagesDiv.innerHTML = "";

  // Clear any summary card
  const existing = document.querySelector(".summary-card");
  if (existing) existing.remove();

  // Reset form
  document.getElementById("onboard").reset();

  // Show onboard, hide chat
  chatDiv.classList.add("hidden");
  onboardForm.classList.remove("hidden");
};
