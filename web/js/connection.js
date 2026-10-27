/** 连接 / 登录状态文案（档案与明细共用） */

import { getBase } from "./api.js";

export function loginUrl() {
  const next = encodeURIComponent(
    location.pathname + location.search + location.hash
  );
  return `${getBase()}/api/auth/login?next=${next}`;
}

export function disconnectCopy(state) {
  if (state.needsLogin) {
    return {
      title: "需要登录",
      sub: "使用 Pocket ID 登录后即可同步你的飞行档案。",
      cta: { label: "登录", href: loginUrl() },
    };
  }
  if (state.auth?.oidc && state.error?.includes("登录")) {
    return {
      title: "会话已过期",
      sub: "请重新登录以继续访问 API。",
      cta: { label: "重新登录", href: loginUrl() },
    };
  }
  const base = getBase();
  const sameOrigin =
    location.protocol.startsWith("http") &&
    base.replace(/\/+$/, "") === location.origin;
  if (sameOrigin) {
    return {
      title: "无法连接后端",
      sub: "请确认 API 已启动（docker compose up -d），或检查反向代理是否转发 /api。",
      cta: { label: "打开 API 设置", action: "api" },
    };
  }
  return {
    title: "无法连接 API",
    sub: `当前 API：${base}。可在顶栏「API」中修改，或由站点注入 flightlog-api-base。`,
    cta: { label: "配置 API", action: "api" },
  };
}
