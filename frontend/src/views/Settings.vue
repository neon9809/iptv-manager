<template>
  <div class="settings">
    <el-row :gutter="20">
      <el-col :xs="24" :sm="24" :md="12">
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>增强分析配置</span>
              <el-tag v-if="currentAnalysisMode === 'quick'" type="warning" size="small">快速模式</el-tag>
              <el-tag v-else type="success" size="small">完整模式</el-tag>
            </div>
          </template>
          <el-form label-width="100px" label-position="top" class="compact-form">
            <el-form-item label="测试模式">
              <el-radio-group v-model="settings.analysisMode" class="full-width">
                <el-radio-button label="quick" class="flex-1">快速分析</el-radio-button>
                <el-radio-button label="full" class="flex-1">完整分析</el-radio-button>
              </el-radio-group>
              <div class="form-tip">系统会根据资源使用情况自动切换模式</div>
            </el-form-item>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="分析频率">
                  <el-input-number v-model="settings.analysisFrequency" :min="15" :max="1440" class="full-width" />
                  <div class="form-tip">分钟</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="原谅参数">
                  <el-input-number v-model="settings.forgivenessParam" :min="1" :max="50" class="full-width" />
                  <div class="form-tip">次</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="并发Worker">
                  <el-input-number v-model="settings.analysisWorkers" :min="1" :max="20" class="full-width" />
                  <div class="form-tip">个</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="测试超时">
                  <el-input-number v-model="settings.analysisTimeout" :min="1" :max="30" class="full-width" />
                  <div class="form-tip">秒</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item>
              <el-button type="primary" @click="saveSettings" :loading="savingSettings" class="full-width">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="24" :md="12">
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>通知事项</span>
              <el-text type="info" size="small">点击配置</el-text>
            </div>
          </template>
          <div class="notification-items">
            <div 
              v-for="item in notificationItems" 
              :key="item.key"
              class="notification-item"
              @click="openItemConfig(item)"
            >
              <div class="item-main">
                <el-switch 
                  v-model="item.enabled" 
                  @click.stop
                  @change="(val: boolean) => onItemEnableChange(item.key, val)"
                />
                <span class="item-name">{{ item.name }}</span>
              </div>
              <div class="item-meta">
                <el-tag v-if="getThresholdText(item)" size="small" type="info">{{ getThresholdText(item) }}</el-tag>
                <el-icon class="arrow-icon"><ArrowRight /></el-icon>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :xs="24" :sm="24" :md="12">
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>通知管道</span>
              <el-text type="warning" size="small">关闭将禁用该管道所有通知</el-text>
            </div>
          </template>
          <div class="channel-configs">
            <div class="channel-config-item">
              <div class="channel-header">
                <div class="channel-title">
                  <el-switch v-model="channels.homepage.enabled" @change="onChannelToggle('homepage')" />
                  <span>首页通知栏</span>
                </div>
                <el-button type="primary" link size="small" @click="editChannel('homepage')" :disabled="!channels.homepage.enabled">编辑</el-button>
              </div>
              <div class="channel-usage">
                <el-text type="info" size="small">被以下通知事项使用: {{ getItemsUsingChannel('homepage') }}</el-text>
              </div>
            </div>

            <div class="channel-config-item">
              <div class="channel-header">
                <div class="channel-title">
                  <el-tooltip :content="smtpEnableTooltip" placement="top" :disabled="canEnableSmtp">
                    <el-switch v-model="channels.smtp.enabled" @change="onSmtpToggle" :disabled="!canEnableSmtp" />
                  </el-tooltip>
                  <span>SMTP 邮件</span>
                  <el-tag v-if="channels.smtp.config.tested" type="success" size="small">已配置</el-tag>
                </div>
                <el-button type="primary" size="small" @click.stop="editChannel('smtp')">{{ channels.smtp.config.tested ? '编辑' : '配置' }}</el-button>
              </div>
              <div class="channel-usage">
                <el-text type="info" size="small">被以下通知事项使用: {{ getItemsUsingChannel('smtp') }}</el-text>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="24" :md="12">
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>日志管理</span>
              <el-tag v-if="settings.logEnabled" type="success" size="small">已启用</el-tag>
              <el-tag v-else type="info" size="small">已禁用</el-tag>
            </div>
          </template>
          <el-form label-width="100px" label-position="top" class="compact-form">
            <el-form-item label="启用日志">
              <el-switch v-model="settings.logEnabled" />
            </el-form-item>
            <el-form-item label="日志保存期">
              <el-input-number v-model="settings.logRetentionHours" :min="1" :max="168" class="full-width" />
              <div class="form-tip">小时，Celery Beat 每小时自动清理</div>
            </el-form-item>
            <el-form-item>
              <el-space wrap class="full-width-buttons">
                <el-button type="primary" @click="saveSettings" :loading="savingSettings">保存配置</el-button>
                <el-button type="info" @click="viewLogs" :disabled="!settings.logEnabled" :loading="loadingLogs">查看日志</el-button>
                <el-button type="success" @click="exportLogs" :disabled="!settings.logEnabled" :loading="exportingLogs">导出日志</el-button>
              </el-space>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :xs="24" :sm="24" :md="24">
        <el-card class="settings-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>备份与恢复</span>
            </div>
          </template>
          <div class="backup-section">
            <div class="backup-info">
              <el-text type="info">导出的配置包含：系统配置、SMTP配置、通知设置、订阅源列表</el-text>
            </div>
            <el-space wrap>
              <el-button type="primary" @click="exportConfig" :loading="exportingConfig">导出配置</el-button>
              <el-upload :show-file-list="false" :before-upload="importConfig" accept=".json">
                <el-button :loading="importingConfig">导入配置</el-button>
              </el-upload>
            </el-space>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="itemDialogVisible" :title="`配置: ${editingItem?.name}`" width="500px" :fullscreen="isMobile">
      <el-form label-width="100px" label-position="top">
        <el-form-item label="启用通知">
          <el-switch v-model="editingItemConfig.enabled" />
        </el-form-item>
        <el-form-item v-if="editingItem?.has_threshold" label="触发阈值">
          <el-input-number v-model="editingItemConfig.threshold_value" :min="1" :max="100" />
          <span style="margin-left: 5px">%</span>
        </el-form-item>
        <el-form-item v-if="editingItem?.has_status_config" label="触发状态">
          <el-checkbox-group v-model="editingItemConfig.statuses">
            <el-checkbox label="failed">失败</el-checkbox>
            <el-checkbox label="timeout">超时</el-checkbox>
            <el-checkbox label="error">错误</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="通知管道">
          <el-checkbox-group v-model="editingItemConfig.channels">
            <el-checkbox v-for="ch in availableChannels" :key="ch.key" :label="ch.key" :disabled="ch.key === 'homepage' ? !channels.homepage.enabled : !channels.smtp.enabled">
              {{ ch.name }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveItemConfig" :loading="savingItem">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="channelDialogVisible" :title="`配置管道: ${editingChannel?.name}`" width="500px" :fullscreen="isMobile">
      <el-form label-width="100px" label-position="top" v-if="editingChannel?.key === 'homepage'">
        <el-form-item label="默认公告">
          <el-input v-model="channels.homepage.config.defaultMessage" placeholder="系统正常运行中" />
        </el-form-item>
      </el-form>

      <el-form label-width="100px" label-position="top" v-if="editingChannel?.key === 'smtp'">
        <el-row :gutter="16">
          <el-col :span="16">
            <el-form-item label="SMTP服务器">
              <el-input v-model="channels.smtp.config.host" placeholder="smtp.gmail.com" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="端口">
              <el-input-number v-model="channels.smtp.config.port" :min="1" :max="65535" class="full-width" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="发件人">
          <el-input v-model="channels.smtp.config.sender" placeholder="iptv@example.com" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="用户名">
              <el-input v-model="channels.smtp.config.username" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item :label="channels.smtp.config.password_set ? '密码（已保存，留空不修改）' : '密码'">
              <el-input v-model="channels.smtp.config.password" type="password" show-password
                :placeholder="channels.smtp.config.password_set ? '••••••••' : ''" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="使用TLS">
          <el-switch v-model="channels.smtp.config.use_tls" />
        </el-form-item>
        <el-form-item label="测试收件人">
          <el-input v-model="smtpTestRecipient" placeholder="请输入接收测试邮件的邮箱地址" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="testSmtp" :loading="testingSmtp">测试并发送测试邮件</el-button>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="channelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveChannelConfig" :loading="savingChannel">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="logsDialogVisible" title="系统日志" width="80%" top="5vh" :fullscreen="isMobile">
      <div class="logs-filter">
        <el-select v-model="logsFilterLevel" placeholder="筛选日志级别" clearable style="width: 150px" @change="handleLogsFilterChange">
          <el-option label="全部" value="" />
          <el-option label="DEBUG" value="DEBUG" />
          <el-option label="INFO" value="INFO" />
          <el-option label="WARNING" value="WARNING" />
          <el-option label="ERROR" value="ERROR" />
          <el-option label="CRITICAL" value="CRITICAL" />
        </el-select>
        <el-button type="primary" @click="loadLogs" :loading="loadingLogs">刷新</el-button>
      </div>
      <div class="logs-container" @scroll="handleLogsScroll">
        <div v-if="logs.length === 0" class="logs-empty">
          <el-empty description="暂无日志" />
        </div>
        <div v-else class="logs-list">
          <div v-for="log in filteredLogs" :key="log.id" class="log-item" :class="`log-${log.level.toLowerCase()}`">
            <div class="log-header">
              <span class="log-time">{{ formatLogTime(log.created_at) }}</span>
              <el-tag :type="getLogLevelTagType(log.level)" size="small">{{ log.level }}</el-tag>
              <span class="log-logger">{{ log.logger }}</span>
            </div>
            <div class="log-message">{{ log.message }}</div>
          </div>
          <div v-if="logsPagination.hasMore" class="logs-load-more">
            <el-button @click="loadMoreLogs" :loading="loadingMoreLogs" style="width: 100%">加载更多</el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="logsDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { 
  smtpConfigApi, 
  analysisApi, 
  systemConfigApi,
  notificationItemsApi,
  notificationChannelConfigsApi,
  logsApi
} from '../api'

