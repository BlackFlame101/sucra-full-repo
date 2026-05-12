"use client"

import { useState, useCallback, useEffect } from "react"
import type { Provider } from "@/lib/ai/model-resolver"

const KEYS_STORAGE_KEY = "socra_api_keys"
const MODEL_STORAGE_KEY = "socra_model_pref"
const QUOTA_FLAG_KEY = "socra_quota_exceeded"

export interface ApiKeys {
  google?: string
  openai?: string
  anthropic?: string
}

export interface ModelPref {
  provider: Provider
  model: string
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
  const [modelPref, setModelPrefState] = useState<ModelPref | null>(null)
  const [quotaExceeded, setQuotaExceededState] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    setApiKeysState(readJson<ApiKeys>(KEYS_STORAGE_KEY, {}))
    setModelPrefState(readJson<ModelPref | null>(MODEL_STORAGE_KEY, null))
    setQuotaExceededState(localStorage.getItem(QUOTA_FLAG_KEY) === "true")
    setLoaded(true)
  }, [])

  const setApiKey = useCallback(
    (provider: Provider, key: string) => {
      setApiKeysState((prev) => {
        const next = { ...prev, [provider]: key || undefined }
        localStorage.setItem(KEYS_STORAGE_KEY, JSON.stringify(next))
        return next
      })
    },
    []
  )

  const setModelPref = useCallback((pref: ModelPref) => {
    setModelPrefState(pref)
    localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(pref))
  }, [])

  const clearSettings = useCallback(() => {
    setApiKeysState({})
    setModelPrefState(null)
    localStorage.removeItem(KEYS_STORAGE_KEY)
    localStorage.removeItem(MODEL_STORAGE_KEY)
    localStorage.removeItem(QUOTA_FLAG_KEY)
    setQuotaExceededState(false)
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
