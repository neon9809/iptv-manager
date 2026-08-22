<template>
  <el-container class="app-container">
    <el-header class="app-header">
      <div class="header-content">
        <h1 class="logo">📺 IPTV Manager</h1>
        <el-menu
          mode="horizontal"
          :router="true"
          :default-active="$route.path"
          class="header-menu"
        >
          <el-menu-item index="/">
            <el-icon><HomeFilled /></el-icon>
            首页
          </el-menu-item>
          <el-menu-item index="/sources">
            <el-icon><Connection /></el-icon>
            订阅源
          </el-menu-item>
          <el-menu-item index="/channels">
            <el-icon><VideoCamera /></el-icon>
            频道管理
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            设置
          </el-menu-item>
        </el-menu>
      </div>
      <!-- 滚动边缘效果：内容与浮动铬层交界处的渐隐遮罩，替代硬分隔线 -->
      <div class="scroll-edge-fade" aria-hidden="true" />
    </el-header>

    <el-main class="app-main">
      <div class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </el-main>

    <el-footer class="app-footer">
      <a href="https://github.com/neon9809/iptv-manager" target="_blank">
        iptv-manager
      </a>
      ｜Powered by FastAPI & Vue.js｜Developed with Trae
    </el-footer>
  </el-container>
</template>

<script setup lang="ts">
import { HomeFilled, Connection, VideoCamera, Setting } from '@element-plus/icons-vue'
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif;
}

.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* ============================================================
   顶部铬层 —— 半透明材料（design.md §12）
   内容从其下滚过，而非被不透明条挡住；
   亮色顶边高光 = 光线照在材料上的质感
   ============================================================ */
.app-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),   /* 亮顶边 */
    0 1px 12px rgba(0, 0, 0, 0.06);
  padding: 0;
  height: 60px;
}

@media (prefers-color-scheme: dark) {
  .app-header {
    background: rgba(28, 28, 30, 0.72);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 1px 12px rgba(0, 0, 0, 0.30);
  }
}

.header-content {
  display: flex;
  align-items: center;
  height: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px;
}

/* Logo：大号文字收紧字距（§15 字号专属字距） */
.logo {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--el-color-primary);
  margin-right: 40px;
  white-space: nowrap;
}

.header-menu {
  flex: 1;
  border-bottom: none !important;
  background: transparent !important;
}

/* 滚动边缘效果：内容与铬层交界处的柔和过渡带，
   替代 1px 硬分隔线（§12 scroll edge effects） */
.scroll-edge-fade {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -12px;
  height: 12px;
  pointer-events: none;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.04), transparent);
}

@media (prefers-color-scheme: dark) {
  .scroll-edge-fade {
    background: linear-gradient(to bottom, rgba(0, 0, 0, 0.25), transparent);
  }
}

.app-main {
  margin-top: 60px;
  margin-bottom: 40px;
  padding: 24px 20px;
  background: #f5f5f7;
  min-height: calc(100vh - 100px);
}

@media (prefers-color-scheme: dark) {
  .app-main { background: #000; }
}

.main-content {
  max-width: 1200px;
  margin: 0 auto;
}

/* ============================================================
   页面切换 —— 空间一致性（§7）：进出沿同一路径，
   轻微上移 + 交叉淡化；默认无过冲（§4 damping 1.0）
   ============================================================ */
.page-enter-active,
.page-leave-active {
  transition: opacity 200ms cubic-bezier(0.25, 0.1, 0.25, 1),
              transform 200ms cubic-bezier(0.25, 0.1, 0.25, 1);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ============================================================
   底部铬层 —— 同为半透明材料，亮边朝上（光从上方来）
   ============================================================ */
.app-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.5),
    0 -1px 12px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  letter-spacing: 0.01em;           /* 小字微放字距（§15） */
  color: var(--el-text-color-secondary, #86868b);
  z-index: 1000;
}

@media (prefers-color-scheme: dark) {
  .app-footer {
    background: rgba(28, 28, 30, 0.72);
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.08),
      0 -1px 12px rgba(0, 0, 0, 0.30);
  }
}

.app-footer a {
  color: var(--el-color-primary);
  text-decoration: none;
  transition: opacity var(--dur-fast, 120ms) ease-out;
}

.app-footer a:hover {
  text-decoration: underline;
}

.app-footer a:active {
  opacity: 0.6;                     /* 按压即时反馈（§1） */
}

@media (max-width: 768px) {
  .header-content {
    padding: 0 12px;
  }

  .logo {
    font-size: 17px;
    margin-right: 16px;
  }

  .app-main {
    padding: 12px;
  }

  .main-content {
    max-width: 100%;
  }
}

/* 减少动态：页面切换退化为纯交叉淡化（§14） */
@media (prefers-reduced-motion: reduce) {
  .page-enter-active,
  .page-leave-active {
    transition: opacity 150ms ease;
  }
  .page-enter-from,
  .page-leave-to {
    transform: none;
  }
}
</style>