const isMobile = computed(() => window.innerWidth < 768)

const settings = ref({
  analysisMode: 'full',
  analysisFrequency: 45,
  forgivenessParam: 10,
  analysisWorkers: 6,
  analysisTimeout: 3,
  logEnabled: false,
  logRetentionHours: 1,
})

const savingSettings = ref(false)
const savingItem = ref(false)
const savingChannel = ref(false)
const exportingLogs = ref(false)
const exportingConfig = ref(false)
const importingConfig = ref(false)
const loadingLogs = ref(false)
const logsDialogVisible = ref(false)
const logs = ref<any[]>([])
const logsFilterLevel = ref('')
const logsPagination = ref({ page: 1, pageSize: 50, total: 0, hasMore: true })
const loadingMoreLogs = ref(false)

const currentAnalysisMode = ref('full')

const loadAnalysisMode = async () => {
  try {
    const response = await analysisApi.getMode()
    currentAnalysisMode.value = response.data.mode
  } catch (error) {
    console.error('加载分析模式失败:', error)
  }
}

const loadSystemConfig = async () => {
  try {
    const response = await systemConfigApi.get()
    const config = response.data
    settings.value.analysisFrequency = config.analysis_frequency_minutes
    settings.value.analysisWorkers = config.analysis_workers
    settings.value.analysisTimeout = config.analysis_timeout_seconds
    settings.value.forgivenessParam = config.forgiveness_param
    settings.value.logEnabled = config.log_enabled
    settings.value.logRetentionHours = config.log_retention_hours
  } catch (error) {
    console.error('加载系统配置失败:', error)
  }
}

