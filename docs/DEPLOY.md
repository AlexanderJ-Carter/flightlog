# FlightLog 部署收敛说明

## 当前线上路径（调研结论）

| 层级 | 角色 | 说明 |
|------|------|------|
| 公网 | `flightlog.alexander.xin` | Cloudflare Tunnel（mycloud） |
| AlexanderCloud | `~/fleet/flightlog-proxy` | **仅反代**到腾讯源站，不应再维护一份静态镜像 |
| 腾讯 `100.111.222.66` | `/home/ubuntu/flightlog` + Docker `:8321` | **权威应用**（FastAPI 托管 `web/` + SQLite `data/`） |
| GitHub | `pages.yml` | 只发布仓库内 `site/` 营销说明页到 GitHub Pages，**不是**产品站 |
| GitHub | `tencent-deploy.yml`（本 PR） | push `main` 后由 **flightlog 专用 self-hosted runner** rsync + `docker compose` |

重复风险在于：若在 cloud 上再 rsync 一份 `web/` 静态站，会与腾讯 Docker 内嵌前端分叉。收敛后 **只改腾讯目录并重启容器**；cloud proxy 继续 `proxy_pass` 到 Tailscale 地址即可。

## 权威流水线

1. `ci.yml`（`ubuntu-latest`）— 测试与镜像构建，不部署。
2. `tencent-deploy.yml`（`self-hosted, linux, flightlog-tencent`）— 生产部署。
3. `pages.yml` — 可选的 GitHub Pages 说明页，与生产解耦。

## 与 Folio 共用腾讯机 runner

Folio 已在同一台机注册 **repo-scoped** runner（`AlexanderJ-Carter.github.io`，label `folio-tencent`）。FlightLog 需在 **同一主机、第二套 runner 目录** 注册到 `AlexanderJ-Carter/flightlog`（GitHub 不允许一个 repo-scoped runner 服务多个仓库）。

### 人工步骤（在腾讯机 `ubuntu@100.111.222.66` 执行）

```bash
# 1) 为 flightlog 准备 runner 目录（勿复用 folio 的 actions-runner 配置）
mkdir -p /home/ubuntu/actions-runner-flightlog
cd /home/ubuntu/actions-runner-flightlog

# 2) 下载与 folio 相同版本的 runner（示例 2.321.0，可按 folio 机已装版本对齐）
curl -o actions-runner-linux-x64-2.321.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
tar xzf actions-runner-linux-x64-2.321.0.tar.gz

# 3) 在 GitHub → flightlog 仓库 → Settings → Actions → Runners → New self-hosted runner
#    复制 ./config.sh 一行命令（含 repo token），在本目录执行，例如：
# ./config.sh --url https://github.com/AlexanderJ-Carter/flightlog --token <TOKEN> \
#   --name tencent-flightlog --labels self-hosted,linux,flightlog-tencent

# 4) 安装并启动服务（与 folio runner 并存）
sudo ./svc.sh install ubuntu
sudo ./svc.sh start
sudo ./svc.sh status
```

### 仓库变量与密钥（flightlog repo Settings）

| 名称 | 用途 |
|------|------|
| `FLIGHTLOG_REMOTE_PATH`（可选） | 默认 `/home/ubuntu/flightlog` |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ZONE_ID`（可选） | 部署后按 URL 刷新缓存 |

`.env` 与 `data/` **永不 rsync**；OIDC、`FLIGHTLOG_PUBLIC_ORIGIN`、绑定地址仅在腾讯机本地维护。

## 本地验证

```bash
uv sync
cd server && uv run python test_lookup.py && uv run python test_auth_oidc.py
docker compose up -d --build
curl -s http://127.0.0.1:8321/api/auth/status
```
