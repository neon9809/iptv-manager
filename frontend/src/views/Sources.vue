<template>
  <div class="sources">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>互联网订阅源</span>
          <el-button type="primary" @click="showAddDialog = true">
            <el-icon><Plus /></el-icon>
            添加订阅源
          </el-button>
        </div>
      </template>

      <div v-if="sources.length === 0" class="empty-state">
        <el-empty description="暂无订阅源，请添加" />
      </div>

      <div v-else>
        <el-row :gutter="20">
          <el-col :span="24" v-for="source in sources" :key="source.id">
            <el-card class="source-card" shadow="hover">
              <el-descriptions :column="3" border>
                <el-descriptions-item label="订阅源昵称">
                  {{ source.nickname }}
                </el-descriptions-item>
                <el-descriptions-item label="刷新频率">
                  {{ source.refresh_frequency_hours }} 小时
                </el-descriptions-item>
                <el-descriptions-item label="上次刷新">
                  {{ formatTime(source.last_refresh_time) }}
                </el-descriptions-item>
                <el-descriptions-item label="刷新状态">
                  <el-tag :type="source.last_refresh_status === 'success' ? 'success' : 'danger'">
                    {{ source.last_refresh_status }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="直播流数">
                  {{ source.stream_count }}
                </el-descriptions-item>
                <el-descriptions-item label="操作">
                  <el-button size="small" @click="editSource(source)">
                    编辑
                  </el-button>
                  <el-button size="small" @click="refreshSource(source.id)">
                    刷新
                  </el-button>
                  <el-button size="small" type="danger" @click="deleteSource(source)">
                    删除
                  </el-button>
                </el-descriptions-item>
              </el-descriptions>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </el-card>

    <el-dialog v-model="showAddDialog" title="添加订阅源" width="500px">
      <el-form :model="newSource" label-width="100px">
        <el-form-item label="订阅源URL" required>
          <el-input v-model="newSource.url" placeholder="https://example.com/iptv.m3u" />
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="newSource.nickname" placeholder="自定义名称" />
        </el-form-item>
        <el-form-item label="刷新频率">
          <el-input-number v-model="newSource.refresh_frequency_hours" :min="1" :max="168" />
          <span style="margin-left: 10px">小时</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addSource" :loading="loading">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditDialog" title="编辑订阅源" width="500px">
      <el-form :model="editingSource" label-width="100px">
        <el-form-item label="订阅源URL">
          <el-input v-model="editingSource.url" disabled />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="editingSource.nickname" placeholder="自定义名称" />
        </el-form-item>
        <el-form-item label="刷新频率">
          <el-input-number v-model="editingSource.refresh_frequency_hours" :min="1" :max="168" />
          <span style="margin-left: 10px">小时</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="updateSource" :loading="loading">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { sourcesApi, streamsApi } from '../api'

const sources = ref<any[]>([])
const showAddDialog = ref(false)
const showEditDialog = ref(false)
const loading = ref(false)

const newSource = ref({
  url: '',
  nickname: '',
  refresh_frequency_hours: 6,
})

const editingSource = ref({
  id: 0,
  url: '',
  nickname: '',
  refresh_frequency_hours: 6,
})

const loadSources = async () => {
  try {
    const res = await sourcesApi.list()
    const streamsRes = await streamsApi.list()
    
    const streams = streamsRes.data
    
    sources.value = res.data.map((source: any) => {
      const sourceStreams = streams.filter((s: any) => 
        s.source_ids && s.source_ids.includes(source.id)
      )
      const channelIds = new Set(sourceStreams.map((s: any) => s.channel_id).filter(Boolean))
      return {
        ...source,
        channel_count: channelIds.size,
        stream_count: sourceStreams.length
      }
    })
  } catch (error) {
    ElMessage.error('加载订阅源失败')
  }
}

const addSource = async () => {
  if (!newSource.value.url || !newSource.value.nickname) {
    ElMessage.warning('请填写完整信息')
    return
  }

  loading.value = true
  try {
    await sourcesApi.create(newSource.value)
    ElMessage.success('添加成功')
    showAddDialog.value = false
    newSource.value = { url: '', nickname: '', refresh_frequency_hours: 6 }
    await loadSources()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '添加失败')
  } finally {
    loading.value = false
  }
}

const refreshSource = async (id: number) => {
  try {
    await sourcesApi.refresh(id)
    ElMessage.success('刷新成功')
    await loadSources()
  } catch (error) {
    ElMessage.error('刷新失败')
  }
}

const editSource = (source: any) => {
  editingSource.value = {
    id: source.id,
    url: source.url,
    nickname: source.nickname,
    refresh_frequency_hours: source.refresh_frequency_hours,
  }
  showEditDialog.value = true
}

const updateSource = async () => {
  loading.value = true
  try {
    await sourcesApi.update(editingSource.value.id, {
      nickname: editingSource.value.nickname,
      refresh_frequency_hours: editingSource.value.refresh_frequency_hours,
    })
    ElMessage.success('更新成功')
    showEditDialog.value = false
    await loadSources()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '更新失败')
  } finally {
    loading.value = false
  }
}

const deleteSource = async (source: any) => {
  const channelCount = source.channel_count || 0
  const streamCount = source.stream_count || 0
  
  if (channelCount > 0 && streamCount > 0) {
    const message = `此订阅源包含 ${channelCount} 个频道和 ${streamCount} 个直播流。\n\n请选择删除操作：\n\n` +
      `1. 点击「同时删除」：删除订阅源和所有直播流\n` +
      `2. 点击「仅删除源」：只删除订阅源，保留直播流\n` +
      `3. 点击「取消」或关闭：不执行任何操作`
    
    await ElMessageBox.confirm(message, '删除确认', {
      confirmButtonText: '同时删除',
      cancelButtonText: '仅删除源',
      type: 'warning',
      distinguishCancelAndClose: true,
      closeOnClickModal: false,
    }).then(async () => {
      await sourcesApi.delete(source.id, true)
      ElMessage.success('已删除订阅源和所有关联直播流')
    }).catch(async (action) => {
      if (action === 'cancel') {
        await sourcesApi.delete(source.id, false)
        ElMessage.success('已删除订阅源，保留直播流')
      }
    })
  } else {
    try {
      let message = '确定要删除此订阅源吗?'
      if (channelCount > 0) {
        message = `此订阅源包含 ${channelCount} 个频道。`
      }
      await ElMessageBox.confirm(message, '删除确认', {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await sourcesApi.delete(source.id, false)
      ElMessage.success('删除成功')
    } catch (error: any) {
      if (error !== 'cancel') {
        ElMessage.error('删除失败')
      }
    }
  }
  await loadSources()
}

const formatTime = (time: string | null) => {
  if (!time) return '从未'
  return new Date(time).toLocaleString('zh-CN')
}

onMounted(() => {
  loadSources()
})
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.source-card {
  margin-bottom: 20px;
}

.empty-state {
  padding: 40px 0;
}
</style>
