const composerEl = document.getElementById("composer");
const sendBtn = document.getElementById("sendBtn");
const resetBtn = document.getElementById("resetBtn");
const questionEl = document.getElementById("question");
const statusEl = document.getElementById("status");
const messagesEl = document.getElementById("messages");
const emptyStateEl = document.getElementById("emptyState");
const sessionPillEl = document.getElementById("sessionPill");

let sessionId = null;
let historyState = [];
let assistantMetaHistory = [];

function setStatus(text) {
  statusEl.textContent = text;
}

function setSessionPill() {
  sessionPillEl.textContent = sessionId || "-";
}

function autosizeTextarea() {
  questionEl.style.height = "auto";
  questionEl.style.height = `${Math.min(questionEl.scrollHeight, 220)}px`;
}

function clip(value, max = 84) {
  if (!value || value.length <= max) {
    return value || "";
  }
  return `${value.slice(0, max - 3)}...`;
}

function titleCase(text) {
  return (text || "")
    .split(" ")
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ");
}

function inferTitleFromPath(sourcePath) {
  const raw = (sourcePath || "").split("/").pop() || "";
  const withoutExt = raw.replace(/\.md$/i, "");
  if (!withoutExt) {
    return "";
  }

  const segments = withoutExt.split("_").filter(Boolean);
  let core = segments.length > 1 ? segments[1] : segments[0];
  const platform = segments.length > 2 ? segments[segments.length - 1] : "";

  core = core.replace(/[-_]+/g, " ").trim();
  const prettyCore = titleCase(core);

  if (platform && /^[a-z0-9-]+$/i.test(platform)) {
    return `${prettyCore} (${titleCase(platform.replace(/-/g, " "))})`;
  }
  return prettyCore;
}

function formatReferenceLabel(item, index) {
  const heading = (item.heading || "").trim();
  let label = "";

  if (heading && heading.toLowerCase() !== "unknown heading") {
    const parts = heading
      .split(">")
      .map((part) => part.trim())
      .filter(Boolean);
    if (parts.length >= 2) {
      label = `${parts[0]} - ${parts[1]}`;
    } else if (parts.length === 1) {
      label = parts[0];
    }
  }

  if (!label) {
    label = inferTitleFromPath(item.source_path);
  }
  if (!label) {
    label = `Reference ${index}`;
  }

  return `[${index}] ${clip(label, 62)}`;
}

function normalizeInputMessage(raw) {
  return raw
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeRenderMessage(text, role) {
  const base = (text || "").replace(/\r\n/g, "\n").trim();
  if (role === "user") {
    return base.replace(/\n{3,}/g, "\n\n");
  }
  return base;
}

function buildTypingBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "msg assistant";

  const bubble = document.createElement("div");
  bubble.className = "bubble typing-bubble";

  const label = document.createElement("span");
  label.className = "typing-label";
  label.textContent = "Thinking";
  bubble.appendChild(label);

  const dots = document.createElement("span");
  dots.className = "typing-dots";
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement("span");
    dots.appendChild(dot);
  }
  bubble.appendChild(dots);

  wrapper.appendChild(bubble);
  return wrapper;
}

