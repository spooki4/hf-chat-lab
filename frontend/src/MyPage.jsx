import { useEffect, useState } from "react";
import { NavLink, Routes, Route, Navigate, Link } from "react-router-dom";
import MyUsagePanel from "./MyUsagePanel";
import "./MyPage.css";

/**
 * 마이페이지의 '틀' (관리자 페이지와 같은 사이드 탭 구조).
 * 왼쪽: 메뉴(나중에 '토큰 사용량' 등 추가 예정), 오른쪽: 선택한 메뉴 내용.
 *
 * props:
 *   apiFetch - 인증 헤더가 자동으로 붙는 fetch 래퍼(App에서 내려줌)
 */
export default function MyPage({ apiFetch }) {
  return (
    <div className="mypage">
      <aside className="mypage-nav">
        <div className="mypage-nav-top">
          <Link to="/" className="mypage-back">
            ← 채팅으로
          </Link>
          <h2 className="mypage-title">👤 마이페이지</h2>
        </div>
        <nav className="mypage-menu">
          <NavLink to="/me/profile" className="mypage-menu-item">
            ⚙️ 정보변경
          </NavLink>
          <NavLink to="/me/usage" className="mypage-menu-item">
            📊 토큰 사용량
          </NavLink>
        </nav>
      </aside>

      <main className="mypage-content">
        <Routes>
          <Route index element={<Navigate to="/me/profile" replace />} />
          <Route path="profile" element={<ProfilePanel apiFetch={apiFetch} />} />
          <Route path="usage" element={<MyUsagePanel apiFetch={apiFetch} />} />
          <Route path="*" element={<Navigate to="/me/profile" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/**
 * 정보변경 패널: 이름/연락처 수정 + 비밀번호 변경.
 */
function ProfilePanel({ apiFetch }) {
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");

  // 프로필(이름/연락처) 저장 상태
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState("");
  const [profileErr, setProfileErr] = useState("");

  // 비밀번호 변경 입력/상태
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [savingPw, setSavingPw] = useState(false);
  const [pwMsg, setPwMsg] = useState("");
  const [pwErr, setPwErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch("/auth/me");
        if (!res.ok) throw new Error();
        const u = await res.json();
        setEmail(u.email);
        setName(u.name || "");
        setPhone(u.phone || "");
      } catch {
        setProfileErr("내 정보를 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveProfile(e) {
    e.preventDefault();
    if (savingProfile) return;
    setProfileMsg("");
    setProfileErr("");
    if (!name.trim()) {
      setProfileErr("이름을 입력하세요.");
      return;
    }
    setSavingProfile(true);
    try {
      const res = await apiFetch("/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), phone: phone.trim() || null }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "저장에 실패했습니다.");
      setName(data.name || "");
      setPhone(data.phone || "");
      setProfileMsg("저장되었습니다.");
    } catch (err) {
      setProfileErr(err.message);
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword(e) {
    e.preventDefault();
    if (savingPw) return;
    setPwMsg("");
    setPwErr("");
    if (!curPw || !newPw) {
      setPwErr("현재 비밀번호와 새 비밀번호를 입력하세요.");
      return;
    }
    if (newPw.length < 4) {
      setPwErr("새 비밀번호는 4자 이상이어야 합니다.");
      return;
    }
    if (newPw !== confirmPw) {
      setPwErr("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setSavingPw(true);
    try {
      const res = await apiFetch("/auth/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: curPw, new_password: newPw }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "변경에 실패했습니다.");
      setCurPw("");
      setNewPw("");
      setConfirmPw("");
      setPwMsg("비밀번호가 변경되었습니다.");
    } catch (err) {
      setPwErr(err.message);
    } finally {
      setSavingPw(false);
    }
  }

  if (loading) return <p className="mypage-loading">불러오는 중…</p>;

  return (
    <div className="profile-panel">
      <h3 className="panel-h">정보변경</h3>

      {/* 1) 기본 정보 */}
      <form className="profile-card" onSubmit={saveProfile}>
        <h4>기본 정보</h4>

        <label className="field">
          <span>이메일</span>
          <input type="email" value={email} disabled title="이메일은 변경할 수 없습니다." />
        </label>

        <label className="field">
          <span>이름</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="이름"
          />
        </label>

        <label className="field">
          <span>연락처</span>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="연락처 (선택)"
          />
        </label>

        {profileErr && <p className="form-error">⚠️ {profileErr}</p>}
        {profileMsg && <p className="form-ok">✅ {profileMsg}</p>}

        <button type="submit" disabled={savingProfile}>
          {savingProfile ? "저장 중…" : "저장"}
        </button>
      </form>

      {/* 2) 비밀번호 변경 */}
      <form className="profile-card" onSubmit={changePassword}>
        <h4>비밀번호 변경</h4>

        <label className="field">
          <span>현재 비밀번호</span>
          <input
            type="password"
            value={curPw}
            autoComplete="current-password"
            onChange={(e) => setCurPw(e.target.value)}
          />
        </label>

        <label className="field">
          <span>새 비밀번호</span>
          <input
            type="password"
            value={newPw}
            autoComplete="new-password"
            onChange={(e) => setNewPw(e.target.value)}
            placeholder="4자 이상"
          />
        </label>

        <label className="field">
          <span>새 비밀번호 확인</span>
          <input
            type="password"
            value={confirmPw}
            autoComplete="new-password"
            onChange={(e) => setConfirmPw(e.target.value)}
          />
        </label>

        {pwErr && <p className="form-error">⚠️ {pwErr}</p>}
        {pwMsg && <p className="form-ok">✅ {pwMsg}</p>}

        <button type="submit" disabled={savingPw}>
          {savingPw ? "변경 중…" : "비밀번호 변경"}
        </button>
      </form>
    </div>
  );
}
