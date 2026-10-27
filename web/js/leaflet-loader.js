/** 按需加载 Leaflet，避免阻塞首屏 */

let loading = null;

export function loadLeaflet() {
  if (globalThis.L) return Promise.resolve();
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/js/lib/leaflet.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("地图库加载失败"));
    document.head.appendChild(s);
  });
  return loading;
}
