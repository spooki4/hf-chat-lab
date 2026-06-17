import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite 설정 파일.
// React 플러그인을 켜주고, 개발 서버는 기본 포트 5173에서 동작한다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
