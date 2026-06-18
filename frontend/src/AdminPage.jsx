import { useEffect, useState } from "react";
import { NavLink, Routes, Route, Navigate, Link } from "react-router-dom";
import AdminUsagePanel from "./AdminUsagePanel";
import "./AdminPage.css";

/**
 * 관리자 페이지의 '틀'.
 * 왼쪽: 관리 메뉴(사이드 탭) — 나중에 메뉴를 늘려나갈 수 있는 구조.
 * 오른쪽: 선택한 메뉴의 내용(중첩 라우트로 분기).
 *
 * props:
 *   apiFetch     - 인증 헤더가 자동으로 붙는 fetch 래퍼(App에서 내려줌)
 *   currentEmail - 현재 로그인한 관리자 이메일(자기 자신 행 구분용)
 */
export default function AdminPage({ apiFetch, currentEmail }) {
  return (
    <div className="admin-page">
      <aside className="admin-nav">
        <div className="admin-nav-top">
          <Link to="/" className="admin-back">
            ← 채팅으로
          </Link>
          <h2 className="admin-title">🛠 관리</h2>
        </div>
        <nav className="admin-menu">
          <NavLink to="/admin/users" className="admin-menu-item">
            👥 사용자 관리
          </NavLink>
          <NavLink to="/admin/usage" className="admin-menu-item">
            📊 토큰 사용량
          </NavLink>
        </nav>
      </aside>

      <main className="admin-content">
        <Routes>
          {/* /admin 으로 들어오면 기본으로 사용자 관리로 보낸다 */}
          <Route index element={<Navigate to="/admin/users" replace />} />
          <Route
            path="users"
            element={<UsersPanel apiFetch={apiFetch} currentEmail={currentEmail} />}
          />
          <Route path="usage" element={<AdminUsagePanel apiFetch={apiFetch} />} />
          <Route path="*" element={<Navigate to="/admin/users" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// 상태/권한을 한글 라벨 + 색상 클래스로 변환
const STATUS_LABEL = { pending: "승인 대기", approved: "승인됨", rejected: "거부됨" };
const ROLE_LABEL = { admin: "관리자", user: "일반" };

/**
 * 사용자 관리 패널: 전체 사용자 목록 + 승인/거부/권한변경/삭제.
 */
function UsersPanel({ apiFetch, currentEmail }) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null); // 처리 중인 행(버튼 중복 클릭 방지)

  async function load() {
    setError("");
    try {
      const res = await apiFetch("/admin/users");
      if (!res.ok) throw new Error("목록을 불러오지 못했습니다.");
      setUsers(await res.json());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 권한/상태 변경 (PATCH). patch = { role } 또는 { status }
  async function updateUser(id, patch) {
    setBusyId(id);
    setError("");
    try {
      const res = await apiFetch(`/admin/users/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "변경에 실패했습니다.");
      // 변경된 사용자만 목록에서 교체
      setUsers((prev) => prev.map((u) => (u.id === id ? data : u)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function deleteUser(u) {
    if (!window.confirm(`'${u.name || u.email}' 사용자를 삭제할까요?\n이 사용자의 모든 대화도 함께 삭제됩니다.`)) {
      return;
    }
    setBusyId(u.id);
    setError("");
    try {
      const res = await apiFetch(`/admin/users/${u.id}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "삭제에 실패했습니다.");
      }
      setUsers((prev) => prev.filter((x) => x.id !== u.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <p className="admin-loading">불러오는 중…</p>;

  const pendingCount = users.filter((u) => u.status === "pending").length;

  return (
    <div className="users-panel">
      <header className="panel-header">
        <h3>사용자 관리</h3>
        <span className="panel-sub">
          전체 {users.length}명
          {pendingCount > 0 && <em className="badge-pending-count"> · 승인 대기 {pendingCount}</em>}
        </span>
      </header>

      {error && <p className="admin-error">⚠️ {error}</p>}

      <div className="table-wrap">
        <table className="users-table">
          <thead>
            <tr>
              <th>이름</th>
              <th>이메일</th>
              <th>연락처</th>
              <th>권한</th>
              <th>상태</th>
              <th>가입일</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const isMe = u.email === currentEmail;
              const busy = busyId === u.id;
              return (
                <tr key={u.id} className={u.status === "pending" ? "row-pending" : ""}>
                  <td>
                    {u.name || "-"}
                    {isMe && <span className="me-tag">나</span>}
                  </td>
                  <td className="cell-email">{u.email}</td>
                  <td>{u.phone || "-"}</td>
                  <td>
                    <span className={`badge role-${u.role}`}>{ROLE_LABEL[u.role]}</span>
                  </td>
                  <td>
                    <span className={`badge status-${u.status}`}>
                      {STATUS_LABEL[u.status]}
                    </span>
                  </td>
                  <td className="cell-date">{formatDate(u.created_at)}</td>
                  <td className="cell-actions">
                    {isMe ? (
                      <span className="muted">— 본인 —</span>
                    ) : (
                      <>
                        {u.status !== "approved" && (
                          <button
                            className="act approve"
                            disabled={busy}
                            onClick={() => updateUser(u.id, { status: "approved" })}
                          >
                            승인
                          </button>
                        )}
                        {u.status !== "rejected" && (
                          <button
                            className="act reject"
                            disabled={busy}
                            onClick={() => updateUser(u.id, { status: "rejected" })}
                          >
                            거부
                          </button>
                        )}
                        {u.role === "user" ? (
                          <button
                            className="act"
                            disabled={busy}
                            onClick={() => updateUser(u.id, { role: "admin" })}
                          >
                            관리자 지정
                          </button>
                        ) : (
                          <button
                            className="act"
                            disabled={busy}
                            onClick={() => updateUser(u.id, { role: "user" })}
                          >
                            일반 전환
                          </button>
                        )}
                        <button
                          className="act delete"
                          disabled={busy}
                          onClick={() => deleteUser(u)}
                        >
                          삭제
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// "2026-06-18T..." → "2026-06-18"
function formatDate(iso) {
  if (!iso) return "-";
  return String(iso).slice(0, 10);
}
