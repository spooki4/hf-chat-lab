import { useEffect, useRef, useState } from "react";
import "./ModelPicker.css";

/**
 * 모델 선택 모달.
 * 모델 개수가 많아 드롭다운 대신 '검색 + 라디오 단일 선택' 모달로 고른다.
 *
 * props:
 *   models   - [{ id, label }]
 *   value    - 현재 선택된 모델 id
 *   onSelect - (id) => void  (선택 확정)
 *   onClose  - () => void     (취소/닫기)
 */
export default function ModelPicker({ models, value, onSelect, onClose }) {
  const [query, setQuery] = useState("");
  const inputRef = useRef(null);

  // 열리면 검색창에 포커스, Esc로 닫기
  useEffect(() => {
    inputRef.current?.focus();
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? models.filter((m) => `${m.label} ${m.id}`.toLowerCase().includes(q))
    : models;

  return (
    <div className="mp-overlay" onClick={onClose}>
      <div className="mp-modal" onClick={(e) => e.stopPropagation()}>
        <div className="mp-header">
          <h3>모델 선택</h3>
          <button className="mp-close" onClick={onClose} title="닫기">
            ×
          </button>
        </div>

        <input
          ref={inputRef}
          className="mp-search"
          type="text"
          placeholder="🔍 모델 검색…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <div className="mp-list">
          {filtered.length === 0 ? (
            <p className="mp-empty">검색 결과가 없습니다.</p>
          ) : (
            filtered.map((m) => {
              const checked = m.id === value;
              return (
                <label
                  key={m.id}
                  className={`mp-item ${checked ? "checked" : ""}`}
                >
                  <input
                    type="radio"
                    name="model"
                    checked={checked}
                    onChange={() => onSelect(m.id)}
                  />
                  <span className="mp-item-label">{m.label}</span>
                  {checked && <span className="mp-current">현재</span>}
                </label>
              );
            })
          )}
        </div>

        <div className="mp-footer">
          <span className="mp-count">{filtered.length}개 모델</span>
          <button className="mp-cancel" onClick={onClose}>
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
