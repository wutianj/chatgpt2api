import apiClient from './client'

export interface UserTask {
  id: string
  task_type: string
  model: string
  status: string
  request: Record<string, unknown>
  result: unknown
  error_code: string | null
  created_at: string | null
  completed_at: string | null
}

export const tasksApi = {
  list: (limit = 50) => apiClient.get<never, { items: UserTask[] }>('/api/tasks', { params: { limit } }),
  get: (taskId: string) => apiClient.get<never, UserTask>(`/api/tasks/${encodeURIComponent(taskId)}`),
  cancel: (taskId: string) => apiClient.post<never, { item: UserTask }>(`/api/tasks/${encodeURIComponent(taskId)}/cancel`),
}
