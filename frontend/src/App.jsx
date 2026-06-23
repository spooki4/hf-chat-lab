import { useState, useRef, useEffect } from "react";
import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm"; // 표, 체크리스트 등 GitHub 스타일 마크다운 지원
import rehypeHighlight from "rehype-highlight"; // 코드블록 문법 하이라이트
import "highlight.js/styles/github-dark.css"; // 하이라이트 다크 테마
import Login from "./Login"; // 로그인/회원가입 화면
import AdminPage from "./AdminPage"; // 관리자 페이지(사용자 관리 등)
import MyPage from "./MyPage"; // 마이페이지(정보변경 등)
import ModelPicker from "./ModelPicker"; // 모델 선택 모달(검색 + 단일 선택)

// 백엔드 주소. .env(VITE_API_URL)로 바꿀 수 있고, 없으면 로컬 기본값을 쓴다.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// DB의 시각 문자열은 타임존 표기가 없는 UTC다. JS Date가 로컬로 오해하지 않도록
// 표기가 없으면 'Z'(UTC)를 붙여 해석한다. (클라이언트가 찍은 ISO는 이미 Z 포함)
function toDate(iso) {
  if (!iso) return null;
  const hasTz = /[zZ]|[+-]\d\d:?\d\d$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

// 메시지 아래 표기용: "06-18 17:35"
function formatMsgTime(iso) {
  const d = toDate(iso);
  if (!d || isNaN(d)) return "";
  return d.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// 사이드바 대화 옆 표기용: 오늘이면 "17:35", 아니면 "06-18"
function formatConvoTime(iso) {
  const d = toDate(iso);
  if (!d || isNaN(d)) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  return d.toLocaleString("ko-KR", sameDay
    ? { hour: "2-digit", minute: "2-digit" }
    : { month: "2-digit", day: "2-digit" });
}

// 로그인 토큰을 브라우저에 저장할 때 쓰는 key (새로고침해도 로그인 유지)
const TOKEN_KEY = "hf_chat_token";

// 맥이면 ⌘(Command), 그 외(윈도우/리눅스)면 Ctrl 키로 전송하도록 안내 문구를 바꾼다.
const IS_MAC =
  typeof navigator !== "undefined" &&
  /Mac|iP(hone|ad|od)/.test(navigator.platform || navigator.userAgent || "");
// 입력창 아래에 보여줄 단축키 안내 (처음 쓰는 사용자를 위한 작은 설명)
const SUBMIT_HINT = IS_MAC
  ? "⌘ + Enter 전송 · Enter 줄바꿈"
  : "Ctrl + Enter 전송 · Enter 줄바꿈";

export default function App() {
  // token: 로그인 토큰(JWT). 없으면 로그인 화면을 보여준다. (localStorage에서 초기화)
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
  // userEmail: 현재 로그인한 사용자 이메일 (사이드바 표시용)
  const [userEmail, setUserEmail] = useState("");
  // userName: 현재 로그인한 사용자 이름 (사이드바에 이메일과 함께 표시)
  const [userName, setUserName] = useState("");
  // userRole: 현재 사용자 권한("admin" | "user"). 관리 메뉴 노출 판단에 사용.
  const [userRole, setUserRole] = useState("user");
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
  // copiedIndex: 방금 '복사됨 ✓'을 보여줄 메시지의 인덱스 (없으면 null)
  const [copiedIndex, setCopiedIndex] = useState(null);
  // search: 대화 제목 검색어 (사이드바 필터)
  const [search, setSearch] = useState("");
  // modelPickerOpen: 모델 선택 모달 표시 여부
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  // sidebarOpen: (모바일) 대화 목록 사이드바를 열었는지. 데스크톱에선 항상 보이므로 무관.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 페이지 이동용(관리자 페이지 등)
  const navigate = useNavigate();

  // 입력창(textarea) DOM 참조 — 입력 내용에 맞춰 높이를 자동 조절하는 데 사용
  const inputRef = useRef(null);

  // 새 메시지가 추가되면 맨 아래로 스크롤
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // 입력 내용에 맞춰 textarea 높이를 자동으로 늘렸다 줄인다(최대 높이까지).
  // 전송 후 input이 ""로 비워지면 다시 한 줄 높이로 돌아온다.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto"; // 먼저 줄였다가
    el.style.height = Math.min(el.scrollHeight, 160) + "px"; // 내용 높이만큼(최대 160px)
  }, [input]);

  // 로그인 상태(token)가 생기면: 토큰 유효성 확인 + 대화/모델 목록 로드.
  // (새로고침으로 localStorage 토큰만 남아있는 경우에도 여기서 검증한다)
  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error("토큰 만료");
        const u = await res.json();
        setUserEmail(u.email);
        setUserName(u.name || "");
        setUserRole(u.role);
        loadConversations();
        loadModels();
      } catch {
        handleLogout(); // 토큰이 만료/무효면 로그아웃 처리
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // --- 인증 헬퍼 -------------------------------------------------------------

  // 로그인 성공 시: 토큰을 저장하고 화면을 채팅으로 전환한다.
  function handleAuth(newToken, email, role) {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
    setUserEmail(email);
    setUserRole(role || "user");
  }

  // 로그아웃: 토큰을 지우고 모든 화면 상태를 초기화한다.
  function handleLogout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setUserEmail("");
    setUserName("");
    setUserRole("user");
    setConversations([]);
    setMessages([]);
    setActiveId(null);
  }

  // 인증이 필요한 API 호출용 공용 래퍼.
  // - 자동으로 Authorization 헤더를 붙인다.
  // - 토큰이 만료/무효(401)면 자동 로그아웃시킨다.
  async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) {
      handleLogout();
      throw new Error("로그인이 필요합니다. 다시 로그인해 주세요.");
    }
    return res;
  }

  // --- API 호출 함수들 -------------------------------------------------------

  async function loadConversations() {
    try {
      const res = await apiFetch("/conversations");
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
    setSidebarOpen(false); // (모바일) 대화를 고르면 사이드바를 닫는다
    try {
      const res = await apiFetch(`/conversations/${id}/messages`);
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
    setSidebarOpen(false); // (모바일) 새 대화를 시작하면 사이드바를 닫는다
  }

  // 새 대화의 제목을 모델로 자동 생성하고, 끝나면 사이드바를 갱신한다.
  async function generateTitle(id) {
    try {
      await apiFetch(`/conversations/${id}/title`, { method: "POST" });
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
      await apiFetch(`/conversations/${id}`, {
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
    await apiFetch(`/conversations/${id}`, { method: "DELETE" });
    if (id === activeId) startNewChat(); // 보고 있던 대화면 화면 비우기
    loadConversations();
  }

  // --- 스트림 읽기 공용 헬퍼 --------------------------------------------------
  // 응답 본문을 토큰 단위로 읽으며 messages의 '마지막 봇 말풍선'에 이어붙인다.
  // (전송/재생성 두 곳에서 같은 방식으로 화면을 갱신하므로 함수로 분리)
  async function readStreamIntoLastBubble(res) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let acc = ""; // 지금까지 받은 전체 텍스트
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      acc += decoder.decode(value, { stream: true });
      // messages의 마지막 항목(봇 메시지)만 갱신 → 타이핑 효과
      // (시각/모델 등 기존 메타는 유지하고 content만 교체)
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], content: acc };
        return next;
      });
    }
    return acc;
  }

  // --- 메시지 전송 (스트리밍) -------------------------------------------------
  async function sendMessage(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    // 내 메시지 + 비어있는 봇 메시지(여기에 토큰을 이어붙일 것)를 함께 추가.
    // 시각은 지금(클라이언트), 봇 메시지에는 사용한 모델을 함께 기록한다.
    const nowIso = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, created_at: nowIso },
      { role: "bot", content: "", model: selectedModel, created_at: nowIso },
    ]);
    setInput("");
    setLoading(true);

    try {
      const res = await apiFetch("/chat/stream", {
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
      await readStreamIntoLastBubble(res);

      // 새 대화였다면 id 활성화 + 제목 자동 생성(끝나면 사이드바 갱신).
      // 기존 대화면 최근활동 시각/정렬이 바뀌었으니 목록을 새로 불러온다.
      if (activeId === null && newId) {
        setActiveId(newId);
        generateTitle(newId);
      } else {
        loadConversations();
      }
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          ...next[next.length - 1],
          content: `⚠️ 오류: ${err.message}`,
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  // 입력창 키 처리:
  //   ⌘/Ctrl + Enter → 전송 (PC에서 Enter만으로 실수 전송되는 불편 해소)
  //   그냥 Enter      → 줄바꿈 (textarea 기본 동작 그대로)
  function onInputKeyDown(e) {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendMessage(e);
    }
  }

  // --- 메시지 복사 -----------------------------------------------------------
  // 봇 응답 원문(마크다운 그대로)을 클립보드에 복사하고, 잠깐 '복사됨 ✓'을 보여준다.
  async function copyMessage(content, index) {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      // 1.5초 뒤 표시 해제 (그 사이 다른 메시지를 복사했으면 그대로 둔다)
      setTimeout(
        () => setCopiedIndex((cur) => (cur === index ? null : cur)),
        1500
      );
    } catch {
      // clipboard API는 보안 컨텍스트(https/localhost)에서만 동작 → 실패 시 조용히 무시
    }
  }

  // --- 응답 재생성 -----------------------------------------------------------
  // 마지막 봇 답변을 버리고 같은 질문으로 다시 생성한다. (백엔드가 마지막 봇 메시지를 삭제 후 재호출)
  async function regenerate() {
    if (loading || activeId === null) return;

    // 화면의 마지막 봇 말풍선을 비워 새 응답을 받을 자리로 만든다.
    // 재생성도 '지금/현재 선택한 모델'로 기록을 갱신한다.
    const nowIso = new Date().toISOString();
    setMessages((prev) => {
      const next = [...prev];
      if (next.length && next[next.length - 1].role === "bot") {
        next[next.length - 1] = {
          role: "bot",
          content: "",
          model: selectedModel,
          created_at: nowIso,
        };
      }
      return next;
    });
    setLoading(true);

    try {
      const res = await apiFetch("/chat/stream/regenerate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: activeId,
          model: selectedModel, // 같은(현재 선택된) 모델로 재생성
        }),
      });

      if (!res.ok) throw new Error(await res.text());
      await readStreamIntoLastBubble(res);
      loadConversations(); // 최근활동 시각/정렬 갱신
    } catch (err) {
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          ...next[next.length - 1],
          content: `⚠️ 오류: ${err.message}`,
        };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  // --- 화면 -----------------------------------------------------------------

  // 로그인하지 않았으면 채팅 대신 로그인/회원가입 화면을 보여준다.
  if (!token) {
    return <Login onAuth={handleAuth} />;
  }

  // 제목 검색: 입력이 있으면 제목에 포함된 대화만 보여준다(대소문자 무시).
  const q = search.trim().toLowerCase();
  const filteredConversations = q
    ? conversations.filter((c) => (c.title || "").toLowerCase().includes(q))
    : conversations;

  // 모델 선택 버튼에 표시할 현재 모델 이름
  const selectedModelLabel =
    models.find((m) => m.id === selectedModel)?.label || selectedModel || "모델 선택";

  // 채팅 화면(라우트 "/"). 아래 Routes에서 다른 페이지와 함께 분기한다.
  const chatScreen = (
    <div className="app">
      {/* (모바일) 사이드바가 열렸을 때 뒤를 덮는 반투명 배경 — 누르면 닫힌다 */}
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 왼쪽: 대화 목록 사이드바 (모바일에선 슬라이드로 열고 닫는다) */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <button className="new-chat" onClick={startNewChat}>
          + 새 대화
        </button>

        {/* 대화 제목 검색 */}
        <div className="convo-search">
          <input
            type="text"
            placeholder="🔍 제목 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {search && (
            <button
              className="convo-search-clear"
              onClick={() => setSearch("")}
              title="검색 지우기"
            >
              ×
            </button>
          )}
        </div>

        <div className="convo-list">
          {filteredConversations.length === 0 && (
            <p className="convo-empty">
              {conversations.length === 0 ? "대화가 없습니다." : "검색 결과가 없습니다."}
            </p>
          )}
          {filteredConversations.map((c) =>
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
                <div className="convo-main">
                  <span className="convo-title">{c.title || "새 대화"}</span>
                  <span className="convo-time">{formatConvoTime(c.updated_at)}</span>
                </div>
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

        {/* 사이드바 하단: 로그인한 사용자 정보 + 메뉴/로그아웃 */}
        <div className="user-bar">
          {/* 이름(굵게) + 이메일(작게) */}
          <div className="user-info">
            <span className="user-name">{userName || userEmail}</span>
            {userName && (
              <span className="user-email" title={userEmail}>
                {userEmail}
              </span>
            )}
          </div>
          <div className="user-actions">
            {/* 모든 사용자: 마이페이지 진입 버튼 */}
            <button
              className="nav-btn"
              onClick={() => navigate("/me")}
              title="마이페이지"
            >
              👤 마이
            </button>
            {/* 관리자에게만 보이는 관리 페이지 진입 버튼 */}
            {userRole === "admin" && (
              <button
                className="nav-btn"
                onClick={() => navigate("/admin")}
                title="관리 페이지"
              >
                🛠 관리
              </button>
            )}
            <button className="logout-btn" onClick={handleLogout} title="로그아웃">
              🚪 로그아웃
            </button>
          </div>
        </div>
      </aside>

      {/* 오른쪽: 채팅 영역 */}
      <main className="chat-container">
        <header className="chat-header">
          {/* (모바일 전용) 대화 목록 열기 버튼 */}
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen(true)}
            title="대화 목록 열기"
            aria-label="대화 목록 열기"
          >
            ☰
          </button>
          <h1>🤗 HF Chat Lab</h1>
          {/* 모델 선택: 버튼을 누르면 검색 가능한 모달이 열린다(모델이 많아서) */}
          <button
            className="model-button"
            onClick={() => setModelPickerOpen(true)}
            disabled={loading}
            title="사용할 모델 선택"
          >
            <span className="model-button-label">{selectedModelLabel}</span>
            <span className="model-button-caret">▾</span>
          </button>
        </header>

        <div className="messages">
          {messages.length === 0 && (
            <p className="empty">메시지를 입력해 대화를 시작해보세요.</p>
          )}
          {messages.map((m, i) => {
            const isLast = i === messages.length - 1; // 마지막 메시지인지
            const time = formatMsgTime(m.created_at);
            return (
              <div key={i} className={`message ${m.role}`}>
                {m.role === "bot" ? (
                  // 봇 응답은 마크다운으로 렌더링 (코드블록/목록/표 등)
                  m.content ? (
                    <>
                      <div className="markdown">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          rehypePlugins={[rehypeHighlight]}
                        >
                          {m.content}
                        </ReactMarkdown>
                      </div>
                      {/* 봇 메시지 도구모음: 복사 + (마지막 답변에만) 재생성 */}
                      <div className="msg-actions">
                        <button
                          className="msg-btn"
                          onClick={() => copyMessage(m.content, i)}
                          title="응답 복사"
                        >
                          {copiedIndex === i ? "복사됨 ✓" : "📋 복사"}
                        </button>
                        {/* 마지막 봇 답변이고, 스트리밍 중이 아니며, 저장된 대화일 때만 재생성 */}
                        {isLast && !loading && activeId !== null && (
                          <button
                            className="msg-btn"
                            onClick={regenerate}
                            title="같은 질문으로 다시 생성"
                          >
                            🔄 재생성
                          </button>
                        )}
                      </div>
                    </>
                  ) : (
                    // 스트리밍 중 아직 내용이 없으면 깜빡이는 표시
                    <span className="typing">…</span>
                  )
                ) : (
                  // 사용자 입력은 안전하게 평문으로 표시
                  m.content
                )}

                {/* 메시지 아래 메타: 시각 + (봇이면) 사용한 모델 */}
                {m.content && (
                  <div className="msg-meta">
                    {time && <span className="msg-time">{time}</span>}
                    {m.role === "bot" && m.model && (
                      <span className="msg-model" title={m.model}>
                        🤖 {m.model}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={sendMessage}>
          <div className="input-row">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="메시지를 입력하세요…"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>
              전송
            </button>
          </div>
          {/* 처음 쓰는 사용자를 위한 단축키 안내 (OS에 맞춰 ⌘ 또는 Ctrl 표시) */}
          <div className="input-hint">{SUBMIT_HINT}</div>
        </form>
      </main>

      {/* 모델 선택 모달 (검색 + 단일 선택) */}
      {modelPickerOpen && (
        <ModelPicker
          models={models}
          value={selectedModel}
          onSelect={(id) => {
            setSelectedModel(id);
            setModelPickerOpen(false);
          }}
          onClose={() => setModelPickerOpen(false)}
        />
      )}
    </div>
  );

  // URL에 따라 화면 분기:
  //   "/"        → 채팅
  //   "/admin/*" → 관리자 페이지(관리자만, 아니면 채팅으로 되돌림)
  //   그 외       → 채팅으로
  return (
    <Routes>
      <Route path="/" element={chatScreen} />
      <Route
        path="/admin/*"
        element={
          userRole === "admin" ? (
            <AdminPage apiFetch={apiFetch} currentEmail={userEmail} />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />
      <Route path="/me/*" element={<MyPage apiFetch={apiFetch} />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