const notificationItems = ref<any[]>([])
const notificationChannelConfigs = ref<any[]>([])

const channels = ref({
  homepage: {
    enabled: true,
    config: {
      defaultMessage: '系统正常运行中'
    }
  },
  smtp: {
    enabled: false,
    config: {
      host: '',
      port: 587,
      sender: '',
      username: '',
      password: '',
      password_set: false,
      use_tls: true,
      tested: false
    }
  }
})

const canEnableSmtp = computed(() => {
  return channels.value.smtp.config.tested
})

const smtpEnableTooltip = computed(() => {
  if (!channels.value.smtp.config.host) return '请先配置 SMTP 服务器地址'
  if (!channels.value.smtp.config.sender) return '请先配置发件人邮箱'
  if (!channels.value.smtp.config.tested) return '请先测试 SMTP 配置'
  return ''
})

const loadNotificationItems = async () => {
  try {
    const response = await notificationItemsApi.list()
    notificationItems.value = response.data
  } catch (error) {
    console.error('加载通知事项失败:', error)
  }
}

const loadNotificationChannelConfigs = async () => {
  try {
    const response = await notificationChannelConfigsApi.list()
    notificationChannelConfigs.value = response.data
    
    response.data.forEach((config: any) => {
      if (config.channel_key === 'homepage') {
        channels.value.homepage.enabled = config.enabled
        channels.value.homepage.config = config.config || {}
      } else if (config.channel_key === 'smtp') {
        channels.value.smtp.enabled = config.enabled
        channels.value.smtp.config = { ...channels.value.smtp.config, ...config.config }
      }
    })
  } catch (error) {
    console.error('加载通知管道配置失败:', error)
  }
}

