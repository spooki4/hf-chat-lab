import { useState } from "react";
import "./Login.css";

// 백엔드 주소 (App.jsx와 동일 규칙)
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * 로그인 / 회원가입 화면.
 * 로그인(또는 가입)에 성공하면 백엔드가 준 토큰을 onAuth(token, email)로 부모에 올려준다.
 * 부모(App)는 그 토큰을 저장하고 채팅 화면으로 전환한다.
 */
export default function Login({ onAuth }) {
  // mode: "login"(로그인) 또는 "register"(회원가입). 한 화면에서 토글한다.
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  async function handleSubmit(e) {
    e.preventDefault();
    if (busy) return;
    setError("");
    setBusy(true);

    try {
      // 모드에 따라 로그인/회원가입 엔드포인트 선택
      const path = isLogin ? "/auth/login" : "/auth/register";
      const res = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();
      if (!res.ok) {
        // 백엔드가 detail에 한국어 에러 메시지를 담아준다.
        throw new Error(data.detail || "요청에 실패했습니다.");
      }

      // 성공: { access_token, token_type, email } → 부모로 전달
      onAuth(data.access_token, data.email);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // 로그인 ↔ 회원가입 전환 (입력값/에러 초기화)
  function toggleMode() {
    setMode(isLogin ? "register" : "login");
    setError("");
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>🤗 HF Chat Lab</h1>
        <p className="login-sub">
          {isLogin ? "로그인하고 내 대화를 이어가세요." : "새 계정을 만들어 시작하세요."}
        </p>

        <input
          type="email"
          placeholder="이메일"
          value={email}
          autoComplete="username"
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="비밀번호 (4자 이상)"
          value={password}
          autoComplete={isLogin ? "current-password" : "new-password"}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {/* 에러 메시지 (있을 때만) */}
        {error && <p className="login-error">⚠️ {error}</p>}

        <button type="submit" disabled={busy}>
          {busy ? "처리 중…" : isLogin ? "로그인" : "회원가입"}
        </button>

        <p className="login-toggle">
          {isLogin ? "계정이 없으신가요?" : "이미 계정이 있으신가요?"}{" "}
          <button type="button" className="link-btn" onClick={toggleMode}>
            {isLogin ? "회원가입" : "로그인"}
          </button>
        </p>
      </form>
    </div>
  );
}
