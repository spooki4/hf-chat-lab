import { useEffect, useState } from "react";
import {
  SummaryCards,
  DailyChart,
  RankBarChart,
  RangeControls,
  fmt,
} from "./UsageShared";

// 오늘부터 n일 전 날짜를 "YYYY-MM-DD"로 (날짜 입력 기본값용)
function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/**
 * 마이페이지 - 토큰 사용량.
 * 기간/모델로 조회해 내 사용량을 요약 카드 + 일별 그래프 + 모델별 분포로 보여준다.
 */
export default function MyUsagePanel({ apiFetch }) {
  const [start, setStart] = useState(isoDaysAgo(29));
  const [end, setEnd] = useState(isoDaysAgo(0));
  const [model, setModel] = useState(""); // "" = 전체
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
        const res = await apiFetch(`/usage/me?${qs.toString()}`);
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
  }, [apiFetch, start, end, model]);

  function onChange(field, value) {
    if (field === "start") setStart(value);
    else setEnd(value);
  }
  function onPreset(days) {
    setStart(isoDaysAgo(days - 1));
    setEnd(isoDaysAgo(0));
  }

  return (
    <div className="usage-panel">
      <h3 className="panel-h">토큰 사용량</h3>

      <RangeControls start={start} end={end} onChange={onChange} onPreset={onPreset}>
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
            <div className="usage-charts two">
              <DailyChart daily={data.daily} />
              <RankBarChart
                title="모델별 사용량"
                data={data.by_model}
                nameKey="model"
                valueKey="total_tokens"
                limit={5}
              />
            </div>

            {data.by_model.length > 0 && (
              <div className="usage-table-box">
                <table className="usage-table">
                  <thead>
                    <tr>
                      <th>모델</th>
                      <th className="num">총 토큰</th>
                      <th className="num">요청 수</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_model.map((m) => (
                      <tr key={m.model}>
                        <td>{m.model}</td>
                        <td className="num">{fmt(m.total_tokens)}</td>
                        <td className="num">{fmt(m.request_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

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
