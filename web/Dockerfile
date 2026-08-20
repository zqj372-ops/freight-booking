# ====== Build stage ======
FROM node:20-alpine AS builder

WORKDIR /app

# 先装依赖 (利用 docker layer 缓存)
COPY package*.json ./
RUN npm install --no-audit --no-fund

# 复制源码 + 构建
COPY . .
# Vite build 时注入 API 地址 (docker-compose 通过 build args 传入)
# v0.5: 主用 /api/v2 (v0.4 deprecated 只读兼容). nginx 反代到 api:8000.
ARG VITE_API_BASE=/api/v2
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ====== Runtime stage ======
FROM nginx:1.27-alpine

# 拷贝构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 拷贝 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/ > /dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
