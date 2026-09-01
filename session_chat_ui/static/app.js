"use strict";

const loginScreen = document.getElementById("loginScreen");
const demographicsScreen = document.getElementById("demographicsScreen");
const chatScreen = document.getElementById("chatScreen");
const loginForm = document.getElementById("loginForm");
const loginUserIdInput = document.getElementById("loginUserId");
const loginButton = document.getElementById("loginButton");
const loginNotice = document.getElementById("loginNotice");
const demographicsForm = document.getElementById("demographicsForm");
const demographicProgress = document.getElementById("demographicProgress");
const demographicProgressBar = document.getElementById("demographicProgressBar");
const demographicQuestion = document.getElementById("demographicQuestion");
const demographicAnswer = document.getElementById("demographicAnswer");
const demographicSubmit = document.getElementById("demographicSubmit");
const demographicNotice = document.getElementById("demographicNotice");
const demographicUserId = document.getElementById("demographicUserId");
const chatForm = document.getElementById("chatForm");
const messages = document.getElementById("messages");
const conversation = document.getElementById("conversation");
const questionInput = document.getElementById("question");
const userIdInput = document.getElementById("userId");
const audienceInput = document.getElementById("audience");
const apiKeyForm = document.getElementById("apiKeyForm");
const apiKeyInput = document.getElementById("apiKey");
const apiKeyButton = document.getElementById("apiKeyButton");
const apiKeyState = document.getElementById("apiKeyState");
const clearApiKeyButton = document.getElementById("clearApiKey");
const sendButton = document.getElementById("sendButton");
const notice = document.getElementById("notice");
const pipelineBadge = document.getElementById("pipelineBadge");
const pipelineText = document.getElementById("pipelineText");
const sessionId = document.getElementById("sessionId");
const sessionState = document.getElementById("sessionState");
const mapName = document.getElementById("mapName");
const storedCount = document.getElementById("storedCount");
const loggedInUserId = document.getElementById("loggedInUserId");
const switchUserButton = document.getElementById("switchUserButton");
const systemToggle = document.getElementById("systemToggle");
const systemStatus = document.getElementById("systemStatus");
const systemStatusText = document.getElementById("systemStatusText");
const systemProgress = document.getElementById("systemProgress");
const systemProgressBar = document.getElementById("systemProgressBar");
const systemDescription = document.getElementById("systemDescription");

const DEFAULT_SYSTEM = "proposed";

let requestInProgress = false;
let statusLoaded = false;
let apiKeyConfigured = false;
let apiKeyEntryAllowed = false;
let displayedHistoryUserId = "";
let displayedHistorySystem = "";
let historyRequestNumber = 0;
let activeDemographicQuestion = null;
let activeSystem = DEFAULT_SYSTEM;
let systemStates = new Map();
let systemOrder = [];
let switchingTo = "";
let fastStatusTimer = null;
let statusInFlight = false;
let systemEpoch = 0;

const emptyConversationMarkup = conversation.innerHTML;

function setInlineNotice(element, message) {
  element.textContent = message || "";
  element.hidden = !message;
}

function showScreen(screen) {
  loginScreen.hidden = screen !== loginScreen;
  demographicsScreen.hidden = screen !== demographicsScreen;
  chatScreen.hidden = screen !== chatScreen;
}

function setCurrentUser(userId) {
  const cleanUserId = userId.trim();
  userIdInput.value = cleanUserId;
  loggedInUserId.textContent = cleanUserId || "—";
  demographicUserId.textContent = cleanUserId;
  demographicUserId.title = cleanUserId;
}

