import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm"; // 표, 체크리스트 등 GitHub 스타일 마크다운 지원
import rehypeHighlight from "rehype-highlight"; // 코드블록 문법 하이라이트
import "highlight.js/styles/github-dark.css"; // 하이라이트 다크 테마

// 백엔드 주소. .env(VITE_API_URL)로 바꿀 수 있고, 없으면 로컬 기본값을 쓴다.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  // conversations: 사이드바에 보여줄 대화 목록 [{ id, title }, ...]
  const [conversations, setConversations] = useState([]);
  // activeId: 현재 열려있는 대화의 id (null이면 "새 대화" 상태)
  const [activeId, setActiveId] = useState(null);
  // messages: 현재 대화의 메시지 [{ role, content }, ...]
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // models: 선택 가능한 모델 목록, selectedModel: 현재 선택된 모델 id
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState("");
  // 제목 편집 상태: editingId = 편집 중인 대화 id(없으면 null), editingText = 입력값
  const [editingId, setEditingId] = useState(null);
  const [editingText, setEditingText] = useState("");

  // 새 메시지가 추가되면 맨 아래로 스크롤
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // 앱이 처음 뜰 때 대화 목록과 모델 목록을 불러온다.
  useEffect(() => {
    loadConversations();
    loadModels();
  }, []);

  // --- API 호출 함수들 -------------------------------------------------------

  async function loadConversations() {
    try {
      const res = await fetch(`${API_URL}/conversations`);
      setConversations(await res.json());
    } catch {
      // 백엔드가 아직 안 떠 있을 수 있으니 조용히 무시
    }
  }

  async function loadModels() {
    try {
      const res = await fetch(`${API_URL}/models`);
      const data = await res.json(); // { models: [...], default }
      setModels(data.models);
      setSelectedModel(data.default); // 처음엔 기본 모델 선택
    } catch {
      // 무시
    }
  }

  // 사이드바에서 대화를 클릭하면 그 대화의 메시지를 불러온다.
  async function selectConversation(id) {
    setActiveId(id);
    try {
      const res = await fetch(`${API_URL}/conversations/${id}/messages`);
      setMessages(await res.json());
    } catch {
      setMessages([]);
    }
  }

  // "새 대화" 버튼: 화면만 비운다. 실제 대화방은 첫 메시지를 보낼 때 백엔드가 만든다.
  function startNewChat() {
    setActiveId(null);
    setMessages([]);
    setInput("");
  }

  // 새 대화의 제목을 모델로 자동 생성하고, 끝나면 사이드바를 갱신한다.
  async function generateTitle(id) {
    try {
      await fetch(`${API_URL}/conversations/${id}/title`, { method: "POST" });
    } catch {
      // 제목 생성 실패는 치명적이지 않으니 무시 (기본 제목 유지)
    } finally {
      loadConversations();
    }
  }

  // 제목 편집 시작 (✏️ 클릭): 해당 대화를 편집 모드로 전환
  function startEdit(c, e) {
    e.stopPropagation(); // 대화 선택으로 번지지 않게
    setEditingId(c.id);
    setEditingText(c.title);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditingText("");
  }

  // 수정된 제목 저장 (PATCH)
  async function saveEdit(id) {
    const title = editingText.trim();
    // 비었거나 그대로면 저장 없이 종료
    if (!title) return cancelEdit();
    try {
      await fetch(`${API_URL}/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    } catch {
      // 무시
    } finally {
      cancelEdit();
      loadConversations();
    }
  }

  // 편집 입력창의 키 입력 처리: Enter=저장, Esc=취소
  function onEditKeyDown(id, e) {
    if (e.key === "Enter") saveEdit(id);
    else if (e.key === "Escape") cancelEdit();
  }

  async function deleteConversation(id, e) {
    e.stopPropagation(); // 삭제 버튼 클릭이 대화 선택으로 번지지 않게
    if (!confirm("이 대화를 삭제할까요?")) return;
    await fetch(`${API_URL}/conversations/${id}`, { method: "DELETE" });
    if (id === activeId) startNewChat(); // 보고 있던 대화면 화면 비우기
    loadConversations();
  }

  // --- 메시지 전송 (스트리밍) -------------------------------------------------
  async function sendMessage(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    // 내 메시지 + 비어있는 봇 메시지(여기에 토큰을 이어붙일 것)를 함께 추가
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "bot", content: "" },
    ]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          conversation_id: activeId,
          model: selectedModel, // 선택한 모델 전달
        }),
      });

      if (!res.ok) throw new Error(await res.text());

      // 백엔드가 헤더로 알려준 대화 ID (새 대화면 여기서 처음 알게 됨)
      const newId = Number(res.headers.get("X-Conversation-Id"));

      // 응답 본문을 스트림으로 읽으며 마지막 봇 메시지에 이어붙인다.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let acc = ""; // 지금까지 받은 전체 텍스트

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        acc += decoder.decode(value, { stream: true });
        // messages의 마지막 항목(봇 메시지)만 갱신 → 타이핑 효과
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { role: "bot", content: acc };
          return next;
        });
      }

      // 새 대화였다면 id 활성화 + 제목 자동 생성(끝나면 사이드바 갱신)
      if (activeId === null && newId) {
        setActiveId(newId);
        generateTitle(newId);
      }
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { role: "bot", content: `⚠️ 오류: ${err.message}` };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  // --- 화면 -----------------------------------------------------------------
  return (
    <div className="app">
      {/* 왼쪽: 대화 목록 사이드바 */}
      <aside className="sidebar">
        <button className="new-chat" onClick={startNewChat}>
          + 새 대화
        </button>
        <div className="convo-list">
          {conversations.map((c) =>
            editingId === c.id ? (
              // 편집 모드: 인라인 입력창
              <div key={c.id} className="convo-item editing">
                <input
                  className="convo-edit-input"
                  value={editingText}
                  autoFocus
                  onChange={(e) => setEditingText(e.target.value)}
                  onKeyDown={(e) => onEditKeyDown(c.id, e)}
                  onBlur={() => saveEdit(c.id)}
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            ) : (
              <div
                key={c.id}
                className={`convo-item ${c.id === activeId ? "active" : ""}`}
                onClick={() => selectConversation(c.id)}
              >
                <span className="convo-title">{c.title || "새 대화"}</span>
                <span className="convo-actions">
                  <button
                    className="convo-btn"
                    onClick={(e) => startEdit(c, e)}
                    title="제목 수정"
                  >
                    ✏️
                  </button>
                  <button
                    className="convo-btn convo-delete"
                    onClick={(e) => deleteConversation(c.id, e)}
                    title="삭제"
                  >
                    ×
                  </button>
                </span>
              </div>
            )
          )}
        </div>
      </aside>

      {/* 오른쪽: 채팅 영역 */}
      <main className="chat-container">
        <header className="chat-header">
          <h1>🤗 HF Chat Lab</h1>
          {/* 모델 선택 드롭다운 */}
          <select
            className="model-select"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={loading}
            title="사용할 모델 선택"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </header>

        <div className="messages">
          {messages.length === 0 && (
            <p className="empty">메시지를 입력해 대화를 시작해보세요.</p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`message ${m.role}`}>
              {m.role === "bot" ? (
                // 봇 응답은 마크다운으로 렌더링 (코드블록/목록/표 등)
                m.content ? (
                  <div className="markdown">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeHighlight]}
                    >
                      {m.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  // 스트리밍 중 아직 내용이 없으면 깜빡이는 표시
                  <span className="typing">…</span>
                )
              ) : (
                // 사용자 입력은 안전하게 평문으로 표시
                m.content
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form className="input-row" onSubmit={sendMessage}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="메시지를 입력하세요…"
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()}>
            전송
          </button>
        </form>
      </main>
    </div>
  );
}
