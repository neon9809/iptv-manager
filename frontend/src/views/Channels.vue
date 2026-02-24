<template>
  <div class="channels">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>频道线路管理</span>
          <el-radio-group v-model="filterType" size="small">
            <el-radio-button label="available">可用频道</el-radio-button>
            <el-radio-button label="all">所有频道</el-radio-button>
            <el-radio-button label="unmatched">未匹配</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <div v-if="loading" class="loading">
        <el-skeleton :rows="10" animated />
      </div>

      <div v-else-if="filterType === 'unmatched'">
        <div v-if="unmatchedStreams.length === 0" class="empty-state">
          <el-empty description="没有未匹配的直播流" />
        </div>
        <div v-else>
          <!-- 批量操作栏 -->
          <div class="batch-actions" v-if="selectedStreams.length > 0">
            <el-alert
              :title="`已选择 ${selectedStreams.length} 个直播流`"
              type="info"
              :closable="false"
            >
              <template #default>
                <el-space>
                  <el-button size="small" type="primary" @click="showBatchBindDialog">
                    批量绑定到频道
                  </el-button>
                  <el-button size="small" type="success" @click="showCreateChannelDialog">
                    创建新频道并绑定
                  </el-button>
                  <el-button size="small" @click="clearSelection">清除选择</el-button>
                </el-space>
              </template>
            </el-alert>
          </div>

          <el-table
            :data="unmatchedStreams"
            @selection-change="handleSelectionChange"
            style="width: 100%"
          >
            <el-table-column type="selection" width="55" />
            <el-table-column label="名称" prop="name" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.name || '未命名' }}
              </template>
            </el-table-column>
            <el-table-column label="URL" show-overflow-tooltip>
              <template #default="{ row }">
                {{ sanitizeUrl(row.url) }}
              </template>
            </el-table-column>
            <el-table-column label="延迟" width="100">
              <template #default="{ row }">
                {{ row.latency_ms ? `${row.latency_ms}ms` : '未测试' }}
              </template>
            </el-table-column>
            <el-table-column label="稳定性" width="120">
              <template #default="{ row }">
                <el-progress
                  v-if="row.stability_score"
                  :percentage="row.stability_score"
                  :status="row.stability_score > 80 ? 'success' : row.stability_score > 50 ? 'warning' : 'exception'"
                  :stroke-width="8"
                />
                <span v-else>未测试</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="340">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="openStream(row.url)">▶ 预览</el-button>
                <el-button size="small" @click="analyzeStream(row.id)">测试</el-button>
                <el-button size="small" type="primary" @click="showBindDialog(row)">绑定</el-button>
                <el-button size="small" type="success" @click="showCreateChannelFromStream(row)">新建频道</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <div v-else>
        <div v-if="filteredChannels.length === 0" class="empty-state">
          <el-empty description="暂无可用频道">
            <template #description>
              <div>
                <p>暂无可用频道</p>
                <p class="empty-tip">请先添加订阅源，系统将自动导入频道</p>
              </div>
            </template>
            <el-button type="primary" @click="$router.push('/sources')">去添加订阅源</el-button>
          </el-empty>
        </div>
        <el-collapse v-else v-model="activeChannels">
          <el-collapse-item
            v-for="channel in filteredChannels"
            :key="channel.id"
            :name="channel.id"
          >
            <template #title>
              <div class="channel-header">
                <span class="channel-name">{{ channel.standard_name }}</span>
                <el-tag size="small" type="info">{{ channel.category || '未分类' }}</el-tag>
                <el-tag size="small" type="success">{{ getChannelStreams(channel.id).length }} 个源</el-tag>
              </div>
            </template>

            <div class="channel-streams">
              <!-- 批量操作栏 -->
              <div class="batch-actions" v-if="getChannelSelectedStreams(channel.id).length > 0">
                <el-alert
                  :title="`已选择 ${getChannelSelectedStreams(channel.id).length} 个直播流`"
                  type="info"
                  :closable="false"
                >
                  <template #default>
                    <el-space>
                      <el-button size="small" type="danger" @click="batchUnbind(channel.id)">
                        批量解绑
                      </el-button>
                      <el-button size="small" @click="clearChannelSelection(channel.id)">清除选择</el-button>
                    </el-space>
                  </template>
                </el-alert>
              </div>

              <el-table
                :data="getChannelStreams(channel.id)"
                @selection-change="(selection: any[]) => handleChannelSelectionChange(channel.id, selection)"
                style="width: 100%"
              >
                <el-table-column type="selection" width="55" />
                <el-table-column label="名称" prop="name" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ row.name || '未命名' }}
                  </template>
                </el-table-column>
                <el-table-column label="来源" width="100">
                  <template #default="{ row }">
                    {{ getSourceName(row.source_ids) }}
                  </template>
                </el-table-column>
                <el-table-column label="视频" width="180">
                  <template #default="{ row }">
                    <span v-if="row.video_analysis_failed">
                      <el-tag size="small" type="danger">分析失败</el-tag>
                    </span>
                    <span v-else-if="row.video_width">
                      {{ row.video_width }}×{{ row.video_height }}
                      <span v-if="row.video_fps"> @{{ row.video_fps }}fps</span>
                      <br>
                      <el-tag size="small" type="info">{{ row.video_codec || '未知' }}</el-tag>
                      <el-tag v-if="row.video_bit_depth" size="small" type="warning">{{ row.video_bit_depth }}bit</el-tag>
                    </span>
                    <span v-else>未分析</span>
                  </template>
                </el-table-column>
                <el-table-column label="音频" width="80">
                  <template #default="{ row }">
                    <el-tag v-if="row.audio_codec" size="small" type="success">{{ row.audio_codec }}</el-tag>
                    <span v-else-if="row.video_analysis_failed">-</span>
                    <span v-else>未分析</span>
                  </template>
                </el-table-column>
                <el-table-column label="延迟" width="100">
                  <template #default="{ row }">
                    <el-tag v-if="row.latency_ms" size="small" type="success">
                      {{ row.latency_ms }}ms
                    </el-tag>
                    <el-tag v-else-if="row.enhanced_analysis_failed" size="small" type="danger">失败</el-tag>
                    <span v-else>未测试</span>
                  </template>
                </el-table-column>
                <el-table-column label="码率" width="100">
                  <template #default="{ row }">
                    <el-tag v-if="row.bitrate_kbps" size="small" type="warning">
                      {{ row.bitrate_kbps }}kbps
                    </el-tag>
                    <span v-else-if="row.enhanced_analysis_failed">-</span>
                    <span v-else>未测试</span>
                  </template>
                </el-table-column>
                <el-table-column label="稳定性" width="120">
                  <template #default="{ row }">
                    <el-progress
                      v-if="row.stability_score"
                      :percentage="row.stability_score"
                      :status="row.stability_score > 80 ? 'success' : row.stability_score > 50 ? 'warning' : 'exception'"
                      :stroke-width="8"
                    />
                    <span v-else-if="row.enhanced_analysis_failed">-</span>
                    <span v-else>未测试</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="100">
                  <template #default="{ row }">
                    <el-tag :type="getActiveType(row.active)" size="small">
                      {{ getActiveText(row.active) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="320">
                  <template #default="{ row }">
                    <el-button size="small" type="primary" @click="openStream(row.url)">▶ 预览</el-button>
                    <el-button size="small" @click="analyzeStream(row.id)">测试</el-button>
                    <el-button
                      size="small"
                      :type="row.active === 'true' ? 'warning' : 'success'"
                      @click="toggleStreamActive(row)"
                    >
                      {{ row.active === 'true' ? '禁用' : '启用' }}
                    </el-button>
                    <el-button size="small" type="danger" @click="unbindStream(row.id)">解绑</el-button>
                  </template>
                </el-table-column>
              </el-table>

              <el-empty v-if="getChannelStreams(channel.id).length === 0" description="暂无直播流" />
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-card>

    <!-- 单个绑定对话框 -->
    <el-dialog v-model="bindDialogVisible" title="绑定频道" width="500px">
      <el-form label-width="80px">
        <el-form-item label="选择频道">
          <el-select v-model="selectedChannelId" filterable placeholder="搜索频道" style="width: 100%">
            <el-option
              v-for="ch in channels"
              :key="ch.id"
              :label="ch.standard_name"
              :value="ch.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="bindStream">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量绑定对话框 -->
    <el-dialog v-model="batchBindDialogVisible" title="批量绑定频道" width="500px">
      <el-alert
        :title="`将 ${selectedStreams.length} 个直播流绑定到指定频道`"
        type="info"
        :closable="false"
        style="margin-bottom: 20px"
      />
      <el-form label-width="80px">
        <el-form-item label="选择频道">
          <el-select v-model="selectedChannelId" filterable placeholder="搜索频道" style="width: 100%">
            <el-option
              v-for="ch in channels"
              :key="ch.id"
              :label="ch.standard_name"
              :value="ch.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchBindDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="batchBind">确定</el-button>
      </template>
    </el-dialog>

    <!-- 创建新频道对话框 -->
    <el-dialog v-model="createChannelDialogVisible" title="创建新频道并绑定" width="500px">
      <el-alert
        :title="`将 ${selectedStreams.length} 个直播流绑定到新频道`"
        type="info"
        :closable="false"
        style="margin-bottom: 20px"
      />
      <el-form label-width="100px">
        <el-form-item label="频道名称">
          <el-input v-model="newChannelName" placeholder="输入新频道名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createChannelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createChannelAndBind">确定</el-button>
      </template>
    </el-dialog>

    <!-- 从单个流创建新频道对话框 -->
    <el-dialog v-model="createChannelFromStreamVisible" title="新建频道" width="500px">
      <el-form label-width="100px">
        <el-form-item label="直播流名称">
          <el-input :model-value="currentStreamForNewChannel?.name || ''" disabled />
        </el-form-item>
        <el-form-item label="频道名称">
          <el-input v-model="newChannelFromStreamName" placeholder="可手动调整频道名称" />
          <div class="form-tip">默认使用直播流名称，可根据需要修改</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createChannelFromStreamVisible = false">取消</el-button>
        <el-button type="primary" @click="createChannelFromStream">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { channelsApi, streamsApi, analysisApi, channelBindingApi, sourcesApi } from '../api'
import { sanitizeUrl } from '../utils/url'

const loading = ref(false)
const channels = ref<any[]>([])
const streams = ref<any[]>([])
const sources = ref<any[]>([])
const filterType = ref('available')
const activeChannels = ref<number[]>([])

// 单个绑定
const bindDialogVisible = ref(false)
const selectedChannelId = ref<number | null>(null)
const currentStream = ref<any>(null)

// 批量绑定
const batchBindDialogVisible = ref(false)
const selectedStreams = ref<any[]>([])

// 创建新频道
const createChannelDialogVisible = ref(false)
const newChannelName = ref('')

// 从单个流创建新频道
const createChannelFromStreamVisible = ref(false)
const currentStreamForNewChannel = ref<any>(null)
const newChannelFromStreamName = ref('')

// 每个频道的选中项
const channelSelections = ref<Map<number, any[]>>(new Map())

const filteredChannels = computed(() => {
  if (filterType.value === 'available') {
    return channels.value.filter(ch => getChannelStreams(ch.id).length > 0)
  }
  return channels.value
})

const unmatchedStreams = computed(() => {
  return streams.value.filter(s => !s.channel_id)
})

const getChannelStreams = (channelId: number) => {
  return streams.value.filter(s => s.channel_id === channelId)
}

const getChannelSelectedStreams = (channelId: number) => {
  return channelSelections.value.get(channelId) || []
}

const getActiveType = (active: string) => {
  if (active === 'true') return 'success'
  if (active === 'false') return 'danger'
  return 'info'
}

const getActiveText = (active: string) => {
  if (active === 'true') return '强制启用'
  if (active === 'false') return '已禁用'
  return '自动'
}

const getSourceName = (sourceIds: number[]) => {
  if (!sourceIds || sourceIds.length === 0) return '未知'
  const firstSourceId = sourceIds[0]
  const source = sources.value.find(s => s.id === firstSourceId)
  return source?.nickname || '未知'
}

const loadData = async () => {
  loading.value = true
  try {
    const [channelsRes, streamsRes, sourcesRes] = await Promise.all([
      channelsApi.list(),
      streamsApi.list(),
      sourcesApi.list(),
    ])
    channels.value = channelsRes.data
    streams.value = streamsRes.data
    sources.value = sourcesRes.data
  } catch (error) {
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

const analyzeStream = async (streamId: string) => {
  try {
    ElMessage.info('开始分析...')
    const response = await analysisApi.trigger({ stream_ids: [streamId], mode: 'full' })
    if (response.data.status === 'submitted') {
      ElMessage.success('分析任务已提交，正在高优先级处理中...')
    }
    await loadData()
  } catch (error) {
    ElMessage.error('分析失败')
  }
}

const toggleStreamActive = async (stream: any) => {
  const newActive = stream.active === 'true' ? 'false' : 'true'
  try {
    await streamsApi.updateActive(stream.id, newActive)
    ElMessage.success('更新成功')
    await loadData()
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

// 单个绑定
const showBindDialog = (stream: any) => {
  currentStream.value = stream
  selectedChannelId.value = null
  bindDialogVisible.value = true
}

const bindStream = async () => {
  if (!selectedChannelId.value || !currentStream.value) {
    ElMessage.warning('请选择频道')
    return
  }
  try {
    await streamsApi.bindChannel(currentStream.value.id, selectedChannelId.value)
    ElMessage.success('绑定成功')
    bindDialogVisible.value = false
    await loadData()
  } catch (error) {
    ElMessage.error('绑定失败')
  }
}

// 单个解绑
const unbindStream = async (streamId: string) => {
  try {
    await ElMessageBox.confirm('确定要解绑这个直播流吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await streamsApi.unbindChannel(streamId)
    ElMessage.success('解绑成功')
    await loadData()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('解绑失败')
    }
  }
}

// 未匹配流的批量选择
const handleSelectionChange = (selection: any[]) => {
  selectedStreams.value = selection
}

const clearSelection = () => {
  selectedStreams.value = []
}

// 批量绑定
const showBatchBindDialog = () => {
  selectedChannelId.value = null
  batchBindDialogVisible.value = true
}

const batchBind = async () => {
  if (!selectedChannelId.value) {
    ElMessage.warning('请选择频道')
    return
  }
  try {
    const streamIds = selectedStreams.value.map(s => s.id)
    await streamsApi.batchBind(streamIds, selectedChannelId.value)
    ElMessage.success(`成功绑定 ${streamIds.length} 个直播流`)
    batchBindDialogVisible.value = false
    selectedStreams.value = []
    await loadData()
  } catch (error) {
    ElMessage.error('批量绑定失败')
  }
}

// 创建新频道并绑定
const showCreateChannelDialog = () => {
  newChannelName.value = ''
  createChannelDialogVisible.value = true
}

const createChannelAndBind = async () => {
  if (!newChannelName.value.trim()) {
    ElMessage.warning('请输入频道名称')
    return
  }
  try {
    const streamIds = selectedStreams.value.map(s => s.id)
    await channelBindingApi.createAndBind(newChannelName.value.trim(), streamIds)
    ElMessage.success(`成功创建频道 '${newChannelName.value}' 并绑定 ${streamIds.length} 个直播流`)
    createChannelDialogVisible.value = false
    selectedStreams.value = []
    await loadData()
  } catch (error) {
    ElMessage.error('创建频道并绑定失败')
  }
}

// 频道内批量选择
const handleChannelSelectionChange = (channelId: number, selection: any[]) => {
  channelSelections.value.set(channelId, selection)
}

const clearChannelSelection = (channelId: number) => {
  channelSelections.value.set(channelId, [])
}

// 批量解绑
const batchUnbind = async (channelId: number) => {
  const selected = getChannelSelectedStreams(channelId)
  if (selected.length === 0) return

  try {
    await ElMessageBox.confirm(`确定要解绑选中的 ${selected.length} 个直播流吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const streamIds = selected.map(s => s.id)
    await streamsApi.batchBind(streamIds, null)
    ElMessage.success(`成功解绑 ${streamIds.length} 个直播流`)
    channelSelections.value.set(channelId, [])
    await loadData()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('批量解绑失败')
    }
  }
}

// 从单个流创建新频道
const showCreateChannelFromStream = (stream: any) => {
  currentStreamForNewChannel.value = stream
  newChannelFromStreamName.value = stream.name || ''
  createChannelFromStreamVisible.value = true
}

const createChannelFromStream = async () => {
  if (!newChannelFromStreamName.value.trim()) {
    ElMessage.warning('请输入频道名称')
    return
  }
  if (!currentStreamForNewChannel.value) {
    ElMessage.error('未选择直播流')
    return
  }
  try {
    await channelBindingApi.createAndBind(
      newChannelFromStreamName.value.trim(),
      [currentStreamForNewChannel.value.id]
    )
    ElMessage.success(`成功创建频道 '${newChannelFromStreamName.value}'`)
    createChannelFromStreamVisible.value = false
    currentStreamForNewChannel.value = null
    newChannelFromStreamName.value = ''
    await loadData()
  } catch (error) {
    ElMessage.error('创建频道失败')
  }
}

// 在新页面打开直播流
const openStream = (url: string) => {
  if (!url) {
    ElMessage.warning('直播流地址为空')
    return
  }
  window.open(url, '_blank')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.channel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.channel-name {
  font-weight: bold;
}

.channel-streams {
  padding: 10px 0;
}

.batch-actions {
  margin-bottom: 15px;
}

.loading {
  padding: 20px;
}

.empty-state {
  padding: 40px 0;
}

.empty-tip {
  font-size: 14px;
  color: #909399;
  margin-top: 8px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}
</style>