const getThresholdText = (item: any) => {
  if (item.has_threshold && item.threshold_value !== null && item.threshold_value !== undefined) {
    return `${item.threshold_value}%`
  }
  return null
}

const availableChannels = [
  { key: 'homepage', name: '首页通知栏' },
  { key: 'smtp', name: 'SMTP 邮件' }
]

const itemDialogVisible = ref(false)
const channelDialogVisible = ref(false)
const smtpTestRecipient = ref('')
const editingItem = ref<any>(null)
const editingItemConfig = ref<any>({})
const editingChannel = ref<any>(null)

const getItemsUsingChannel = (channelKey: string) => {
  const items = notificationItems.value.filter(item => item.channels.includes(channelKey)).map(item => item.name)
  return items.length > 0 ? items.join('、') : '无'
}

const openItemConfig = (item: any) => {
  editingItem.value = item
  editingItemConfig.value = {
    enabled: item.enabled,
    threshold_value: item.threshold_value || 30,
    statuses: item.statuses || [],
    channels: [...item.channels]
  }
  itemDialogVisible.value = true
}

const saveItemConfig = async () => {
  if (!editingItem.value) return
  savingItem.value = true
  try {
    await notificationItemsApi.update(editingItem.value.key, editingItemConfig.value)
    const item = notificationItems.value.find(i => i.key === editingItem.value.key)
    if (item) Object.assign(item, editingItemConfig.value)
    itemDialogVisible.value = false
    ElMessage.success('通知事项配置已保存')
  } catch (error) {
    ElMessage.error('保存通知事项配置失败')
  } finally {
    savingItem.value = false
  }
}

const editChannel = (channelKey: string) => {
  editingChannel.value = availableChannels.find(c => c.key === channelKey)
  channelDialogVisible.value = true
}

const saveChannelConfig = async () => {
  if (!editingChannel.value) return
  savingChannel.value = true
  channelDialogVisible.value = false
  try {
    if (editingChannel.value.key === 'homepage') {
      await notificationChannelConfigsApi.update('homepage', { enabled: channels.value.homepage.enabled, config: channels.value.homepage.config })
    } else if (editingChannel.value.key === 'smtp') {
      await smtpConfigApi.update({
        enabled: channels.value.smtp.enabled,
        host: channels.value.smtp.config.host,
        port: channels.value.smtp.config.port,
        sender: channels.value.smtp.config.sender,
        username: channels.value.smtp.config.username,
        // 安全：仅在用户输入了新密码时才提交，空值表示不修改已保存的密码
        ...(channels.value.smtp.config.password ? { password: channels.value.smtp.config.password } : {}),
        use_tls: channels.value.smtp.config.use_tls,
        tested: channels.value.smtp.config.tested
      })
      await notificationChannelConfigsApi.update('smtp', { enabled: channels.value.smtp.enabled, config: {} })
    }
    ElMessage.success('管道配置已保存')
  } catch (error) {
    ElMessage.error('保存管道配置失败')
  } finally {
    savingChannel.value = false
  }
}

const onChannelToggle = async (channelKey: string) => {
  try {
    await notificationChannelConfigsApi.update(channelKey, { enabled: channels.value[channelKey as keyof typeof channels.value].enabled })
  } catch (error) {
    console.error('保存管道状态失败:', error)
  }
}

const onSmtpToggle = async (enabled: boolean) => {
  if (enabled && !channels.value.smtp.config.tested) {
    ElMessage.warning('请先配置并测试 SMTP 参数')
    channels.value.smtp.enabled = false
    return
  }
  try {
    await smtpConfigApi.update({ enabled })
    await notificationChannelConfigsApi.update('smtp', { enabled })
  } catch (error) {
    ElMessage.error('保存 SMTP 状态失败')
  }
}

const onItemEnableChange = async (key: string, enabled: boolean) => {
  try {
    await notificationItemsApi.update(key, { enabled })
  } catch (error) {
    console.error('保存通知项状态失败:', error)
  }
}

const testingSmtp = ref(false)

