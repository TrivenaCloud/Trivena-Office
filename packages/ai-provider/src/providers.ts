import type { AiProviderId, AiProviderMeta, AiSettings, LegacyAiSettings } from './types'

/**
 * Trivena Cloud LLM proxy endpoints (OpenAI/Anthropic/Gemini compatible).
 * Auth uses the TrivOffice API key from Trivena Cloud sign-in.
 */
export const GENSPARK_LLM_BASE_URLS = {
  anthropic: 'https://cloud.trivena.tech/api/llm/anthropic',
  gemini: 'https://cloud.trivena.tech/api/llm/gemini/v1beta',
  openai: 'https://cloud.trivena.tech/api/llm/openai/v1',
} as const

/** Billing / telemetry agent type for Trivena-proxied traffic. */
export const GENSPARK_AGENT_TYPE = 'trivoffice'

export function gensparkAttributionHeaders(baseUrl?: string): Record<string, string> {
  if (!baseUrl) return {}
  if (
    baseUrl.includes('genspark.ai') ||
    baseUrl.includes('trivena.tech') ||
    baseUrl.includes('trivena.app')
  ) {
    return { 'X-Agent-Type': GENSPARK_AGENT_TYPE }
  }
  return {}
}

export const AI_PROVIDERS: AiProviderMeta[] = [
  {
    id: 'genspark',
    label: 'Trivena Cloud',
    // NVIDIA NIM models via cloud.trivena.tech (NVIDIA_API_KEY on the server).
    // Legacy Gemini ids still work; the gateway remaps them to the NIM default.
    models: ['z-ai/glm-5.2'],
    defaultModel: 'z-ai/glm-5.2',
    keyPlaceholder: 'Not required — sign in to Trivena Cloud',
  },
  {
    id: 'anthropic',
    label: 'Claude',
    models: [
      'claude-sonnet-5',
      'claude-opus-4-8',
      'claude-opus-4-7',
      'claude-sonnet-4-6',
      'claude-opus-4-6',
      'claude-opus-4-5-20251101',
      'claude-haiku-4-5-20251001',
      'claude-sonnet-4-5-20250929',
    ],
    defaultModel: 'claude-opus-4-7',
    keyPlaceholder: 'sk-ant-api03-...',
  },
  {
    id: 'gemini',
    label: 'Gemini',
    models: ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash'],
    defaultModel: 'gemini-2.5-flash',
    keyPlaceholder: 'AIza...',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    models: ['deepseek-chat', 'deepseek-reasoner'],
    defaultModel: 'deepseek-chat',
    keyPlaceholder: 'sk-...',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    models: ['gpt-4.1', 'gpt-4.1-mini', 'gpt-4o', 'gpt-4o-mini'],
    defaultModel: 'gpt-4.1-mini',
    keyPlaceholder: 'sk-...',
  },
  {
    id: 'custom',
    label: 'Custom',
    models: [],
    defaultModel: '',
    keyPlaceholder: 'API Key',
    needsBaseUrl: true,
  },
]

/**
 * Fresh settings with every provider's default model and an empty key,
 * except providers listed in `defaultApiKeys` (e.g. an app-specific
 * preconfigured Anthropic key). Callers own that policy; this package
 * has no hardcoded keys.
 */
export function defaultAiSettings(
  defaultApiKeys?: Partial<Record<AiProviderId, string>>,
): AiSettings {
  const providers = {} as AiSettings['providers']
  for (const meta of AI_PROVIDERS) {
    providers[meta.id] = {
      apiKey: defaultApiKeys?.[meta.id] ?? '',
      model: meta.defaultModel,
      baseUrl: meta.needsBaseUrl ? '' : undefined,
    }
  }
  return { provider: 'genspark', providers }
}

/**
 * Merge on-disk settings over freshly computed defaults, migrating the
 * pre-provider shape (a single OpenAI-compatible endpoint) into the
 * "custom" provider slot. `stored` is whatever the caller read from its
 * settings file (already JSON-parsed); this function does no file I/O.
 */
export function resolveAiSettings(
  stored: Partial<AiSettings> & LegacyAiSettings,
  defaults: AiSettings,
): AiSettings {
  if (!stored.providers) {
    if (stored.apiKey) {
      defaults.providers.custom = {
        apiKey: stored.apiKey,
        model: stored.model ?? '',
        baseUrl: stored.baseUrl ?? 'https://api.openai.com/v1',
      }
    }
    return defaults
  }
  const providers = { ...defaults.providers, ...stored.providers }
  // Migrate Trivena Cloud users off Gemini defaults onto NVIDIA GLM.
  const genspark = providers.genspark
  if (genspark?.model && /^(gemini|google\/)/i.test(genspark.model)) {
    providers.genspark = { ...genspark, model: defaults.providers.genspark.model }
  }
  return {
    provider: stored.provider ?? defaults.provider,
    providers,
  }
}
