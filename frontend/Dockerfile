# 프론트엔드(React/Vite) 컨테이너 이미지 — 2단계 빌드.
#   1) build 단계: node로 정적 파일(dist) 빌드
#   2) 실행 단계: nginx로 정적 파일 서빙 + /api 를 백엔드로 리버스 프록시
# 이렇게 하면 브라우저는 한 오리진(프론트)만 보게 되어 CORS가 필요 없다.

# ---- 1) 빌드 단계 ----
FROM node:20-alpine AS build
WORKDIR /app

# 잠금 파일 기준으로 정확히 동일한 의존성 설치(package-lock.json)
COPY package*.json ./
RUN npm ci

COPY . .

# API 주소를 빌드 시점에 주입. 기본값 "/api"는 nginx가 백엔드로 프록시한다.
# (Vite는 VITE_* 환경변수를 빌드 시 코드에 박아 넣는다)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- 2) 실행 단계 ----
FROM nginx:1.27-alpine
# SPA 라우팅 + /api 프록시 설정
COPY nginx.conf /etc/nginx/conf.d/default.conf
# 빌드 산출물을 nginx 웹 루트로 복사
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