const testSmtp = async () => {
  const config = channels.value.smtp.config
  if (!config.host) { ElMessage.warning('请输入 SMTP 服务器地址'); return }
  if (!config.sender) { ElMessage.warning('请输入发件人邮箱'); return }
  if (!config.username) { ElMessage.warning('请输入用户名'); return }
  if (!smtpTestRecipient.value) { ElMessage.warning('请输入收件人邮箱'); return }

  testingSmtp.value = true
  try {
    const response = await fetch('/api/v1/notifications/test-smtp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host: config.host, port: config.port, sender: config.sender,
        username: config.username, password: config.password,
        use_tls: config.use_tls, recipient: smtpTestRecipient.value
      })
    })
    const result = await response.json()
    if (result.success) {
      channels.value.smtp.config.tested = true
      ElMessage.success(`测试邮件已发送至 ${smtpTestRecipient.value}`)
      try { await smtpConfigApi.update({ tested: true }) } catch (error) { console.error('保存 tested 状态失败:', error) }
    } else {
      ElMessage.error(`SMTP 测试失败: ${result.message}`)
    }
  } catch (error) {
    ElMessage.error('SMTP 测试请求失败')
  } finally {
    testingSmtp.value = false
  }
}

const saveSettings = async () => {
  savingSettings.value = true
  try {
    await systemConfigApi.update({
      analysis_frequency_minutes: settings.value.analysisFrequency,
      analysis_workers: settings.value.analysisWorkers,
      analysis_timeout_seconds: settings.value.analysisTimeout,
      forgiveness_param: settings.value.forgivenessParam,
      log_enabled: settings.value.logEnabled,
      log_retention_hours: settings.value.logRetentionHours,
    })
    ElMessage.success('配置已保存')
  } catch (error) {
    ElMessage.error('保存配置失败')
  } finally {
    savingSettings.value = false
  }
}

