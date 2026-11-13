# 知识库平台

多服务知识库平台：iam（认证与权限）、kb（知识库与文档处理）、open（开放平台）三个后端服务，加 React 前端。

## 目录结构

```
.
├── backend/    # 后端：共享库 libs/platform_common、服务 services/{iam,kb,open}、本机开发脚本 scripts/devctl.py
├── frontend/   # 前端：React + Ant Design（Vite）
├── docs/       # 需求、技术方案、缺陷与测试报告
├── docker/     # 全部 Docker 部署文件与容器数据（本地一键运行 + 生产部署）
├── CLAUDE.md   # 项目协作规范
└── .venv/      # 后端共用 Python 环境（隐藏目录，不进 git）
```

## 启动

**一键运行（Docker）：请看 [docker/README.md](docker/README.md)。** 进入 `docker/` 目录执行 `docker compose up -d`，访问 <http://localhost:8300>。

本机开发（后端 devctl、前端 pnpm dev，不进容器）的命令见 [CLAUDE.md](CLAUDE.md) 第 9 节。
