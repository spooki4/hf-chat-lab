import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import "./Usage.css";

// 숫자에 천 단위 콤마 (예: 12345 → "12,345")
export function fmt(n) {
  return (n ?? 0).toLocaleString("ko-KR");
}

// 차트에 쓸 색상(입력/출력)
export const COLOR_PROMPT = "#60a5fa"; // 입력(파랑)
export const COLOR_COMPLETION = "#34d399"; // 출력(초록)
const RANK_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0d9488"];

/** 요약 카드 4개: 총 토큰 / 요청 수 / 입력 토큰 / 출력 토큰 */
export function SummaryCards({ totals }) {
  const cards = [
    { label: "총 토큰", value: fmt(totals.total_tokens), accent: true },
    { label: "요청 수", value: fmt(totals.request_count) },
    { label: "입력 토큰", value: fmt(totals.prompt_tokens) },
    { label: "출력 토큰", value: fmt(totals.completion_tokens) },
  ];
  return (
    <div className="usage-cards">
      {cards.map((c) => (
        <div key={c.label} className={`usage-card ${c.accent ? "accent" : ""}`}>
          <span className="usage-card-label">{c.label}</span>
          <span className="usage-card-value">{c.value}</span>
        </div>
      ))}
    </div>
  );
}

/** 일별 추이: 날짜별 입력/출력 토큰을 누적 막대로 */
export function DailyChart({ daily }) {
  if (!daily || daily.length === 0) {
    return <EmptyChart />;
  }
  return (
    <div className="usage-chart-box">
      <h4 className="usage-chart-title">일별 토큰 사용량</h4>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={daily} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef0f2" />
          <XAxis dataKey="day" tick={{ fontSize: 11 }} tickFormatter={shortDay} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={compact} width={48} />
          <Tooltip formatter={(v) => fmt(v)} labelFormatter={(d) => `날짜: ${d}`} />
          <Legend />
          <Bar dataKey="prompt_tokens" name="입력" stackId="t" fill={COLOR_PROMPT} />
          <Bar
            dataKey="completion_tokens"
            name="출력"
            stackId="t"
            fill={COLOR_COMPLETION}
            radius={[3, 3, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * 가로 막대 랭킹 차트 (TOP N).
 *   data: [{ ...있는그대로 }], nameKey: 라벨로 쓸 필드, valueKey: 값 필드
 */
export function RankBarChart({ title, data, nameKey, valueKey, limit = 5 }) {
  const rows = (data || []).slice(0, limit);
  return (
    <div className="usage-chart-box">
      <h4 className="usage-chart-title">{title}</h4>
      {rows.length === 0 ? (
        <p className="usage-empty-inline">데이터가 없습니다.</p>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(140, rows.length * 46)}>
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f2" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={compact} />
            <YAxis
              type="category"
              dataKey={nameKey}
              tick={{ fontSize: 11 }}
              width={120}
              tickFormatter={(s) => truncate(s, 16)}
            />
            <Tooltip formatter={(v) => fmt(v)} />
            <Bar dataKey={valueKey} name="토큰" radius={[0, 4, 4, 0]}>
              {rows.map((_, i) => (
                <Cell key={i} fill={RANK_COLORS[i % RANK_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

/** 기간 선택 + (선택) 추가 필터 슬롯. 빠른 프리셋(7/30일) 포함 */
export function RangeControls({ start, end, onChange, onPreset, children }) {
  return (
    <div className="usage-controls">
      <label className="usage-field">
        <span>시작</span>
        <input
          type="date"
          value={start}
          max={end || undefined}
          onChange={(e) => onChange("start", e.target.value)}
        />
      </label>
      <label className="usage-field">
        <span>끝</span>
        <input
          type="date"
          value={end}
          min={start || undefined}
          onChange={(e) => onChange("end", e.target.value)}
        />
      </label>
      <div className="usage-presets">
        <button type="button" onClick={() => onPreset(7)}>
          최근 7일
        </button>
        <button type="button" onClick={() => onPreset(30)}>
          최근 30일
        </button>
      </div>
      {children}
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="usage-chart-box">
      <h4 className="usage-chart-title">일별 토큰 사용량</h4>
      <p className="usage-empty">
        선택한 기간에 사용 기록이 없습니다.
        <br />
        채팅에서 메시지를 보내면 사용량이 집계됩니다.
      </p>
    </div>
  );
}

// "2026-06-18" → "06-18" (x축 라벨 간결하게)
function shortDay(d) {
  return typeof d === "string" ? d.slice(5) : d;
}
// 큰 수 축약 (1200 → 1.2k)
function compact(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}
function truncate(s, n) {
  s = String(s ?? "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