const exportLogs = async () => {
  exportingLogs.value = true
  try {
    const response = await logsApi.export()
    const blob = new Blob([response.data], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'iptv-manager-logs.txt'
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('日志导出成功')
  } catch (error) {
    ElMessage.error('日志导出失败')
  } finally {
    exportingLogs.value = false
  }
}

const exportConfig = async () => {
  exportingConfig.value = true
  try {
    const response = await fetch('/api/v1/config/backup')
    if (!response.ok) throw new Error('导出失败')
    const data = await response.json()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `iptv-manager-config-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('配置导出成功')
  } catch (error) {
    ElMessage.error('配置导出失败')
  } finally {
    exportingConfig.value = false
  }
}

const importConfig = async (file: File) => {
  importingConfig.value = true
  try {
    const text = await file.text()
    const configData = JSON.parse(text)
    const response = await fetch('/api/v1/config/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(configData)
    })
    if (!response.ok) throw new Error('导入失败')
    const result = await response.json()
    
    const details = result.details || {}
    const messages = []
    
    if (details.restored_sources?.length > 0) {
      messages.push(`已恢复 ${details.restored_sources.length} 个订阅源: ${details.restored_sources.join(', ')}`)
    }
    if (details.skipped_sources?.length > 0) {
      messages.push(`跳过 ${details.skipped_sources.length} 个已存在的订阅源: ${details.skipped_sources.map((s: any) => s.nickname).join(', ')}`)
    }
    if (details.failed_sources?.length > 0) {
      messages.push(`失败 ${details.failed_sources.length} 个: ${details.failed_sources.map((s: any) => `${s.nickname}(${s.reason})`).join(', ')}`)
    }
    
    if (messages.length > 0) {
      ElMessage.success(messages.join('；'))
    } else {
      ElMessage.success('配置导入成功')
    }
    
    setTimeout(() => { window.location.reload() }, 1500)
  } catch (error) {
    ElMessage.error('配置导入失败，请检查文件格式')
  } finally {
    importingConfig.value = false
  }
  return false
}

const viewLogs = async () => {
  logsDialogVisible.value = true
  logs.value = []
  logsPagination.value = { page: 1, pageSize: 50, total: 0, hasMore: true }
  await loadLogs()
}

const loadLogs = async (append: boolean = false) => {
  if (append) loadingMoreLogs.value = true
  else loadingLogs.value = true
  try {
    const params: any = { limit: logsPagination.value.pageSize, offset: (logsPagination.value.page - 1) * logsPagination.value.pageSize }
    if (logsFilterLevel.value) params.level = logsFilterLevel.value
    const response = await logsApi.list(params)
    if (append) logs.value = [...logs.value, ...response.data]
    else logs.value = response.data
    logsPagination.value.hasMore = response.data.length === logsPagination.value.pageSize
  } catch (error) {
    ElMessage.error('加载日志失败')
  } finally {
    loadingLogs.value = false
    loadingMoreLogs.value = false
  }
}

const loadMoreLogs = async () => {
  if (loadingMoreLogs.value || !logsPagination.value.hasMore) return
  logsPagination.value.page++
  await loadLogs(true)
}

const handleLogsFilterChange = async () => {
  logs.value = []
  logsPagination.value = { page: 1, pageSize: 50, total: 0, hasMore: true }
  await loadLogs()
}

const handleLogsScroll = (event: Event) => {
  const target = event.target as HTMLElement
  const scrollBottom = target.scrollHeight - target.scrollTop - target.clientHeight
  if (scrollBottom < 100 && logsPagination.value.hasMore && !loadingMoreLogs.value) loadMoreLogs()
}

const filteredLogs = computed(() => {
  if (!logsFilterLevel.value) return logs.value
  return logs.value.filter(log => log.level === logsFilterLevel.value)
})

const formatLogTime = (time: string) => {
  try {
    const date = new Date(time)
    return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return time }
}

const getLogLevelTagType = (level: string) => {
  const levelMap: Record<string, any> = { 'DEBUG': 'info', 'INFO': 'success', 'WARNING': 'warning', 'ERROR': 'danger', 'CRITICAL': 'danger' }
  return levelMap[level] || 'info'
}

const loadSmtpConfig = async () => {
  try {
    const response = await smtpConfigApi.get()
    const config = response.data
    channels.value.smtp.enabled = config.enabled
    channels.value.smtp.config.host = config.host || ''
    channels.value.smtp.config.port = config.port || 587
    channels.value.smtp.config.sender = config.sender || ''
    channels.value.smtp.config.username = config.username || ''
    // 安全：后端不再回传明文密码，仅返回是否已设置；输入框留空表示不修改
    channels.value.smtp.config.password_set = config.password_set || false
    channels.value.smtp.config.password = ''
    channels.value.smtp.config.use_tls = config.use_tls !== false
    channels.value.smtp.config.tested = config.tested || false
  } catch (error) {
    console.error('加载 SMTP 配置失败:', error)
  }
}

onMounted(() => {
  loadSystemConfig()
  loadSmtpConfig()
  loadAnalysisMode()
  loadNotificationItems()
  loadNotificationChannelConfigs()
})
</script>

<style scoped>
.settings-card {
  margin-bottom: 0;
  height: 100%;
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

.compact-form .el-form-item {
  margin-bottom: 16px;
}

.compact-form .el-form-item:last-child {
  margin-bottom: 0;
}

.form-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.full-width {
  width: 100%;
}

.full-width-buttons {
  width: 100%;
}

.notification-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.notification-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.notification-item:hover {
  background-color: var(--el-fill-color-light);
  border-color: var(--el-color-primary);
}

.item-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.item-name {
  font-weight: 500;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.arrow-icon {
  color: var(--el-text-color-secondary);
}

.channel-configs {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.channel-config-item {
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
}

.channel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.channel-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.channel-usage {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color);
}

.backup-section {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}

.backup-info {
  flex: 1;
  min-width: 200px;
}

.logs-filter {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.logs-container {
  max-height: 60vh;
  overflow-y: auto;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background-color: var(--el-fill-color-lighter);
}

.logs-empty {
  padding: 40px 0;
}

.logs-list {
  display: flex;
  flex-direction: column;
}

.logs-load-more {
  padding: 12px 16px;
  text-align: center;
}

.log-item {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-family: monospace;
  font-size: 13px;
}

.log-item:last-child {
  border-bottom: none;
}

.log-item.log-debug { background-color: #f4f4f5; }
.log-item.log-info { background-color: #f0f9ff; }
.log-item.log-warning { background-color: #fdf6ec; }
.log-item.log-error { background-color: #fef0f0; }
.log-item.log-critical { background-color: #fef0f0; border-left: 4px solid var(--el-color-danger); }

.log-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}

.log-time {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.log-logger {
  color: var(--el-text-color-regular);
  font-size: 12px;
}

.log-message {
  color: var(--el-text-color-primary);
  word-break: break-all;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .settings-card {
    margin-bottom: 20px;
  }
  
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .notification-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .item-meta {
    width: 100%;
    justify-content: flex-end;
  }
  
  .backup-section {
    flex-direction: column;
    align-items: stretch;
  }
  
  .backup-info {
    margin-bottom: 12px;
  }
  
  .logs-filter {
    flex-direction: column;
    align-items: stretch;
  }
  
  .logs-filter .el-select {
    width: 100% !important;
  }
}
</style>
