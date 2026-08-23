<template>
  <div class="home">
    <el-alert
      v-if="bannerNotifications.length"
      v-for="notif in bannerNotifications"
      :key="notif.id"
      :title="notif.subject"
      :type="notif.severity as 'success' | 'warning' | 'error' | 'info'"
      :closable="notif.read_button === 'available'"
      @close="markAsRead(notif.id)"
      show-icon
      style="margin-bottom: 20px"
    >
      {{ notif.context }}
    </el-alert>

    <el-row :gutter="20">
      <el-col :xs="24" :sm="24" :md="24">
        <el-card class="stats-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>系统状态</span>
              <el-button type="primary" @click="startAnalysis" :loading="analyzing" size="default">
                <el-icon><VideoPlay /></el-icon>
                <span class="btn-text">立即分析</span>
              </el-button>
            </div>
          </template>
          <el-row :gutter="16">
            <el-col :xs="12" :sm="6" :md="6">
              <div class="stat-item">
                <div class="stat-value">{{ stats.effectiveChannels }}</div>
                <div class="stat-label">有效频道</div>
                <div class="stat-sub-label">共 {{ stats.totalChannels }} 个</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="stat-item">
                <div class="stat-value">{{ stats.effectiveSources }}</div>
                <div class="stat-label">有效订阅源</div>
                <div class="stat-sub-label">共 {{ stats.totalSources }} 个</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="stat-item">
                <div class="stat-value">{{ stats.effectiveStreams }}</div>
                <div class="stat-label">有效直播流</div>
                <div class="stat-sub-label">共 {{ stats.totalStreams }} 个</div>
              </div>
            </el-col>
            <el-col :xs="12" :sm="6" :md="6">
              <div class="stat-item">
                <div class="stat-value" :class="stats.health === '正常' ? 'health-ok' : 'health-error'">{{ stats.health }}</div>
                <div class="stat-label">系统状态</div>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :xs="24" :sm="24" :md="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>播放列表地址</span>
              <el-text type="info" size="small">点击复制到播放器</el-text>
            </div>
          </template>
          <div class="playlist-grid">
            <div class="playlist-item" @click="copyPlaylist('playfast')">
              <div class="playlist-icon"><el-icon><Timer /></el-icon></div>
              <div class="playlist-info">
                <div class="playlist-name">延迟优先</div>
                <div class="playlist-desc">最快响应时间</div>
              </div>
            </div>
            <div class="playlist-item" @click="copyPlaylist('playbest')">
              <div class="playlist-icon"><el-icon><Film /></el-icon></div>
              <div class="playlist-info">
                <div class="playlist-name">画质优先</div>
                <div class="playlist-desc">最高清晰度</div>
              </div>
            </div>
            <div class="playlist-item" @click="copyPlaylist('playstable')">
              <div class="playlist-icon"><el-icon><Lock /></el-icon></div>
              <div class="playlist-info">
                <div class="playlist-name">稳定性优先</div>
                <div class="playlist-desc">最稳定连接</div>
              </div>
            </div>
            <div class="playlist-item" @click="copyPlaylist('playoptimized')">
              <div class="playlist-icon"><el-icon><MagicStick /></el-icon></div>
              <div class="playlist-info">
                <div class="playlist-name">综合优化</div>
                <div class="playlist-desc">智能平衡</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :xs="24" :sm="24" :md="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>最近维护</span>
            </div>
          </template>
          <div class="timeline-container">
            <el-timeline v-if="timeline.length > 0">
              <el-timeline-item
                v-for="(item, index) in timeline.slice(0, 10)"
                :key="index"
                :timestamp="item.timestamp"
                :type="item.type"
                placement="top"
              >
                {{ item.content }}
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无维护记录" :image-size="80" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay, Timer, Film, Lock, MagicStick } from '@element-plus/icons-vue'
import { healthApi, sourcesApi, channelsApi, streamsApi, notificationsApi, analysisApi, systemConfigApi } from '../api'

const notifications = ref<any[]>([])
const bannerNotifications = computed(() => 
  notifications.value.filter(n => !n.notification_channels?.includes('maintenance-timeline'))
)
const analyzing = ref(false)
let refreshTimer: number | null = null
const stats = ref({
  effectiveChannels: 0,
  totalChannels: 0,
  effectiveSources: 0,
  totalSources: 0,
  effectiveStreams: 0,
  totalStreams: 0,
  health: '未知',
})

const timeline = ref<any[]>([])

const getSystemStartTime = () => {
  const stored = localStorage.getItem('system_start_time')
  if (stored) {
    return stored
  }
  const now = new Date().toISOString()
  localStorage.setItem('system_start_time', now)
  return now
}

