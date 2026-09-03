import apiClient from './client'

export interface ModelCatalogResponse {
  object: 'model_catalog'
  schema_version: 1
  generated_at: string
  revision: string
  chat_models: string[]
  image_models: string[]
  all_models: string[]
  defaults: {
    chat_model: string
    image_model: string
  }
  capabilities: {
    image_upscale: boolean
    high_resolution_image_models: string[]
  }
  source: {
    chat: 'config' | 'accounts' | 'fallback'
    image: 'config' | 'accounts' | 'fallback'
  }
  openai_models_endpoint: '/v1/models'
}

const MODEL_LABELS: Record<string, string> = {
  'gemini-auto': 'Gemini 自动',
  'gemini-2.5-pro': 'Gemini 2.5 Pro',
  'gemini-3.5-flash': 'Gemini 3.5 Flash',
  'gemini-3.1-pro-preview': 'Gemini 3.1 Pro 预览',
  'gemini-imagen': 'Gemini Imagen 生图',
}

export function modelDisplayLabel(model: string): string {
  const normalized = String(model || '').trim()
  if (normalized === 'auto') return '自动模型'
  return MODEL_LABELS[normalized]
    || (normalized.startsWith('gemini-') ? `Gemini · ${normalized.slice('gemini-'.length)}` : normalized)
}

export const modelsApi = {
  catalog: () => apiClient.get<never, ModelCatalogResponse>('/api/model-catalog'),
}
