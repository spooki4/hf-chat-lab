import { useEffect, useState } from "react";
import {
  SummaryCards,
  DailyChart,
  RankBarChart,
  RangeControls,
  fmt,
} from "./UsageShared";

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/**
 * 관리페이지 - 전체 사용자 토큰 사용량 모니터링.
 * 기간/사용자/모델 필터 + 요약 + 일별 추이 + 사용자 TOP5 + 모델 TOP5 + 전체 표.
 */
export default function AdminUsagePanel({ apiFetch }) {
  const [start, setStart] = useState(isoDaysAgo(29));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const [model, setModel] = useState("");
  const [userId, setUserId] = useState(""); // "" = 전체 사용자
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const qs = new URLSearchParams({ start, end });
        if (model) qs.set("model", model);
        if (userId) qs.set("user_id", userId);
        const res = await apiFetch(`/admin/usage?${qs.toString()}`);
        if (!res.ok) throw new Error("사용량을 불러오지 못했습니다.");
        const json = await res.json();
        if (alive) setData(json);
      } catch (err) {
        if (alive) setError(err.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [apiFetch, start, end, model, userId]);

  function onChange(field, value) {
    if (field === "start") setStart(value);
    else setEnd(value);
  }
  function onPreset(days) {
    setStart(isoDaysAgo(days - 1));
    setEnd(isoDaysAgo(0));
  }

  // 사용자 TOP5 차트는 이름이 같을 수 있으니 "이름(이메일앞)" 형태로 라벨 생성
  const userRank = (data?.by_user || []).map((u) => ({
    ...u,
    label: u.name || u.email,
  }));

  return (
    <div className="usage-panel">
      <h3 className="panel-h">토큰 사용량 모니터링</h3>

      <RangeControls start={start} end={end} onChange={onChange} onPreset={onPreset}>
        <label className="usage-field">
          <span>사용자</span>
          <select value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">전체 사용자</option>
            {(data?.users || []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.name || u.email} ({u.email})
              </option>
            ))}
          </select>
        </label>
        <label className="usage-field">
          <span>모델</span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">전체 모델</option>
            {(data?.models || []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      </RangeControls>

      {error && <p className="usage-error">⚠️ {error}</p>}
      {loading && !data ? (
        <p className="usage-loading">불러오는 중…</p>
      ) : (
        data && (
          <>
            <SummaryCards totals={data.totals} />

            <div className="usage-charts">
              <DailyChart daily={data.daily} />
            </div>

            <div className="usage-charts two" style={{ marginTop: 16 }}>
              <RankBarChart
                title="토큰 사용 TOP 5 · 사용자"
                data={userRank}
                nameKey="label"
                valueKey="total_tokens"
                limit={5}
              />
              <RankBarChart
                title="토큰 사용 TOP 5 · 모델"
                data={data.by_model}
                nameKey="model"
                valueKey="total_tokens"
                limit={5}
              />
            </div>

            {/* 사용자별 전체 표 */}
            <div className="usage-table-box">
              <table className="usage-table">
                <thead>
                  <tr>
                    <th className="rank">#</th>
                    <th>사용자</th>
                    <th>이메일</th>
                    <th className="num">총 토큰</th>
                    <th className="num">요청 수</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_user.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ textAlign: "center", color: "#9aa1ac" }}>
                        선택한 조건에 사용 기록이 없습니다.
                      </td>
                    </tr>
                  ) : (
                    data.by_user.map((u, i) => (
                      <tr key={u.user_id}>
                        <td className="rank">{i + 1}</td>
                        <td>{u.name || "-"}</td>
                        <td>{u.email}</td>
                        <td className="num">{fmt(u.total_tokens)}</td>
                        <td className="num">{fmt(u.request_count)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <p className="usage-note">
              ※ 토큰 수는 모델 제공자가 알려주는 값을 우선 사용하며, 제공되지 않을 때는 근사치로
              집계됩니다.
            </p>
          </>
        )
      )}
    </div>
  );
}
