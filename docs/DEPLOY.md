# FlightLog 部署收敛说明

## 当前线上路径（调研结论）

| 层级 | 角色 | 说明 |
|------|------|------|
| 公网 | `flightlog.alexander.xin` | Cloudflare Tunnel（mycloud） |
| AlexanderCloud | `~/fleet/flightlog-proxy` | **仅反代**到腾讯源站，不应再维护一份静态镜像 |
| 腾讯 `100.111.222.66` | `/home/ubuntu/flightlog` + Docker `:8321` | **权威应用**（FastAPI 托管 `web/` + SQLite `data/`） |
| GitHub | `pages.yml` | 只发布仓库内 `site/` 营销说明页到 GitHub Pages，**不是**产品站 |
| GitHub | `tencent-deploy.yml` | **仅手动** `workflow_dispatch`；需 `flightlog-tencent` runner（当前未部署） |

重复风险在于：若在 cloud 上再 rsync 一份 `web/` 静态站，会与腾讯 Docker 内嵌前端分叉。收敛后 **只改腾讯目录并重启容器**；cloud proxy 继续 `proxy_pass` 到 Tailscale 地址即可。

## 权威流水线

1. `ci.yml`（`ubuntu-latest`）— 测试与镜像构建，不部署。
2. **生产部署** — 在腾讯机上对 `/home/ubuntu/flightlog` 做 `git pull` / rsync 后 `docker compose up -d --build`（见下文）。
3. `tencent-deploy.yml` — 可选：将来若在腾讯机注册 **flightlog 仓库专用** runner 后，可在 Actions 里手动触发，效果与本地 rsync + compose 相同；**不会在 push 时自动排队**。
4. `pages.yml` — 可选的 GitHub Pages 说明页，与生产解耦。

## 腾讯机 self-hosted runner（仅 Folio）

同一台腾讯机上 **只保留 Folio 仓库的 repo-scoped runner**（`AlexanderJ-Carter.github.io`，label `folio-tencent` / `tencent-folio`）。**不要**为 FlightLog 在同一主机再注册第二个 runner（`tencent-flightlog` / `flightlog-tencent`）；该方案已明确放弃，避免与 Folio 运维冲突、重复占用同一主机上的 runner 服务。

FlightLog 生产变更请用 SSH 或现有运维方式更新 `/home/ubuntu/flightlog`，不要依赖尚未存在的 `flightlog-tencent` runner。

## 生产部署（手动，推荐）

在腾讯机 `ubuntu@100.111.222.66`（或经 Tailscale 等价地址）：

```bash
cd /home/ubuntu/flightlog
git fetch origin main && git checkout main && git pull --ff-only
# 若从本机 rsync：见仓库根目录 docker-compose.yml，排除 .env、data/、*.db
DOCKER_BUILDKIT=1 docker compose build
docker compose up -d
curl -sS http://127.0.0.1:8321/api/health   # 或 .env 中的 FLIGHTLOG_BIND/PORT
```

`.env` 与 `data/` **永不**从 CI 覆盖；OIDC、`FLIGHTLOG_PUBLIC_ORIGIN`、绑定地址仅在腾讯机本地维护。

### 可选：GitHub Actions 手动部署

仅当将来在 **flightlog 仓库** 单独注册 self-hosted runner 且打上 `flightlog-tencent` 标签时，可在 GitHub → Actions → **Deploy FlightLog (Tencent)** → **Run workflow** 触发。未注册 runner 前请勿运行，否则会一直排队。

仓库变量与密钥（可选）：

| 名称 | 用途 |
|------|------|
| `FLIGHTLOG_REMOTE_PATH`（可选） | 默认 `/home/ubuntu/flightlog` |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ZONE_ID`（可选） | 部署后按 URL 刷新缓存 |

## 本地验证

```bash
uv sync
cd server && uv run python test_lookup.py && uv run python test_auth_oidc.py
docker compose up -d --build
curl -s http://127.0.0.1:8321/api/auth/status
```