function renderDemographicQuestion(question) {
  activeDemographicQuestion = question;
  demographicQuestion.textContent = question.text;
  demographicProgress.textContent = `Question ${question.number} of ${question.total}`;
  demographicProgressBar.style.width = `${Math.round((question.number / question.total) * 100)}%`;
  demographicAnswer.replaceChildren();
  setInlineNotice(demographicNotice, "");

  if (question.kind === "rating_1_5") {
    const scaleLabels = document.createElement("div");
    scaleLabels.className = "likert-scale-labels";

    const disagree = document.createElement("span");
    disagree.textContent = "1 · Strongly disagree";
    const agree = document.createElement("span");
    agree.textContent = "5 · Strongly agree";
    scaleLabels.append(disagree, agree);

    const options = document.createElement("div");
    options.className = "likert-options";
    options.setAttribute("role", "radiogroup");
    options.setAttribute("aria-label", "Choose a number from 1 to 5");

    for (let value = 1; value <= 5; value += 1) {
      const label = document.createElement("label");
      label.className = "likert-option";

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "demographicRating";
      input.value = String(value);
      input.required = true;
      input.addEventListener("change", () => {
        options.querySelectorAll(".likert-option").forEach((option) => {
          const optionInput = option.querySelector("input");
          option.classList.toggle("selected", optionInput.checked);
        });
      });

      const number = document.createElement("span");
      number.textContent = String(value);
      label.append(input, number);
      options.appendChild(label);
    }

    demographicAnswer.append(scaleLabels, options);
    options.querySelector("input").focus();
    return;
  }

  const input = question.kind === "birth_year"
    ? document.createElement("input")
    : document.createElement(question.index === 2 ? "textarea" : "input");
  input.id = "demographicResponse";
  input.className = "onboarding-input";
  input.name = "demographicResponse";
  input.required = true;
  input.maxLength = 2000;

  if (question.kind === "birth_year") {
    input.type = "number";
    input.min = "1900";
    input.max = String(new Date().getUTCFullYear());
    input.step = "1";
    input.inputMode = "numeric";
    input.placeholder = "Four-digit year";
  } else {
    input.placeholder = question.index === 1
      ? "Enter your gender"
      : "Enter your response";
    if (input.tagName === "TEXTAREA") input.rows = 3;
  }

  demographicAnswer.appendChild(input);
  input.focus();
}

function readDemographicAnswer() {
  if (!activeDemographicQuestion) return "";
  if (activeDemographicQuestion.kind === "rating_1_5") {
    const selected = demographicAnswer.querySelector(
      'input[name="demographicRating"]:checked',
    );
    return selected ? selected.value : "";
  }
  const input = demographicAnswer.querySelector(".onboarding-input");
  return input ? input.value.trim() : "";
}

async function enterChat() {
  showScreen(chatScreen);
  setNotice("");
  resetConversation();
  displayedHistoryUserId = "";
  displayedHistorySystem = "";
  activeSystem = DEFAULT_SYSTEM;
  switchingTo = "";

  // Status first, so the system labels are known before history renders.
  await refreshStatus();
  await loadChatHistory(userIdInput.value, activeSystem);

  if (apiKeyConfigured) {
    questionInput.focus();
  } else if (apiKeyEntryAllowed) {
    apiKeyInput.focus();
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = loginUserIdInput.value.trim();
  if (!userId) {
    setInlineNotice(loginNotice, "Enter your User ID.");
    loginUserIdInput.focus();
    return;
  }

  loginButton.disabled = true;
  setInlineNotice(loginNotice, "");

  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ user_id: userId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "The participant login could not be saved.");
    }

    setCurrentUser(data.user_id);
    if (data.completed) {
      await enterChat();
    } else if (data.question) {
      showScreen(demographicsScreen);
      renderDemographicQuestion(data.question);
      refreshStatus();
    } else {
      throw new Error("The next survey question could not be loaded.");
    }
  } catch (error) {
    setInlineNotice(
      loginNotice,
      error.message || "The participant login could not be saved.",
    );
  } finally {
    loginButton.disabled = false;
  }
});

demographicsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!activeDemographicQuestion) return;

  const answer = readDemographicAnswer();
  if (!answer) {
    setInlineNotice(demographicNotice, "Enter or select a response before continuing.");
    return;
  }

  demographicSubmit.disabled = true;
  setInlineNotice(demographicNotice, "");

  try {
    const response = await fetch("/api/demographics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        user_id: userIdInput.value,
        question_index: activeDemographicQuestion.index,
        answer,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      if (data.question) renderDemographicQuestion(data.question);
      throw new Error(data.error || "The survey response could not be saved.");
    }

    if (data.completed) {
      activeDemographicQuestion = null;
      await enterChat();
    } else if (data.question) {
      renderDemographicQuestion(data.question);
    } else {
      throw new Error("The next survey question could not be loaded.");
    }
  } catch (error) {
    setInlineNotice(
      demographicNotice,
      error.message || "The survey response could not be saved.",
    );
  } finally {
    demographicSubmit.disabled = false;
  }
});

