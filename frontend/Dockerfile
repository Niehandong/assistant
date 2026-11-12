# 前端生产镜像：node 构建 -> nginx 静态资源 + 反向代理
# 构建：docker build -t kbp-frontend:dev frontend
# 运行：需注入 IAM_UPSTREAM / KB_UPSTREAM / OPEN_UPSTREAM（格式 host:port，不带协议）

FROM node:22-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@9.15.9
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
# 官方镜像启动时会对 /etc/nginx/templates/*.template 做 envsubst（仅替换已定义的环境变量）
ENV NGINX_ENVSUBST_FILTER=_UPSTREAM \
    IAM_UPSTREAM=iam:8301 \
    KB_UPSTREAM=kb:8302 \
    OPEN_UPSTREAM=open:8303
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
