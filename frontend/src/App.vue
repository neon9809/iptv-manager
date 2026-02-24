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
    </el-header>

    <el-main class="app-main">
      <div class="main-content">
        <router-view />
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  padding: 0;
  height: 60px;
}

.header-content {
  display: flex;
  align-items: center;
  height: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px;
}

.logo {
  font-size: 20px;
  font-weight: bold;
  color: #409eff;
  margin-right: 40px;
  white-space: nowrap;
}

.header-menu {
  flex: 1;
  border-bottom: none !important;
}

.app-main {
  margin-top: 60px;
  margin-bottom: 40px;
  padding: 20px;
  background: #f5f7fa;
  min-height: calc(100vh - 100px);
}

.main-content {
  max-width: 1200px;
  margin: 0 auto;
}

.app-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #909399;
  z-index: 1000;
}

.app-footer a {
  color: #409eff;
  text-decoration: none;
}

.app-footer a:hover {
  text-decoration: underline;
}

@media (max-width: 768px) {
  .header-content {
    padding: 0 12px;
  }
  
  .logo {
    font-size: 16px;
    margin-right: 16px;
  }
  
  .app-main {
    padding: 12px;
  }
  
  .main-content {
    max-width: 100%;
  }
}
</style>
