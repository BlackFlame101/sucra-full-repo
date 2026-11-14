import { DEFAULT_GOOGLE_MODEL } from "@/lib/ai/model-policy"

export type Provider = "google" | "openai" | "anthropic" | "groq"

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
      { id: DEFAULT_GOOGLE_MODEL, label: "Gemini 3.5 Flash-Lite (default)" },
      { id: "gemini-3.8-flash", label: "Gemini 3.8 Flash" },
      { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
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
    id: "groq",
    label: "Groq",
    models: [
      { id: "openai/gpt-oss-120b", label: "GPT OSS 120B" },
      { id: "openai/gpt-oss-20b", label: "GPT OSS 20B" },
      { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B (Enterprise access)" },
      { id: "llama-3.1-8b-instant", label: "Llama 3.1 8B Instant (Enterprise access)" },
      { id: "qwen/qwen3.8-27b", label: "Qwen 3.8 27B (Preview)" },
      { id: "meta-models/muse-spark-open", label: "Muse Spark Open (Preview)" },
      { id: "minimaxai/minimax-m2.7", label: "MiniMax M2.7 (Preview, Enterprise access)" },
    ],
    keyPlaceholder: "gsk_...",
    keyPrefix: "gsk_",
  },
]