const loadData = async () => {
  try {
    const healthRes = await healthApi.check()
    stats.value.health = healthRes.data.status === 'healthy' ? '正常' : '异常'
    
    const sourcesRes = await sourcesApi.list()
    const allSources = sourcesRes.data
    stats.value.totalSources = allSources.length
    stats.value.effectiveSources = allSources.filter((s: any) => s.last_refresh_status === 'success').length
    
    const channelsRes = await channelsApi.list()
    const allChannels = channelsRes.data
    stats.value.totalChannels = allChannels.length
    
    const allStreams: any[] = await streamsApi.listAll()
    stats.value.totalStreams = allStreams.length
    
    const channelIdsWithStreams = new Set(allStreams.map((s: any) => s.channel_id).filter(Boolean))
    stats.value.effectiveChannels = channelIdsWithStreams.size
    
    const configRes = await systemConfigApi.get()
    const forgivenessParam = configRes.data.forgiveness_param || 10
    stats.value.effectiveStreams = allStreams.filter((s: any) => 
      s.latency_ms !== null && s.latency_ms !== undefined && s.unreachable_count <= forgivenessParam
    ).length
    
    const notifRes = await notificationsApi.list()
    notifications.value = notifRes.data
    
    const maintenanceItems = notifRes.data
      .filter((n: any) => n.notification_channels?.includes('maintenance-timeline'))
      .map((n: any) => ({
        timestamp: n.created_at,
        content: `${n.subject}: ${n.context}`,
        type: n.severity === 'success' ? 'success' : n.severity === 'warning' ? 'warning' : 'info'
      }))
    
    const baseTimeline = [
      { timestamp: getSystemStartTime(), content: '系统启动', type: 'primary' },
    ]
    
    timeline.value = [...baseTimeline, ...maintenanceItems].sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )
    
    const analysisComplete = maintenanceItems.some((item: any) => 
      item.content.includes('分析完成')
    )
    if (analysisComplete && analyzing.value) {
      stopRefresh()
    }
  } catch (error) {
    console.error('Failed to load data:', error)
    timeline.value = [{ timestamp: getSystemStartTime(), content: '系统启动', type: 'primary' }]
  }
}

const copyPlaylist = async (type: string) => {
  const host = window.location.hostname
  const url = `http://${host}/${type}`
  
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success(`已复制: ${url}`)
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

const markAsRead = async (id: number) => {
  try {
    await notificationsApi.markRead(id)
    notifications.value = notifications.value.filter(n => n.id !== id)
  } catch (error) {
    console.error('Failed to mark notification as read:', error)
  }
}

const startAnalysis = async () => {
  analyzing.value = true
  try {
    const response = await analysisApi.trigger({ mode: 'full' })
    if (response.data.status === 'submitted') {
      ElMessage.success(`分析任务已提交，共 ${response.data.total} 个直播流`)
      refreshTimer = window.setInterval(() => {
        loadData()
      }, 500)
    } else if (response.data.status === 'no_streams') {
      ElMessage.warning('没有可分析的直播流，请先添加订阅源')
      analyzing.value = false
    }
  } catch (error) {
    ElMessage.error('启动分析失败')
    analyzing.value = false
  }
}

const stopRefresh = () => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  analyzing.value = false
}

onMounted(() => {
  loadData()
})

onUnmounted(() => {
  stopRefresh()
})
</script>

<style scoped>
.stats-card {
  margin-bottom: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 16px;
}

.card-header .el-text {
  font-weight: normal;
}

.stat-item {
  text-align: center;
  padding: 16px 8px;
}

/* 大号数字：负字距 + 紧行高（§15 大字收紧） */
.stat-value {
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.05;
  color: var(--el-color-primary);
  font-variant-numeric: tabular-nums;   /* 数字等宽，刷新时不跳动 */
}

.stat-value.health-ok {
  color: var(--el-color-success);
}

.stat-value.health-error {
  color: var(--el-color-danger);
}

.stat-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
  margin-top: 8px;
}

.stat-sub-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.playlist-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.playlist-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: var(--radius-card, 14px);
  background: var(--el-fill-color-blank, #fff);
  box-shadow: var(--shadow-card, 0 1px 3px rgba(0, 0, 0, 0.05));
  cursor: pointer;
  user-select: none;
  /* 只动 transform/box-shadow（§11 compositor-friendly）；
     按压反馈在 :active 即刻生效（§1 pointer-down） */
  transition: transform 120ms ease-out, box-shadow 120ms ease-out,
              background-color 120ms ease-out;
  will-change: transform;
}

.playlist-item:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-raised, 0 8px 24px rgba(0, 0, 0, 0.10));
}

.playlist-item:active {
  transform: scale(0.97);            /* 按下即缩，不等松手 */
  box-shadow: var(--shadow-card, 0 1px 3px rgba(0, 0, 0, 0.05));
}

.playlist-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-chip, 10px);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 20px;
  flex-shrink: 0;
}

.playlist-info {
  flex: 1;
  min-width: 0;
}

.playlist-name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--el-text-color-primary);
}

.playlist-desc {
  font-size: 12px;
  letter-spacing: 0.01em;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.timeline-container {
  max-height: 400px;
  overflow-y: auto;
}

@media (max-width: 768px) {
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .card-header .el-button {
    width: 100%;
  }
  
  .btn-text {
    display: inline;
  }
  
  .stat-item {
    padding: 12px 4px;
  }
  
  .stat-value {
    font-size: 24px;
  }
  
  .stat-label {
    font-size: 12px;
  }
  
  .playlist-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }
  
  .playlist-item {
    padding: 12px;
  }
  
  .playlist-icon {
    width: 34px;
    height: 34px;
    font-size: 17px;
  }
  
  .playlist-name {
    font-size: 13px;
  }
  
  .playlist-desc {
    font-size: 11px;
  }
}

@media (max-width: 480px) {
  .playlist-grid {
    grid-template-columns: 1fr;
  }
}
</style>
