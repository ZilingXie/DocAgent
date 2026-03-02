const { useMemo, useRef, useState, useEffect } = React;

function normalizeInputMessage(raw) {
  return (raw || "")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function clip(value, max = 80) {
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
  return `[${index}] ${clip(label, 64)}`;
}

function dedupeCitations(citations) {
  const seen = new Set();
  const list = [];
  (citations || []).forEach((item) => {
    const key = `${item.source_link || ""}::${item.heading || ""}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    list.push(item);
  });
  return list;
}

function TypingBubble() {
  return (
    <div className="flex justify-start">
      <div className="max-w-[78%] rounded-3xl bg-slate-100 px-5 py-3 text-slate-600">
        <div className="inline-flex items-center gap-2">
          <span className="text-sm font-medium">Thinking</span>
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.1s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
          </span>
        </div>
      </div>
    </div>
  );
}

function MessageItem({ turn, meta, index }) {
  const isUser = turn.role === "user";
  const citations = useMemo(() => dedupeCitations(meta?.citations), [meta?.citations]);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`w-full max-w-[78%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        <div
          className={
            isUser
              ? "rounded-3xl bg-blue-700 px-5 py-3 text-white shadow-sm"
              : "rounded-3xl bg-slate-100 px-5 py-3 text-slate-800 shadow-sm"
          }
        >
          <p className="m-0 whitespace-pre-wrap break-words text-[15px] leading-7">
            {(turn.content || "").trim()}
          </p>

          {!isUser && citations.length > 0 && (
            <div className="mt-4 border-t border-slate-300/70 pt-3">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                References
              </p>
              <div className="flex flex-wrap gap-2">
                {citations.map((item, refIdx) => (
                  <a
                    key={`${item.source_link || ""}-${refIdx}`}
                    href={item.source_link || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={`${item.source_path || ""}\n${item.heading || ""}`.trim()}
                    className="rounded-full border border-slate-300 bg-white/90 px-3 py-1 font-mono text-[11px] text-slate-600 transition hover:border-blue-300 hover:text-blue-700"
                  >
                    {formatReferenceLabel(item, refIdx + 1)}
                  </a>
                ))}
              </div>
              {Number.isFinite(meta?.latency_ms) && (
                <p className="mt-2 text-[11px] text-slate-500">latency {meta.latency_ms} ms</p>
              )}
            </div>
          )}
        </div>
        <span className="px-1 font-mono text-[11px] text-slate-500">
          {isUser ? "You" : "DocAgent"} {isUser ? "" : `• #${index + 1}`}
        </span>
      </div>
    </div>
  );
}

function ChatApp() {
  const [sessionId, setSessionId] = useState(null);
  const [status, setStatus] = useState("Ready");
  const [input, setInput] = useState("");
  const [history, setHistory] = useState([]);
  const [assistantMetaHistory, setAssistantMetaHistory] = useState([]);
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [history, sending]);

  function alignAssistantMeta(nextHistory, appendedMeta) {
    const nextAssistantCount = nextHistory.filter((turn) => turn.role === "assistant").length;
    let nextMeta = [...assistantMetaHistory];
    if (typeof appendedMeta !== "undefined") {
      nextMeta = [...nextMeta, appendedMeta];
    }
    if (nextAssistantCount === 0) {
      return [];
    }
    if (nextMeta.length > nextAssistantCount) {
      return nextMeta.slice(-nextAssistantCount);
    }
    if (nextMeta.length < nextAssistantCount) {
      return [
        ...Array.from({ length: nextAssistantCount - nextMeta.length }, () => null),
        ...nextMeta,
      ];
    }
    return nextMeta;
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

  async function sendMessage(event) {
    if (event) {
      event.preventDefault();
    }

    const message = normalizeInputMessage(input);
    if (!message || sending) {
      return;
    }

    const optimisticHistory = [...history, { role: "user", content: message }];
    setHistory(optimisticHistory);
    setInput("");
    setSending(true);
    setStatus("Thinking...");

    try {
      const data = await callApi("/api/chat", {
        message,
        session_id: sessionId,
      });
      const nextHistory = Array.isArray(data.history) ? data.history : optimisticHistory;
      setSessionId(data.session_id || sessionId);
      setHistory(nextHistory);
      setAssistantMetaHistory(
        alignAssistantMeta(nextHistory, {
          citations: data.citations || [],
          latency_ms: data.latency_ms,
        })
      );
      setStatus("Ready");
    } catch (err) {
      const failHistory = [
        ...optimisticHistory,
        { role: "assistant", content: `Request failed: ${err.message}` },
      ];
      setHistory(failHistory);
      setAssistantMetaHistory(alignAssistantMeta(failHistory, null));
      setStatus(`Error`);
    } finally {
      setSending(false);
    }
  }

  async function resetSession() {
    if (sending) {
      return;
    }
    setStatus("Resetting...");

    try {
      if (sessionId) {
        await callApi("/api/chat/reset", { session_id: sessionId });
      }
      setSessionId(null);
      setHistory([]);
      setAssistantMetaHistory([]);
      setStatus("Ready");
    } catch (err) {
      setStatus("Error");
    }
  }

  let assistantIndex = 0;

  return (
    <div className="min-h-screen bg-slate-50 p-6 font-sans md:p-10">
      <div className="mx-auto flex h-[86vh] w-full max-w-5xl flex-col rounded-[32px] border border-slate-200 bg-white shadow-[0_20px_60px_rgba(15,23,42,0.08)]">
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-8 py-6">
          <div>
            <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-400">
              DocAgent
            </p>
            <h1 className="m-0 text-2xl font-semibold text-slate-800">Modern Chat</h1>
            <p className="mt-2 text-sm text-slate-500">
              Ask questions and open references directly on Agora docs.
            </p>
          </div>

          <div className="flex flex-col items-end gap-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-500">
              <span className="font-medium text-slate-400">Status</span>
              <span className="font-mono text-slate-700">{status}</span>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-500">
              <span className="font-medium text-slate-400">Session</span>
              <span className="font-mono text-slate-700">{sessionId || "-"}</span>
            </div>
            <button
              type="button"
              onClick={resetSession}
              className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
            >
              Reset Session
            </button>
          </div>
        </header>

        <section ref={listRef} className="flex-1 space-y-4 overflow-y-auto px-8 py-6">
          {history.length === 0 && !sending && (
            <div className="flex h-full items-center justify-center">
              <div className="rounded-3xl border border-slate-200 bg-slate-50 px-8 py-10 text-center text-slate-500">
                Start the conversation by sending a message.
              </div>
            </div>
          )}

          {history.map((turn, idx) => {
            const meta = turn.role === "assistant" ? assistantMetaHistory[assistantIndex++] : null;
            return <MessageItem key={`${turn.role}-${idx}`} turn={turn} meta={meta} index={idx} />;
          })}

          {sending && <TypingBubble />}
        </section>

        <form onSubmit={sendMessage} className="border-t border-slate-100 px-8 py-5">
          <div className="flex items-center gap-3 rounded-full border border-slate-200 bg-slate-50 px-3 py-2">
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Message DocAgent..."
              className="h-11 flex-1 rounded-full bg-transparent px-3 text-[15px] text-slate-800 outline-none placeholder:text-slate-400"
            />
            <button
              type="submit"
              disabled={sending}
              className="rounded-full bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("chat-root"));
root.render(<ChatApp />);