switchUserButton.addEventListener("click", () => {
  if (requestInProgress || switchingTo) {
    setNotice("Wait for the current QBot response before switching users.");
    return;
  }

  historyRequestNumber += 1;
  activeDemographicQuestion = null;
  displayedHistoryUserId = "";
  displayedHistorySystem = "";
  activeSystem = DEFAULT_SYSTEM;
  setCurrentUser("");
  resetConversation();
  loginUserIdInput.value = "";
  setInlineNotice(loginNotice, "");
  showScreen(loginScreen);
  refreshStatus();
  loginUserIdInput.focus();
});

function setNotice(message) {
  notice.textContent = message || "";
  notice.hidden = !message;
}

const systemButtons = new Map();

function systemEntry(id) {
  return systemStates.get(id) || null;
}

function systemLabel(id) {
  const entry = systemEntry(id);
  return entry ? entry.label : id;
}

function storeSystemState(entry) {
  if (!entry || !entry.id) return;
  systemStates.set(entry.id, entry);
  if (!systemOrder.includes(entry.id)) systemOrder.push(entry.id);
}

function ensureSystemButton(id) {
  let button = systemButtons.get(id);
  if (button) return button;

  button = document.createElement("button");
  button.type = "button";
  button.className = "system-option";
  button.setAttribute("role", "radio");

  const name = document.createElement("span");
  name.className = "system-option-name";
  button.appendChild(name);
  button.addEventListener("click", () => {
    selectSystem(id);
  });

  systemButtons.set(id, button);
  systemToggle.appendChild(button);
  return button;
}

function renderSystems() {
  const busy = Boolean(switchingTo) || requestInProgress;
  systemToggle.setAttribute("aria-busy", switchingTo ? "true" : "false");

  systemOrder.forEach((id) => {
    const entry = systemStates.get(id);
    if (!entry) return;

    const button = ensureSystemButton(id);
    const isTarget = id === switchingTo;
    // Only ready systems are clickable; the /rosout baseline follows the same
    // active/blocked lifecycle as the other runtime-backed systems.
    const selectable = Boolean(entry.actionable);
    // While switching, only the incoming system is highlighted: the outgoing
    // one is already put away.
    const highlighted = switchingTo ? isTarget : id === activeSystem;

    button.querySelector(".system-option-name").textContent = entry.label;
    button.classList.toggle("selected", highlighted);
    button.setAttribute("aria-checked", highlighted ? "true" : "false");
    button.disabled = busy || !selectable;
    button.title = entry.detail || entry.description || "";

    const spinner = button.querySelector(".system-spinner");
    if (isTarget || entry.state === "preparing") {
      if (!spinner) {
        const dot = document.createElement("span");
        dot.className = "system-spinner";
        dot.setAttribute("aria-hidden", "true");
        button.appendChild(dot);
      }
    } else if (spinner) {
      spinner.remove();
    }
  });

  updateSystemStatusLine();
}

function systemHeadline(entry) {
  if (entry.state === "failed") {
    return `${entry.label} could not be prepared. Select it to try again.`;
  }
  return entry.detail || `${entry.label} is unavailable`;
}

function updateSystemStatusLine() {
  const entry = systemEntry(switchingTo || activeSystem);

  if (!entry) {
    systemStatus.className = "system-status";
    systemStatusText.textContent = "Checking systems…";
    systemStatusText.title = "";
    systemProgress.hidden = true;
    systemDescription.textContent = "";
    return;
  }

  const progress = entry.state === "preparing" ? entry.progress : null;
  let tone = "";
  let text = "";

  if (entry.state === "preparing") {
    text = progress && progress.total
      ? `Building /rosout index — ${progress.done} / ${progress.total} logs`
      : "Building /rosout index…";
  } else if (switchingTo) {
    text = `Starting ${entry.label}…`;
  } else if (entry.state === "ready") {
    tone = "ready";
    text = `${entry.label} is ready`;
  } else if (entry.state === "needs_preparation") {
    text = entry.detail || "Select this system to prepare it";
  } else {
    tone = "error";
    text = systemHeadline(entry);
  }

  systemStatus.className = `system-status${tone ? ` ${tone}` : ""}`;
  systemStatusText.textContent = text;
  systemStatusText.title = text;
  systemDescription.textContent = entry.description || "";

  if (progress && progress.total > 0) {
    systemProgress.hidden = false;
    systemProgressBar.style.width = `${Math.min(
      100,
      Math.round((progress.done / progress.total) * 100),
    )}%`;
  } else {
    systemProgress.hidden = true;
    systemProgressBar.style.width = "0%";
  }
}

