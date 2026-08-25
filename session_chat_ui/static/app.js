"use strict";

const chatForm = document.getElementById("chatForm");
const messages = document.getElementById("messages");
const questionInput = document.getElementById("question");
const userIdInput = document.getElementById("userId");
const audienceInput = document.getElementById("audience");
const sendButton = document.getElementById("sendButton");
const notice = document.getElementById("notice");
const pipelineBadge = document.getElementById("pipelineBadge");
const pipelineText = document.getElementById("pipelineText");
const sessionId = document.getElementById("sessionId");
const sessionState = document.getElementById("sessionState");
const mapName = document.getElementById("mapName");
const storedCount = document.getElementById("storedCount");

let requestInProgress = false;

try {
  userIdInput.value = localStorage.getItem("qbot-session-user-id") || "";
} catch (error) {
  // The UI still works when browser storage is disabled.
}

function setNotice(message) {
  notice.textContent = message || "";
  notice.hidden = !message;
}

function scrollToLatest() {
  messages.scrollTop = messages.scrollHeight;
}

function initials(value) {
  const clean = value.trim();
  return clean ? clean.slice(0, 2).toUpperCase() : "ME";
}

function addMessage(text, role, metaText, isError = false) {
  const article = document.createElement("article");
  article.className = `message ${role}-message${isError ? " error-message" : ""}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = role === "user" ? initials(userIdInput.value) : "QB";

  const body = document.createElement("div");
  body.className = "message-body";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = metaText;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  body.append(meta, bubble);
  article.append(avatar, body);
  messages.appendChild(article);
  scrollToLatest();
  return article;
}

function addThinkingMessage() {
  const article = document.createElement("article");
  article.className = "message assistant-message thinking";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "QB";

  const body = document.createElement("div");
  body.className = "message-body";

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = "Searching robot evidence";

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  for (let index = 0; index < 3; index += 1) {
    const dot = document.createElement("span");
    dot.className = "thinking-dot";
    bubble.appendChild(dot);
  }

  body.append(meta, bubble);
  article.append(avatar, body);
  messages.appendChild(article);
  scrollToLatest();
  return article;
}

function resizeQuestion() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 150)}px`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Status request failed");
    }

    const data = await response.json();
    pipelineBadge.className = `pipeline-badge ${data.ready ? "ready" : "error"}`;

    if (data.ready) {
      pipelineText.textContent = "RAG pipeline ready";
    } else if (!data.session_ready) {
      pipelineText.textContent = "Waiting for experiment";
    } else if (!data.embedding_ready) {
      pipelineText.textContent = "Embedding service offline";
    } else if (!data.api_key_configured) {
      pipelineText.textContent = "API key not set";
    } else {
      pipelineText.textContent = "Pipeline unavailable";
    }

    sessionId.textContent = data.session_id || "Not found";
    sessionId.title = data.session_id || "";
    sessionState.textContent = data.session_status || "Unknown";
    mapName.textContent = data.map_name || "Not recorded";
    mapName.title = data.map_name || "";
    storedCount.textContent = String(data.stored_exchange_count || 0);
  } catch (error) {
    pipelineBadge.className = "pipeline-badge error";
    pipelineText.textContent = "UI server unavailable";
  }
}

questionInput.addEventListener("input", resizeQuestion);

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.textContent;
    resizeQuestion();
    questionInput.focus();
  });
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (requestInProgress) return;

  const userId = userIdInput.value.trim();
  const question = questionInput.value.trim();

  if (!userId) {
    setNotice("Enter your user ID before sending a question.");
    userIdInput.focus();
    return;
  }

  if (!question) {
    setNotice("Enter a question for QBot.");
    questionInput.focus();
    return;
  }

  setNotice("");
  try {
    localStorage.setItem("qbot-session-user-id", userId);
  } catch (error) {
    // Browser storage is optional.
  }

  const suggestions = document.getElementById("suggestions");
  if (suggestions) suggestions.remove();

  addMessage(question, "user", userId);
  questionInput.value = "";
  resizeQuestion();

  const thinking = addThinkingMessage();
  requestInProgress = true;
  sendButton.disabled = true;
  userIdInput.disabled = true;
  audienceInput.disabled = true;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        question,
        audience: audienceInput.value,
      }),
    });

    let data;
    try {
      data = await response.json();
    } catch (error) {
      data = { error: "The UI server returned an unreadable response." };
    }

    thinking.remove();
    const responseText = data.answer || data.error || "No answer was returned.";
    const meta = response.ok
      ? `QBot assistant · ${Math.max(0, Math.round((data.response_time_ms || 0) / 100) / 10)}s · saved`
      : "QBot assistant · request error";
    addMessage(responseText, "assistant", meta, !response.ok);

    if (data.error && data.answer && data.error !== data.answer) {
      setNotice(data.error);
    }
  } catch (error) {
    thinking.remove();
    addMessage(
      "The browser could not reach the QBot UI server. Check that run_ui.sh is still running.",
      "assistant",
      "Connection error",
      true,
    );
  } finally {
    requestInProgress = false;
    sendButton.disabled = false;
    userIdInput.disabled = false;
    audienceInput.disabled = false;
    questionInput.focus();
    refreshStatus();
  }
});

refreshStatus();
setInterval(refreshStatus, 10000);
