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
      <div className="max-w-[70%] rounded-2xl border border-sky-100/80 bg-white px-4 py-2.5 text-slate-600 shadow-[0_8px_20px_rgba(14,165,233,0.08)]">
        <div className="inline-flex items-center gap-2">
          <span className="text-sm font-medium">Thinking</span>
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:-0.2s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400 [animation-delay:-0.1s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sky-400" />
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
              ? "rounded-3xl bg-gradient-to-br from-sky-500 to-sky-600 px-5 py-3 text-white shadow-[0_10px_24px_rgba(2,132,199,0.28)]"
              : "rounded-3xl border border-sky-100/90 bg-white px-5 py-3 text-slate-800 shadow-[0_8px_22px_rgba(2,132,199,0.08)]"
          }
        >
          <p className="m-0 whitespace-pre-wrap break-words text-[15px] leading-7">
            {(turn.content || "").trim()}
          </p>

          {!isUser && citations.length > 0 && (
            <div className="mt-4 border-t border-sky-100 pt-3">
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
                    className="rounded-full border border-sky-200 bg-white px-3 py-1 font-mono text-[11px] text-slate-600 transition hover:border-sky-400 hover:text-sky-700"
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
    } catch (err) {
      const failHistory = [
        ...optimisticHistory,
        { role: "assistant", content: `Request failed: ${err.message}` },
      ];
      setHistory(failHistory);
      setAssistantMetaHistory(alignAssistantMeta(failHistory, null));
    } finally {
      setSending(false);
    }
  }

  async function resetSession() {
    if (sending) {
      return;
    }

    try {
      if (sessionId) {
        await callApi("/api/chat/reset", { session_id: sessionId });
      }
      setSessionId(null);
      setHistory([]);
      setAssistantMetaHistory([]);
    } catch {}
  }

  let assistantIndex = 0;
  const showLanding = history.length === 0 && !sending;

  const composer = (
    <form
      onSubmit={sendMessage}
      className={
        showLanding
          ? "mx-auto w-full max-w-2xl"
          : "bg-transparent px-5 pb-6 pt-3 md:px-8 md:pb-7"
      }
    >
      <div className="flex items-center gap-3 rounded-[30px] border border-sky-200/90 bg-white/95 px-3 py-2 shadow-[0_16px_40px_rgba(14,165,233,0.16)] backdrop-blur">
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask Anything About Agora Product"
          className="h-11 flex-1 rounded-full bg-transparent px-3 text-[15px] text-slate-800 outline-none placeholder:text-slate-400"
        />
        <button
          type="submit"
          disabled={sending}
          className="min-w-[84px] rounded-full bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Send
        </button>
      </div>
    </form>
  );

  return (
    <div className="h-screen w-screen bg-gradient-to-b from-sky-100/60 via-sky-50 to-white font-sans">
      <div className="flex h-full w-full overflow-hidden bg-white/90 backdrop-blur">
        <div className="flex min-w-0 flex-1 flex-col bg-gradient-to-b from-sky-50/60 via-white to-white">
          <header className="flex items-center justify-between gap-3 border-b border-sky-100/80 bg-white/70 px-5 py-4 backdrop-blur md:px-8">
            <div>
              <h1 className="m-0 text-lg font-semibold text-slate-800 md:text-2xl">
                Agora Document Agent
              </h1>
            </div>

            <div className="flex items-center gap-2">
              <div className="hidden items-center gap-2 rounded-full border border-sky-200 bg-white px-3 py-1 text-xs text-slate-500 sm:inline-flex">
                <span className="font-medium text-slate-400">Session</span>
                <span className="font-mono text-slate-700">{sessionId || "-"}</span>
              </div>
              <button
                type="button"
                onClick={resetSession}
                className="rounded-full border border-sky-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-sky-300 hover:text-sky-700"
              >
                Reset Session
              </button>
            </div>
          </header>

          {showLanding ? (
            <section className="flex flex-1 flex-col items-center justify-center px-6">
              <h2 className="mb-8 text-center text-4xl font-semibold tracking-tight text-slate-800 md:text-5xl">
                What can I help with?
              </h2>
              {composer}
            </section>
          ) : (
            <>
            <section ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-5 py-4 md:px-8 md:py-5">
                {history.map((turn, idx) => {
                  const meta =
                    turn.role === "assistant" ? assistantMetaHistory[assistantIndex++] : null;
                  return (
                    <MessageItem key={`${turn.role}-${idx}`} turn={turn} meta={meta} index={idx} />
                  );
                })}
                {sending && <TypingBubble />}
              </section>
              {composer}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("chat-root"));
root.render(<ChatApp />);