function updateComposerLock() {
  const switching = Boolean(switchingTo);
  const locked = switching || requestInProgress;
  const entry = systemEntry(activeSystem);

  sendButton.disabled = locked;
  questionInput.disabled = switching;
  switchUserButton.disabled = locked;
  audienceInput.disabled = locked || (entry ? entry.uses_audience === false : false);
}

function updateFastStatusPolling() {
  const preparing = systemOrder.some((id) => {
    const entry = systemStates.get(id);
    return Boolean(entry) && entry.state === "preparing";
  });

  if ((preparing || switchingTo) && fastStatusTimer === null) {
    fastStatusTimer = setInterval(refreshStatus, 1500);
  } else if (!preparing && !switchingTo && fastStatusTimer !== null) {
    clearInterval(fastStatusTimer);
    fastStatusTimer = null;
  }
}

async function applySystem(id) {
  activeSystem = id;
  switchingTo = "";
  updateComposerLock();
  renderSystems();

  displayedHistorySystem = "";
  resetConversation();
  await loadChatHistory(userIdInput.value, id);

  if (!questionInput.disabled) questionInput.focus();
}

async function selectSystem(id) {
  if (switchingTo) return;

  if (requestInProgress) {
    setNotice("Wait for the current QBot response before switching systems.");
    return;
  }

  const entry = systemEntry(id);
  if (!entry) return;

  if (!entry.actionable) {
    if (id === "rosout" && entry.state === "needs_preparation") {
      switchingTo = id;
      updateComposerLock();
      renderSystems();

      try {
        const response = await fetch("/api/system/prepare", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
          body: JSON.stringify({ system: id }),
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.error || "The /rosout index could not be prepared.");
        }

        await refreshStatus();
        if (systemEntry(id) && systemEntry(id).ready) {
          await applySystem(id);
          setNotice(`${entry.label} is ready.`);
          return;
        }
        setNotice(systemHeadline(systemEntry(id) || entry));
        return;
      } catch (error) {
        switchingTo = "";
        updateComposerLock();
        renderSystems();
        setNotice(error.message || "The /rosout index could not be prepared.");
        return;
      }
    }

    setNotice(systemHeadline(entry));
    return;
  }

  if (id === activeSystem) return;
  setNotice("");
  await applySystem(id);
  setNotice(`${entry.label} is ready.`);
}

function resolveSwitchProgress() {
  if (!switchingTo) return;

  const entry = systemEntry(switchingTo);
  if (!entry || entry.state === "preparing") return;

  if (entry.state === "ready") {
    const target = switchingTo;
    switchingTo = "";
    applySystem(target).then(() => {
      setNotice(`${entry.label} is ready to use.`);
    });
    return;
  }

  switchingTo = "";
  updateComposerLock();
  renderSystems();
  setNotice(systemHeadline(entry));
}

function applySystemStates(systems, defaultSystem) {
  if (!Array.isArray(systems)) return;

  systemOrder = systems.map((item) => item.id);
  systemStates = new Map(systems.map((item) => [item.id, item]));

  if (!systemStates.has(activeSystem)) {
    activeSystem = systemStates.has(defaultSystem)
      ? defaultSystem
      : systemOrder[0] || DEFAULT_SYSTEM;
  }

  renderSystems();
  updateComposerLock();
  resolveSwitchProgress();
  updateFastStatusPolling();

  const active = systemEntry(activeSystem);
  const fallback = systemEntry(DEFAULT_SYSTEM);
  if (
    !switchingTo
    && !requestInProgress
    && active
    && !active.ready
    && activeSystem !== DEFAULT_SYSTEM
    && fallback
    && fallback.ready
  ) {
    const reason = active.detail || `${active.label} is no longer available.`;
    applySystem(DEFAULT_SYSTEM).then(() => {
      setNotice(`${reason} Switched back to ${fallback.label}.`);
    });
  }
}

