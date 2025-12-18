import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

const API_URL = "http://localhost:8000";

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [emailInput, setEmailInput] = useState("");
  const [emailError, setEmailError] = useState("");
  const [pendingQuery, setPendingQuery] = useState(null);

  const [sessionId, setSessionId] = useState(() => {
    const existing = localStorage.getItem("chat_session_id");
    if (existing) return existing;
    const sid = `session_${Date.now()}`;
    localStorage.setItem("chat_session_id", sid);
    return sid;
  });

  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ---------------------- SHOW EMAIL UI ----------------------
  const showEmailCard = (data) => {
    const skipAllowed = data.skip_allowed ?? (data.skip_count === 0);

    setMessages((prev) => prev.filter((m) => m.type !== "email_card"));

    setMessages((prev) => [
      ...prev,
      {
        id: `email_${Date.now()}`,
        role: "bot",
        type: "email_card",
        content: data.message || "Please provide your email to continue.",
        skipAllowed,
      },
    ]);
  };

  // ---------------------- STREAM ----------------------
  const startStream = async (text, isRetry = false, overrideEmail = null) => {
    if (!text.trim()) return;
    setLoading(true);

    const userId = !isRetry ? `u_${Date.now()}` : null;
    const botId = `b_${Date.now()}_${Math.random()}`;

    if (!isRetry) {
      setMessages((prev) => [
        ...prev,
        { id: userId, role: "user", content: text },
        { id: botId, role: "bot", content: "", streaming: true },
      ]);
    } else {
      setMessages((prev) => [
        ...prev,
        { id: botId, role: "bot", content: "", streaming: true },
      ]);
    }

    try {
      const resp = await fetch(`${API_URL}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          email: overrideEmail || undefined,
        }),
      });

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 1);

          if (!line.startsWith("data:")) continue;

          let data = {};
          try {
            data = JSON.parse(line.replace("data:", "").trim());
          } catch {
            continue;
          }

          if (data.require_email) {
            setMessages((prev) => prev.filter((x) => x.id !== botId));
            setPendingQuery(text);
            showEmailCard(data);
            reader.cancel();
            setLoading(false);
            return;
          }

          setMessages((prev) =>
            prev.map((m) =>
              m.id === botId
                ? {
                    ...m,
                    content: data.content ?? m.content,
                    sources: data.sources ?? "",
                    streaming: !data.done,
                  }
                : m
            )
          );

          if (data.done && data.session_id) {
            localStorage.setItem("chat_session_id", data.session_id);
            setSessionId(data.session_id);
          }
        }
      }

      setMessages((prev) =>
        prev.map((m) => (m.id === botId ? { ...m, streaming: false } : m))
      );
    } catch (e) {
      console.error("Stream error:", e);
    }

    setLoading(false);
  };

  // ---------------------- SEND MESSAGE ----------------------
  const sendMessage = () => {
    if (!input.trim()) return;

    setMessages((prev) => prev.filter((m) => m.type !== "email_card"));

    const txt = input.trim();
    setInput("");
    startStream(txt);
  };

  // ---------------------- EMAIL SUBMIT ----------------------
  const handleEmailSubmit = async () => {
    setEmailError("");

    if (!emailInput.includes("@")) {
      setEmailError("Enter a valid email");
      return;
    }

    try {
      const res = await fetch(`${API_URL}/api/email/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailInput,
          session_id: sessionId,
        }),
      });

      const data = await res.json();
      if (!data.success) {
        setEmailError(data.message);
        return;
      }

      const retry = pendingQuery;
      setPendingQuery(null);

      const savedEmail = emailInput;
      setEmailInput("");

      setMessages((prev) => prev.filter((m) => m.type !== "email_card"));

      if (retry) {
        setTimeout(() => startStream(retry, true, savedEmail), 100);
      }
    } catch {
      setEmailError("Network error");
    }
  };

  // ---------------------- SKIP EMAIL ----------------------
  const handleEmailSkip = async () => {
    try {
      const res = await fetch(`${API_URL}/api/email/skip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });

      const data = await res.json();

      if (!data.success) {
        setEmailError("Skip not allowed");
        return;
      }

      const retry = pendingQuery;
      setPendingQuery(null);

      setMessages((prev) => prev.filter((m) => m.type !== "email_card"));

      if (retry) setTimeout(() => startStream(retry, true), 100);
    } catch {
      setEmailError("Network error");
    }
  };

  // ---------------------- CLEAR CHAT ----------------------
  const clearChat = () => {
    const sid = `session_${Date.now()}`;
    localStorage.setItem("chat_session_id", sid);
    setSessionId(sid);
    setMessages([]);
    setEmailInput("");
    setEmailError("");
    setPendingQuery(null);
  };

  // ---------------------- MARKDOWN RENDER ----------------------
  const renderMarkdown = (text) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ node, ...props }) => (
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              marginTop: "16px",
              marginBottom: "16px",
              border: "2px solid #e1e4e8",
              borderRadius: "6px",
              overflow: "hidden",
            }}
            {...props}
          />
        ),
        thead: ({ node, ...props }) => (
          <thead style={{ background: "#f6f8fa" }} {...props} />
        ),
        th: ({ node, ...props }) => (
          <th
            style={{
              border: "1px solid #e1e4e8",
              padding: "12px 16px",
              fontWeight: "600",
              textAlign: "left",
              color: "#24292e",
            }}
            {...props}
          />
        ),
        td: ({ node, ...props }) => (
          <td
            style={{
              border: "1px solid #e1e4e8",
              padding: "12px 16px",
              color: "#24292e",
            }}
            {...props}
          />
        ),
        tr: ({ node, ...props }) => (
          <tr
            style={{
              background: "white",
              borderBottom: "1px solid #e1e4e8",
            }}
            {...props}
          />
        ),
        a: ({ node, ...props }) => (
          <a
            {...props}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: "#0366d6",
              textDecoration: "none",
              fontWeight: "500",
            }}
          />
        ),
        p: ({ node, ...props }) => (
          <p style={{ marginBottom: "12px", lineHeight: "1.6" }} {...props} />
        ),
        ul: ({ node, ...props }) => (
          <ul
            style={{
              marginLeft: "20px",
              marginBottom: "12px",
              lineHeight: "1.7",
            }}
            {...props}
          />
        ),
        ol: ({ node, ...props }) => (
          <ol
            style={{
              marginLeft: "20px",
              marginBottom: "12px",
              lineHeight: "1.7",
            }}
            {...props}
          />
        ),
        li: ({ node, ...props }) => (
          <li style={{ marginBottom: "6px" }} {...props} />
        ),
        h1: ({ node, ...props }) => (
          <h1
            style={{
              fontSize: "24px",
              fontWeight: "700",
              marginTop: "20px",
              marginBottom: "12px",
              color: "#24292e",
            }}
            {...props}
          />
        ),
        h2: ({ node, ...props }) => (
          <h2
            style={{
              fontSize: "20px",
              fontWeight: "700",
              marginTop: "18px",
              marginBottom: "10px",
              color: "#24292e",
            }}
            {...props}
          />
        ),
        h3: ({ node, ...props }) => (
          <h3
            style={{
              fontSize: "18px",
              fontWeight: "600",
              marginTop: "16px",
              marginBottom: "8px",
              color: "#24292e",
            }}
            {...props}
          />
        ),
        blockquote: ({ node, ...props }) => (
          <blockquote
            style={{
              borderLeft: "4px solid #dfe2e5",
              paddingLeft: "16px",
              margin: "12px 0",
              color: "#6a737d",
              fontStyle: "italic",
            }}
            {...props}
          />
        ),
        code({ inline, className, children }) {
          const match = /language-(\w+)/.exec(className || "");
          return !inline ? (
            <SyntaxHighlighter
              style={oneLight}
              language={match ? match[1] : "text"}
              PreTag="div"
              customStyle={{
                borderRadius: "6px",
                padding: "16px",
                marginTop: "12px",
                marginBottom: "12px",
                border: "1px solid #e1e4e8",
              }}
            >
              {String(children).replace(/\n$/, "")}
            </SyntaxHighlighter>
          ) : (
            <code
              style={{
                background: "#f6f8fa",
                padding: "2px 6px",
                borderRadius: "3px",
                fontSize: "0.9em",
                color: "#24292e",
                border: "1px solid #e1e4e8",
              }}
            >
              {children}
            </code>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );

  // ---------------------- RENDER MESSAGE ----------------------
  const renderMessage = (msg) => {
    if (msg.role === "user") {
      return (
        <div
          key={msg.id}
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginBottom: "16px",
          }}
        >
          <div
            style={{
              background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
              color: "white",
              padding: "12px 18px",
              borderRadius: "18px 18px 4px 18px",
              maxWidth: "75%",
              wordWrap: "break-word",
              boxShadow: "0 2px 8px rgba(102, 126, 234, 0.25)",
            }}
          >
            {msg.content}
          </div>
        </div>
      );
    }

    if (msg.type === "email_card") {
      return (
        <div key={msg.id} style={{ marginBottom: "20px" }}>
          <div
            style={{
              background: "white",
              border: "2px solid #e1e4e8",
              borderRadius: "12px",
              padding: "24px",
              maxWidth: "500px",
              boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            }}
          >
            <div
              style={{
                fontSize: "18px",
                fontWeight: "600",
                marginBottom: "8px",
                color: "#24292e",
              }}
            >
              📧 Email Required
            </div>
            <div
              style={{
                marginBottom: "16px",
                color: "#586069",
                lineHeight: "1.5",
              }}
            >
              {msg.content}
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <input
                type="email"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleEmailSubmit()}
                placeholder="your.email@example.com"
                style={{
                  padding: "12px 14px",
                  borderRadius: "8px",
                  border: "2px solid #e1e4e8",
                  fontSize: "14px",
                  outline: "none",
                  transition: "border-color 0.2s",
                }}
                onFocus={(e) => (e.target.style.borderColor = "#667eea")}
                onBlur={(e) => (e.target.style.borderColor = "#e1e4e8")}
              />

              <div style={{ display: "flex", gap: "10px" }}>
                <button
                  onClick={handleEmailSubmit}
                  style={{
                    flex: 1,
                    background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                    color: "white",
                    padding: "12px 20px",
                    borderRadius: "8px",
                    border: "none",
                    fontWeight: "600",
                    cursor: "pointer",
                    transition: "transform 0.2s",
                  }}
                  onMouseOver={(e) => (e.target.style.transform = "translateY(-1px)")}
                  onMouseOut={(e) => (e.target.style.transform = "translateY(0)")}
                >
                  Submit
                </button>

                {msg.skipAllowed && (
                  <button
                    onClick={handleEmailSkip}
                    style={{
                      background: "#f6f8fa",
                      color: "#586069",
                      padding: "12px 20px",
                      borderRadius: "8px",
                      border: "1px solid #e1e4e8",
                      fontWeight: "600",
                      cursor: "pointer",
                      transition: "background 0.2s",
                    }}
                    onMouseOver={(e) => (e.target.style.background = "#e1e4e8")}
                    onMouseOut={(e) => (e.target.style.background = "#f6f8fa")}
                  >
                    Skip
                  </button>
                )}
              </div>

              {emailError && (
                <div
                  style={{
                    color: "#d73a49",
                    fontSize: "13px",
                    marginTop: "4px",
                    fontWeight: "500",
                  }}
                >
                  ⚠️ {emailError}
                </div>
              )}
            </div>
          </div>
        </div>
      );
    }

    return (
      <div key={msg.id} style={{ marginBottom: "16px" }}>
        <div
          style={{
            background: "white",
            padding: "16px 20px",
            borderRadius: "18px 18px 18px 4px",
            maxWidth: "85%",
            boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
            border: "1px solid #e1e4e8",
            wordWrap: "break-word",
          }}
        >
          <div style={{ color: "#24292e", fontSize: "15px" }}>
            {renderMarkdown(msg.content)}
          </div>

          {msg.sources && msg.sources.trim() !== "" && (
            <div
              style={{
                marginTop: "16px",
                padding: "12px 14px",
                borderTop: "2px solid #e1e4e8",
                background: "#f6f8fa",
                borderRadius: "6px",
                fontSize: "13px",
              }}
            >
              <div
                style={{
                  fontWeight: "600",
                  marginBottom: "8px",
                  color: "#24292e",
                }}
              >
                Check for more details...
              </div>
              <div style={{ color: "#586069" }}>
                {renderMarkdown(msg.sources)}
              </div>
            </div>
          )}

          {msg.streaming && (
            <div
              style={{
                fontStyle: "italic",
                color: "#959da5",
                marginTop: "8px",
                fontSize: "13px",
              }}
            >
              <span style={{ display: "inline-block", animation: "pulse 1.5s ease-in-out infinite" }}>
                ●
              </span>{" "}
              Typing…
            </div>
          )}
        </div>
      </div>
    );
  };

  // ---------------------- UI ----------------------
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "linear-gradient(to bottom, #f6f8fa, #ffffff)",
        padding: "20px",
      }}
    >
      <div
        style={{
          maxWidth: "1000px",
          margin: "0 auto",
          display: "flex",
          flexDirection: "column",
          height: "calc(100vh - 40px)",
        }}
      >
        {/* HEADER */}
        <div
          style={{
            background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            color: "white",
            padding: "24px 28px",
            borderRadius: "16px 16px 0 0",
            boxShadow: "0 4px 12px rgba(102, 126, 234, 0.3)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <img
              src="/SRMIST_Icon.png"
              alt="SRMIST_Icon"
              style={{
                width: "50px",
                height: "50px",
                objectFit: "contain",
//                background: "white",
                borderRadius: "8px",
                padding: "4px",
              }}
              onError={(e) => {
                e.target.style.display = "none";
              }}
            />
            <div>
              <h2 style={{ margin: 0, fontSize: "24px", fontWeight: "700" }}>
                SRMIST University ChatBot
              </h2>
              <div style={{ marginTop: "6px", fontSize: "14px", opacity: 0.9 }}>
                Your intelligent campus companion
              </div>
            </div>
          </div>

          <button
            onClick={clearChat}
            title="Clear Chat"
            style={{
              background: "rgba(255, 255, 255, 0.2)",
              color: "white",
              padding: "10px",
              borderRadius: "10px",
              border: "1px solid rgba(255, 255, 255, 0.3)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "all 0.2s",
              width: "40px",
              height: "40px",
            }}
            onMouseOver={(e) => {
              e.target.style.background = "rgba(255, 255, 255, 0.3)";
              e.target.style.transform = "scale(1.05)";
            }}
            onMouseOut={(e) => {
              e.target.style.background = "rgba(255, 255, 255, 0.2)";
              e.target.style.transform = "scale(1)";
            }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 6h18" />
              <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
              <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
              <line x1="10" y1="11" x2="10" y2="17" />
              <line x1="14" y1="11" x2="14" y2="17" />
            </svg>
          </button>
        </div>

        {/* MESSAGES */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            background: "white",
            border: "1px solid #e1e4e8",
            borderTop: "none",
            padding: "24px",
            minHeight: "400px",
          }}
        >
          {messages.length === 0 && (
            <div
              style={{
                textAlign: "center",
                color: "#959da5",
                marginTop: "60px",
                fontSize: "15px",
              }}
            >
              <div style={{ fontSize: "48px", marginBottom: "16px" }}>💬</div>
              <div>Start a conversation by asking a question below</div>
            </div>
          )}
          {messages.map((m) => renderMessage(m))}
          <div ref={messagesEndRef} />
        </div>

        {/* INPUT AREA */}
        <div
          style={{
            padding: "20px",
            background: "white",
            borderRadius: "0 0 16px 16px",
            border: "1px solid #e1e4e8",
            borderTop: "2px solid #e1e4e8",
            boxShadow: "0 -2px 8px rgba(0,0,0,0.04)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "8px 12px 8px 18px",
              borderRadius: "12px",
              border: "2px solid #e1e4e8",
              background: "white",
              transition: "border-color 0.2s",
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = "#667eea")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "#e1e4e8")}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
              placeholder="Ask me anything about SRMIST..."
              disabled={loading}
              style={{
                flex: 1,
                border: "none",
                outline: "none",
                fontSize: "15px",
                padding: "6px 0",
                background: "transparent",
              }}
            />
            <button
              onClick={sendMessage}
              disabled={loading}
              title="Send Message"
              style={{
                background: loading
                  ? "#959da5"
                  : "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                color: "white",
                padding: "10px",
                borderRadius: "8px",
                border: "none",
                cursor: loading ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "transform 0.2s",
                minWidth: "40px",
                minHeight: "40px",
              }}
              onMouseOver={(e) =>
                !loading && (e.target.style.transform = "scale(1.05)")
              }
              onMouseOut={(e) => (e.target.style.transform = "scale(1)")}
            >
              {loading ? (
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    animation: "spin 1s linear infinite",
                  }}
                >
                  <circle cx="12" cy="12" r="10" opacity="0.25" />
                  <path d="M12 2a10 10 0 0 1 10 10" />
                </svg>
              ) : (
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {/* FOOTER */}
        <div
          style={{
            marginTop: "16px",
            padding: "16px",
            background: "white",
            borderRadius: "12px",
            border: "1px solid #e1e4e8",
            textAlign: "center",
            fontSize: "13px",
            color: "#586069",
            lineHeight: 1.6,
          }}
        >
          <div>This chatbot is experimental and accuracy may vary.</div>
          <div style={{ fontWeight: "600", marginTop: "4px", color: "#24292e" }}>
            Developed by SRMTech | Built for SRMIST University
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        @media (max-width: 768px) {
          body {
            padding: 10px;
          }
        }
      `}</style>
    </div>
  );
}

export default App;

