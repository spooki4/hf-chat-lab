import { useState } from "react";
import "./Login.css";

// 백엔드 주소 (App.jsx와 동일 규칙)
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * 로그인 / 회원가입 화면.
 * - 로그인 성공: 백엔드가 준 토큰을 onAuth(token, email, role)로 부모에 올려준다.
 * - 회원가입 성공: 토큰을 주지 않는다(승인 대기). 안내 메시지를 띄우고 로그인 모드로 전환.
 */
export default function Login({ onAuth }) {
  // mode: "login"(로그인) 또는 "register"(회원가입). 한 화면에서 토글한다.
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(""); // 성공/안내 메시지(가입 접수 등)
  const [busy, setBusy] = useState(false);

  const isLogin = mode === "login";

  async function handleSubmit(e) {
    e.preventDefault();
    if (busy) return;
    setError("");
    setNotice("");

    // 회원가입 시 비밀번호 확인 일치 검사(오타 방지)
    if (!isLogin && password !== confirmPassword) {
      setError("비밀번호 확인이 일치하지 않습니다.");
      return;
    }

    setBusy(true);

    try {
      // 모드에 따라 로그인/회원가입 엔드포인트 + 본문 선택
      const path = isLogin ? "/auth/login" : "/auth/register";
      const body = isLogin
        ? { email, password }
        : { email, password, name, phone: phone || null };
      const res = await fetch(`${API_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();
      if (!res.ok) {
        // 백엔드가 detail에 한국어 에러 메시지를 담아준다.
        throw new Error(data.detail || "요청에 실패했습니다.");
      }

      if (isLogin) {
        // 로그인 성공: { access_token, token_type, email, role } → 부모로 전달
        onAuth(data.access_token, data.email, data.role);
      } else {
        // 회원가입 성공: { status, message } → 안내 후 로그인 화면으로
        setMode("login");
        setPassword("");
        setConfirmPassword("");
        setNotice(data.message || "가입 신청이 접수되었습니다.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // 로그인 ↔ 회원가입 전환 (에러/안내 초기화)
  function toggleMode() {
    setMode(isLogin ? "register" : "login");
    setError("");
    setNotice("");
    setConfirmPassword("");
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

        {/* 회원가입 모드에서만 비밀번호 확인 + 이름/연락처 입력 */}
        {!isLogin && (
          <>
            <input
              type="password"
              placeholder="비밀번호 확인"
              value={confirmPassword}
              autoComplete="new-password"
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
            <input
              type="text"
              placeholder="이름"
              value={name}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
              required
            />
            <input
              type="tel"
              placeholder="연락처 (선택)"
              value={phone}
              autoComplete="tel"
              onChange={(e) => setPhone(e.target.value)}
            />
          </>
        )}

        {/* 에러 / 안내 메시지 (있을 때만) */}
        {error && <p className="login-error">⚠️ {error}</p>}
        {notice && <p className="login-notice">✅ {notice}</p>}

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
