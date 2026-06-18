import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import "./App.css";

// React 18 방식: root를 만들고 그 안에 <App />을 렌더링한다.
// BrowserRouter: URL 기반 화면 전환(채팅 / 관리 / 마이페이지)을 가능하게 한다.
// StrictMode는 개발 중 잠재적 문제를 잡아주는 도우미(프로덕션엔 영향 없음).
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