function scrollToLatest() {
  messages.scrollTop = messages.scrollHeight;
}

function resetConversation() {
  conversation.innerHTML = emptyConversationMarkup;
  messages.scrollTop = 0;
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
  conversation.appendChild(article);
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
  conversation.appendChild(article);
  scrollToLatest();
  return article;
}

function resizeQuestion() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 150)}px`;
}

function formatSavedTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "saved earlier";
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function loadChatHistory(userId, system) {
  const cleanUserId = userId.trim();
  const wantedSystem = system || activeSystem;
  const requestNumber = ++historyRequestNumber;

  if (!cleanUserId) {
    displayedHistoryUserId = "";
    displayedHistorySystem = "";
    resetConversation();
    return false;
  }

  try {
    const response = await fetch("/api/history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ user_id: cleanUserId, system: wantedSystem }),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Saved chats could not be loaded.");
    }

    if (
      requestNumber !== historyRequestNumber
      || userIdInput.value.trim() !== cleanUserId
      || wantedSystem !== activeSystem
    ) {
      return false;
    }

    const interactions = Array.isArray(data.interactions)
      ? data.interactions
      : [];

    conversation.replaceChildren();

    const divider = document.createElement("div");
    divider.className = "history-divider";
    divider.textContent = interactions.length === 0
      ? systemLabel(wantedSystem)
      : `${systemLabel(wantedSystem)} · ${interactions.length} saved chat${interactions.length === 1 ? "" : "s"}`;

    if (interactions.length === 0) {
      resetConversation();
      conversation.prepend(divider);
    } else {
      conversation.appendChild(divider);

      interactions.forEach((entry) => {
        const savedTime = formatSavedTime(entry.asked_at_iso);
        addMessage(entry.question || "", "user", `${cleanUserId} · ${savedTime}`);
        addMessage(
          entry.robot_response || "No saved response.",
          "assistant",
          `${systemLabel(entry.system || wantedSystem)} · ${savedTime} · saved`,
          entry.status === "error",
        );
      });
    }

    displayedHistoryUserId = cleanUserId;
    displayedHistorySystem = wantedSystem;
    scrollToLatest();
    return true;
  } catch (error) {
    if (requestNumber === historyRequestNumber) {
      setNotice(error.message || "Saved chats could not be loaded.");
    }
    return false;
  }
}

async function refreshStatus() {
  if (statusInFlight) return;
  statusInFlight = true;
  const epoch = systemEpoch;

  try {
    const currentUserId = userIdInput.value.trim();
    const response = await fetch("/api/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ user_id: currentUserId }),
    });
    if (!response.ok) {
      throw new Error("Status request failed");
    }

    const data = await response.json();
    statusLoaded = true;
    apiKeyConfigured = Boolean(data.api_key_configured);
    apiKeyEntryAllowed = Boolean(data.api_key_entry_allowed);
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
    mapName.textContent = data.map_name
      || (currentUserId ? "No maps for this user" : "Enter User ID");
    mapName.title = data.map_name || "";
    storedCount.textContent = String(data.stored_exchange_count || 0);

    apiKeyInput.disabled = !apiKeyEntryAllowed;
    apiKeyButton.disabled = !apiKeyEntryAllowed;
    clearApiKeyButton.hidden = !(apiKeyConfigured && apiKeyEntryAllowed);
    apiKeyState.className = `api-key-state${apiKeyConfigured ? " configured" : ""}`;

    if (apiKeyConfigured) {
      apiKeyState.textContent = "Configured in memory";
      apiKeyButton.textContent = "Replace";
    } else if (apiKeyEntryAllowed) {
      apiKeyState.textContent = "Not configured";
      apiKeyButton.textContent = "Use key";
    } else {
      apiKeyState.textContent = "Enter at localhost:8766 on the QBot";
      apiKeyButton.textContent = "Local only";
    }

    // Discard system states requested before the latest prepare call.
    if (epoch === systemEpoch) {
      applySystemStates(data.systems, data.default_system);
    }
  } catch (error) {
    statusLoaded = false;
    pipelineBadge.className = "pipeline-badge error";
    pipelineText.textContent = "UI server unavailable";
  } finally {
    statusInFlight = false;
  }
}

apiKeyForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  let apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    setNotice("Enter your NVIDIA API key.");
    apiKeyInput.focus();
    return;
  }

  if (!apiKeyEntryAllowed) {
    setNotice("Open http://localhost:8766 on the QBot itself to enter the API key.");
    apiKeyInput.value = "";
    apiKey = null;
    return;
  }

  let requestBody = JSON.stringify({ api_key: apiKey });
  apiKeyInput.value = "";
  apiKey = null;
  apiKeyButton.disabled = true;
  setNotice("");

  try {
    const response = await fetch("/api/api-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: requestBody,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "The API key could not be configured.");
    }
    setNotice("NVIDIA API key is ready for this UI session only.");
  } catch (error) {
    setNotice(error.message || "The API key could not be configured.");
  } finally {
    requestBody = null;
    await refreshStatus();
  }
});

clearApiKeyButton.addEventListener("click", async () => {
  clearApiKeyButton.disabled = true;
  setNotice("");

  try {
    const response = await fetch("/api/api-key", {
      method: "DELETE",
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "The API key could not be removed.");
    }
    setNotice("NVIDIA API key was removed from server memory.");
  } catch (error) {
    setNotice(error.message || "The API key could not be removed.");
  } finally {
    clearApiKeyButton.disabled = false;
    await refreshStatus();
  }
});

questionInput.addEventListener("input", resizeQuestion);

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

messages.addEventListener("click", (event) => {
  const button = event.target.closest(".suggestion");
  if (button) {
    questionInput.value = button.textContent || "";
    resizeQuestion();
    questionInput.focus();
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (requestInProgress) return;

  if (switchingTo) {
    setNotice(`${systemLabel(switchingTo)} is still starting up.`);
    return;
  }

  const userId = userIdInput.value.trim();
  const question = questionInput.value.trim();

  if (!userId) {
    showScreen(loginScreen);
    setInlineNotice(loginNotice, "Log in before sending a question.");
    loginUserIdInput.focus();
    return;
  }

  if (!question) {
    setNotice("Enter a question for QBot.");
    questionInput.focus();
    return;
  }

  if (statusLoaded && !apiKeyConfigured) {
    setNotice(
      apiKeyEntryAllowed
        ? "Enter the NVIDIA API key before sending a question."
        : "Open http://localhost:8766 on the QBot to enter the NVIDIA API key.",
    );
    if (apiKeyEntryAllowed) apiKeyInput.focus();
    return;
  }

  const activeEntry = systemEntry(activeSystem);
  if (statusLoaded && activeEntry && !activeEntry.ready) {
    setNotice(
      activeEntry.detail
      || `${activeEntry.label} is not ready to answer questions.`,
    );
    return;
  }

  if (
    displayedHistoryUserId !== userId
    || displayedHistorySystem !== activeSystem
  ) {
    await loadChatHistory(userId, activeSystem);
  }

  setNotice("");

  const suggestions = document.getElementById("suggestions");
  if (suggestions) suggestions.remove();

  addMessage(question, "user", userId);
  questionInput.value = "";
  resizeQuestion();

  const thinking = addThinkingMessage();
  const askedSystem = activeSystem;
  requestInProgress = true;
  updateComposerLock();
  renderSystems();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        question,
        audience: audienceInput.value,
        system: askedSystem,
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
    const answeringSystem = systemLabel(data.system || askedSystem);
    const meta = response.ok
      ? `${answeringSystem} · ${Math.max(0, Math.round((data.response_time_ms || 0) / 100) / 10)}s · saved`
      : `${answeringSystem} · request error`;
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
    updateComposerLock();
    renderSystems();
    questionInput.focus();
    refreshStatus();
  }
});

showScreen(loginScreen);
loginUserIdInput.focus();
refreshStatus();
setInterval(refreshStatus, 10000);
