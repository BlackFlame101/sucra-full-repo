"use client"

import { useState, useCallback, useEffect, useRef } from "react"
import type { Provider } from "@/lib/ai/model-resolver"

const KEYS_STORAGE_KEY = "socra_api_keys"
const MODEL_STORAGE_KEY = "socra_model_pref"
const QUOTA_FLAG_KEY = "socra_quota_exceeded"
const SETTINGS_CHANGED_EVENT = "socra-settings-changed"

export interface ApiKeys {
  google?: string
  openai?: string
  anthropic?: string
  groq?: string
}

export interface ModelPref {
  provider: Provider
  model: string
}

export function notifySettingsChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SETTINGS_CHANGED_EVENT))
  }
}

interface ActiveConfig {
  apiKey?: string
  provider?: Provider
  model?: string
}

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

export function useUserSettings() {
  const [apiKeys, setApiKeysState] = useState<ApiKeys>({})
  const apiKeysRef = useRef<ApiKeys>({})
  const [modelPref, setModelPrefState] = useState<ModelPref | null>(null)
  const [quotaExceeded, setQuotaExceededState] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    const syncFromStorage = () => {
      const storedKeys = readJson<ApiKeys & { xai?: string }>(KEYS_STORAGE_KEY, {})
      // Preserve users' locally stored key during the provider rename.
      const migratedKeys: ApiKeys = { ...storedKeys, groq: storedKeys.groq ?? storedKeys.xai }
      delete (migratedKeys as ApiKeys & { xai?: string }).xai
      apiKeysRef.current = migratedKeys
      setApiKeysState(migratedKeys)
      if (storedKeys.xai && !storedKeys.groq) {
        localStorage.setItem(KEYS_STORAGE_KEY, JSON.stringify(migratedKeys))
      }
      const savedModel = readJson<ModelPref | null>(MODEL_STORAGE_KEY, null)
      // Move saved Gemini 2.5 preferences to the requested 3.5 model. The key is
      // kept exactly as stored; users can replace it in Settings if it is stale.
      const model = savedModel?.provider === "google" && savedModel.model.startsWith("gemini-2.5-")
        ? { provider: "google" as const, model: "gemini-3.5-flash-lite" }
        : savedModel
      if (model && model !== savedModel) localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(model))
      const migratedModel = model?.provider === ("xai" as Provider)
        ? { provider: "groq" as Provider, model: "openai/gpt-oss-120b" }
        : model
      if (migratedModel !== savedModel) localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(migratedModel))
      setModelPrefState(migratedModel)
      setQuotaExceededState(localStorage.getItem(QUOTA_FLAG_KEY) === "true")
      setLoaded(true)
    }
    syncFromStorage()
    window.addEventListener("storage", syncFromStorage)
    window.addEventListener(SETTINGS_CHANGED_EVENT, syncFromStorage)
    return () => {
      window.removeEventListener("storage", syncFromStorage)
      window.removeEventListener(SETTINGS_CHANGED_EVENT, syncFromStorage)
    }
  }, [])

  const setApiKey = useCallback(
    (provider: Provider, key: string) => {
      const next = { ...apiKeysRef.current, [provider]: key || undefined }
      apiKeysRef.current = next
      localStorage.setItem(KEYS_STORAGE_KEY, JSON.stringify(next))
      setApiKeysState(next)
      notifySettingsChanged()
    },
    []
  )

  const setModelPref = useCallback((pref: ModelPref) => {
    setModelPrefState(pref)
    localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(pref))
    notifySettingsChanged()
  }, [])

  const clearSettings = useCallback(() => {
    setApiKeysState({})
    setModelPrefState(null)
    localStorage.removeItem(KEYS_STORAGE_KEY)
    localStorage.removeItem(MODEL_STORAGE_KEY)
    localStorage.removeItem(QUOTA_FLAG_KEY)
    setQuotaExceededState(false)
    notifySettingsChanged()
  }, [])

  const setQuotaExceeded = useCallback((value: boolean) => {
    setQuotaExceededState(value)
    if (value) {
      localStorage.setItem(QUOTA_FLAG_KEY, "true")
    } else {
      localStorage.removeItem(QUOTA_FLAG_KEY)
    }
  }, [])

  const isUsingOwnKey = !!(
    modelPref && apiKeys[modelPref.provider]
  )

  const getGoogleApiKey = useCallback(
    () => apiKeys.google,
    [apiKeys]
  )

  const getActiveConfig = useCallback((): ActiveConfig => {
    if (!modelPref) return {}
    const key = apiKeys[modelPref.provider]
    if (!key) return {}
    return {
      apiKey: key,
      provider: modelPref.provider,
      model: modelPref.model,
    }
  }, [apiKeys, modelPref])

  return {
    apiKeys,
    modelPref,
    loaded,
    isUsingOwnKey,
    quotaExceeded,
    setApiKey,
    setModelPref,
    clearSettings,
    setQuotaExceeded,
    getGoogleApiKey,
    getActiveConfig,
  }
}