function renderMessages(history, options = {}) {
  const pending = options.pending === true;

  messagesEl.innerHTML = "";
  if ((!history || history.length === 0) && !pending) {
    emptyStateEl.style.display = "block";
    messagesEl.appendChild(emptyStateEl);
    return;
  }
  emptyStateEl.style.display = "none";

  let assistantIndex = 0;
  history.forEach((turn) => {
    const wrapper = document.createElement("div");
    wrapper.className = `msg ${turn.role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = normalizeRenderMessage(turn.content, turn.role);

    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = turn.role === "user" ? "You" : "DocAgent";

    const turnMeta =
      turn.role === "assistant" ? assistantMetaHistory[assistantIndex] || null : null;
    if (turn.role === "assistant") {
      assistantIndex += 1;
    }

    if (turnMeta && turnMeta.citations && turnMeta.citations.length > 0) {
      const refLabel = document.createElement("div");
      refLabel.className = "in-bubble-label";
      refLabel.textContent = "References";
      bubble.appendChild(refLabel);

      const citations = document.createElement("div");
      citations.className = "citations";
      const uniqueCitations = [];
      const seen = new Set();
      turnMeta.citations.forEach((item) => {
        const key = `${item.source_link || ""}::${item.heading || ""}`;
        if (seen.has(key)) {
          return;
        }
        seen.add(key);
        uniqueCitations.push(item);
      });

      uniqueCitations.forEach((item, index) => {
        const chip = document.createElement("a");
        chip.className = "chip";
        chip.href = item.source_link || "#";
        chip.target = "_blank";
        chip.rel = "noopener noreferrer";
        chip.textContent = formatReferenceLabel(item, index + 1);
        chip.title = `${item.source_path || ""}\n${item.heading || ""}`.trim();
        citations.appendChild(chip);
      });
      bubble.appendChild(citations);
    }

    if (turnMeta && Number.isFinite(turnMeta.latency_ms)) {
      const latency = document.createElement("div");
      latency.className = "in-bubble-latency";
      latency.textContent = `latency ${turnMeta.latency_ms} ms`;
      bubble.appendChild(latency);
    }

    wrapper.appendChild(bubble);
    wrapper.appendChild(meta);
    messagesEl.appendChild(wrapper);
  });

  if (pending) {
    messagesEl.appendChild(buildTypingBubble());
  }

  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function callApi(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return resp.json();
}

async function sendMessage() {
  const message = normalizeInputMessage(questionEl.value);
  if (!message) {
    setStatus("Message required");
    return;
  }

  sendBtn.disabled = true;
  setStatus("Thinking...");
  historyState = [...historyState, { role: "user", content: message }];
  renderMessages(historyState, { pending: true });
  questionEl.value = "";
  autosizeTextarea();

  try {
    const data = await callApi("/api/chat", {
      message,
      session_id: sessionId,
    });
    sessionId = data.session_id;
    setSessionPill();
    const nextHistory = Array.isArray(data.history) ? data.history : historyState;
    const nextAssistantCount = nextHistory.filter(
      (turn) => turn.role === "assistant"
    ).length;

    assistantMetaHistory = [
      ...assistantMetaHistory,
      {
        citations: data.citations || [],
        latency_ms: data.latency_ms,
      },
    ];

    if (nextAssistantCount === 0) {
      assistantMetaHistory = [];
    } else if (assistantMetaHistory.length > nextAssistantCount) {
      assistantMetaHistory = assistantMetaHistory.slice(-nextAssistantCount);
    } else if (assistantMetaHistory.length < nextAssistantCount) {
      const padding = Array.from(
        { length: nextAssistantCount - assistantMetaHistory.length },
        () => null
      );
      assistantMetaHistory = [...padding, ...assistantMetaHistory];
    }

    historyState = nextHistory;
    renderMessages(historyState);
    setStatus("Ready");
  } catch (err) {
    historyState = [
      ...historyState,
      { role: "assistant", content: `Request failed: ${err.message}` },
    ];
    assistantMetaHistory = [...assistantMetaHistory, null];
    renderMessages(historyState);
    setStatus(`Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
  }
}

composerEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  await sendMessage();
});

resetBtn.addEventListener("click", async () => {
  sendBtn.disabled = true;
  if (!sessionId) {
    historyState = [];
    assistantMetaHistory = [];
    renderMessages(historyState);
    setStatus("Session cleared");
    sendBtn.disabled = false;
    return;
  }
  setStatus("Resetting...");
  try {
    await callApi("/api/chat/reset", { session_id: sessionId });
    sessionId = null;
    historyState = [];
    assistantMetaHistory = [];
    setSessionPill();
    renderMessages(historyState);
    setStatus("Ready");
  } catch (err) {
    setStatus(`Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
  }
});

questionEl.addEventListener("input", autosizeTextarea);
questionEl.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    await sendMessage();
  }
});

setSessionPill();
renderMessages(historyState);
autosizeTextarea();
