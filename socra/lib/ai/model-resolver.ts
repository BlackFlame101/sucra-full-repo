import { createGoogleGenerativeAI } from "@ai-sdk/google"
import { createOpenAI } from "@ai-sdk/openai"
import { createAnthropic } from "@ai-sdk/anthropic"

export type Provider = "google" | "openai" | "anthropic" | "xai"

export interface ModelConfig {
  provider?: Provider
  model?: string
  apiKey?: string
}

export interface ModelOption {
  id: string
  label: string
}

export interface ProviderInfo {
  id: Provider
  label: string
  models: ModelOption[]
  keyPlaceholder: string
  keyPrefix: string
}

export const PROVIDERS: ProviderInfo[] = [
  {
    id: "google",
    label: "Google Gemini",
    models: [
      { id: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite (default)" },
      { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
      { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
      { id: "gemini-2.0-flash", label: "Gemini 2.0 Flash" },
    ],
    keyPlaceholder: "AIza...",
    keyPrefix: "AIza",
  },
  {
    id: "openai",
    label: "OpenAI",
    models: [
      { id: "gpt-4o-mini", label: "GPT-4o Mini" },
      { id: "gpt-4o", label: "GPT-4o" },
      { id: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
      { id: "gpt-4.1", label: "GPT-4.1" },
    ],
    keyPlaceholder: "sk-...",
    keyPrefix: "sk-",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    models: [
      { id: "claude-sonnet-4-20250514", label: "Claude Sonnet 4" },
      { id: "claude-3-5-sonnet-20241022", label: "Claude 3.5 Sonnet" },
    ],
    keyPlaceholder: "sk-ant-...",
    keyPrefix: "sk-ant-",
  },
  {
    id: "xai",
    label: "xAI Grok",
    models: [
      { id: "grok-4.7", label: "Grok 4.7" },
      { id: "grok-4.6", label: "Grok 4.6" },
    ],
    keyPlaceholder: "xai-...",
    keyPrefix: "xai-",
  },
]

const DEFAULT_MODEL = "gemini-3.5-flash-lite"

export function resolveModel(config?: ModelConfig) {
  if (!config?.apiKey) {
    return createGoogleGenerativeAI({
      apiKey: process.env.GEMINI_API_KEY!,
    })(DEFAULT_MODEL)
  }

  switch (config.provider) {
    case "openai":
      return createOpenAI({ apiKey: config.apiKey })(
        config.model ?? "gpt-4o-mini"
      )
    case "anthropic":
      return createAnthropic({ apiKey: config.apiKey })(
        config.model ?? "claude-sonnet-4-20250514"
      )
    case "xai":
      return createOpenAI({
        apiKey: config.apiKey,
        baseURL: "https://api.x.ai/v1",
      })(config.model ?? "grok-4.7")
    case "google":
    default:
      return createGoogleGenerativeAI({ apiKey: config.apiKey })(
        config.model ?? DEFAULT_MODEL
      )
  }
}

export function isQuotaError(error: unknown): boolean {
  if (!error) return false
  const msg =
    error instanceof Error ? error.message : String(error)
  const lower = msg.toLowerCase()
  return (
    lower.includes("quota") ||
    lower.includes("rate_limit") ||
    lower.includes("rate limit") ||
    lower.includes("resource_exhausted") ||
    lower.includes("429") ||
    lower.includes("too many requests")
  )
}
