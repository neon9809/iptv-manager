import axios from 'axios'

const API_BASE = ''

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
})

export const healthApi = {
  check: () => api.get('/health'),
}

export const sourcesApi = {
  list: () => api.get('/api/v1/sources'),
  create: (data: { nickname: string; url: string; refresh_frequency_hours?: number }) =>
    api.post('/api/v1/sources', data),
  update: (id: number, data: { nickname?: string; url?: string; refresh_frequency_hours?: number }) =>
    api.put(`/api/v1/sources/${id}`, data),
  delete: (id: number, deleteStreams: boolean = false) => 
    api.delete(`/api/v1/sources/${id}`, { params: { delete_streams: deleteStreams } }),
  refresh: (id: number) => api.post(`/api/v1/sources/${id}/refresh`),
}

export const channelsApi = {
  list: () => api.get('/api/v1/channels'),
  updateOrder: (id: number, order_index: number) =>
    api.put(`/api/v1/channels/${id}/order`, { order_index }),
}

export const streamsApi = {
  list: (params?: { channel_id?: number; unmatched?: boolean }) =>
    api.get('/api/v1/streams', { params }),
  updateActive: (id: string, active: string) =>
    api.put(`/api/v1/streams/${id}/active`, { active }),
  bindChannel: (streamId: string, channelId: number) =>
    api.post(`/api/v1/streams/${streamId}/bind`, null, { params: { channel_id: channelId } }),
  unbindChannel: (streamId: string) =>
    api.post(`/api/v1/streams/${streamId}/unbind`),
  batchBind: (streamIds: string[], channelId: number | null) =>
    api.post('/api/v1/streams/batch-bind', { stream_ids: streamIds, channel_id: channelId }),
}

export const channelBindingApi = {
  createAndBind: (channelName: string, streamIds: string[]) =>
    api.post('/api/v1/channels/create-and-bind', { channel_name: channelName, stream_ids: streamIds }),
}

export const analysisApi = {
  trigger: (data: { stream_ids?: string[]; mode?: string }) =>
    api.post('/api/v1/analysis/trigger', data),
  getMode: () => api.get('/api/v1/analysis/mode'),
  setMode: (mode: string) => api.post('/api/v1/analysis/mode', { mode }),
}

export const benchmarkApi = {
  get: () => api.get('/api/v1/benchmark'),
}

export const notificationsApi = {
  list: () => api.get('/api/v1/notifications'),
  create: (data: { issuer: string; subject: string; context: string; severity?: string; notification_channels?: string[]; valid_until?: string }) =>
    api.post('/api/v1/notifications', data),
  markRead: (id: number) => api.put(`/api/v1/notifications/${id}/read`),
  delete: (id: number) => api.delete(`/api/v1/notifications/${id}`),
}

export const smtpConfigApi = {
  get: () => api.get('/api/v1/smtp-config'),
  update: (data: {
    enabled?: boolean;
    host?: string;
    port?: number;
    sender?: string;
    username?: string;
    password?: string;
    use_tls?: boolean;
    tested?: boolean;
  }) => api.put('/api/v1/smtp-config', data),
}

export const playlistApi = {
  getPlayfast: () => api.get('/playfast', { responseType: 'text' }),
  getPlaybest: () => api.get('/playbest', { responseType: 'text' }),
  getPlaystable: () => api.get('/playstable', { responseType: 'text' }),
  getPlayoptimized: () => api.get('/playoptimized', { responseType: 'text' }),
}

export const streamDomainsApi = {
  get: () => api.get('/api/v1/stream-domains'),
}

export const systemConfigApi = {
  get: () => api.get('/api/v1/system-config'),
  update: (data: {
    analysis_frequency_minutes?: number;
    analysis_workers?: number;
    analysis_timeout_seconds?: number;
    forgiveness_param?: number;
    source_refresh_frequency_hours?: number;
    log_enabled?: boolean;
    log_retention_hours?: number;
  }) => api.put('/api/v1/system-config', data),
}

export const notificationItemsApi = {
  list: () => api.get('/api/v1/notification-items'),
  update: (itemKey: string, data: {
    enabled?: boolean;
    threshold_value?: number;
    statuses?: string[];
    channels?: string[];
  }) => api.put(`/api/v1/notification-items/${itemKey}`, data),
}

export const notificationChannelConfigsApi = {
  list: () => api.get('/api/v1/notification-channel-configs'),
  update: (channelKey: string, data: {
    enabled?: boolean;
    config?: any;
  }) => api.put(`/api/v1/notification-channel-configs/${channelKey}`, data),
}

export const logsApi = {
  list: (params?: { limit?: number; level?: string }) => api.get('/api/v1/logs', { params }),
  export: () => api.get('/api/v1/logs/export', { responseType: 'text' }),
}

export default api
