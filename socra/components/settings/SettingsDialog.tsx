"use client"

import { useState, useEffect } from "react"
import { Eye, EyeOff, Trash2, Info } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { PROVIDERS, type Provider } from "@/lib/ai/model-resolver"
import { useUserSettings, type ApiKeys, type ModelPref } from "@/hooks/useUserSettings"
import { toast } from "sonner"


// Gemini and Groq are wired through to the Python backend.
const SUPPORTED_PROVIDERS: ReadonlySet<Provider> = new Set<Provider>(["google", "groq"])
const COMING_SOON_TOOLTIP = "Coming soon — this provider is not wired to the tutor backend yet."

interface SettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: () => void
}

export function SettingsDialog({ open, onOpenChange, onSaved }: SettingsDialogProps) {
  const {
    apiKeys,
    modelPref,
    setApiKey,
    setModelPref,
    clearSettings,
    setQuotaExceeded,
  } = useUserSettings()

  const [draftKeys, setDraftKeys] = useState<ApiKeys>({})
  const [draftModel, setDraftModel] = useState<ModelPref | null>(null)
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (open) {
      setDraftKeys({ ...apiKeys })
      setDraftModel(modelPref ? { ...modelPref } : null)
      setVisibleKeys({})
    }
  }, [open, apiKeys, modelPref])

  const hasAnyKey = Object.values(draftKeys).some((k) => k && k.trim().length > 0)

  const handleSave = () => {
    for (const provider of PROVIDERS) {
      const key = draftKeys[provider.id]?.trim() || ""
      setApiKey(provider.id, key)
    }

    if (draftModel) {
      const keyForSelected = draftKeys[draftModel.provider]?.trim()
      if (keyForSelected) {
        setModelPref(draftModel)
      } else {
        setModelPref(draftModel)
      }
    }

    if (hasAnyKey) {
      setQuotaExceeded(false)
    }

    toast.success("Settings saved", {
      description: hasAnyKey
        ? "Your API key and model preference have been saved."
        : "Settings cleared. Using default server key.",
    })
    onSaved?.()
    onOpenChange(false)
  }

  const handleClear = () => {
    clearSettings()
    setDraftKeys({})
    setDraftModel(null)
    toast.success("Settings cleared", {
      description: "Reverted to default server API key.",
    })
    onSaved?.()
    onOpenChange(false)
  }

  const handleModelSelect = (value: string) => {
    const [provider, ...modelParts] = value.split(":")
    const selectedModel = modelParts.join(":")
    const model = provider === "google" && selectedModel.startsWith("gemini-2.5-")
      ? "gemini-3.5-flash-lite"
      : selectedModel
    setDraftModel({ provider: provider as Provider, model })
  }

  const currentModelValue = draftModel
    ? `${draftModel.provider}:${draftModel.model}`
    : undefined

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl">AI Settings</DialogTitle>
          <DialogDescription>
            Configure your own API keys and choose a model. Leave empty to use
            the default server key.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 pt-2">
          {/* API Keys */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                API Keys
              </h3>
            </div>

            {PROVIDERS.map((provider) => {
              const key = draftKeys[provider.id] || ""
              const visible = visibleKeys[provider.id]
              const supported = SUPPORTED_PROVIDERS.has(provider.id)

              const inputBlock = (
                <div
                  className={`space-y-1.5 ${supported ? "" : "opacity-60"}`}
                  aria-disabled={!supported}
                >
                  <div className="flex items-center gap-2">
                    <Label htmlFor={`key-${provider.id}`} className="text-sm">
                      {provider.label}
                    </Label>
                    {provider.id === "google" && (
                      <Badge
                        variant="secondary"
                        className="text-[10px] px-1.5 py-0"
                      >
                        also used for embeddings
                      </Badge>
                    )}
                    {!supported && (
                      <Badge
                        variant="outline"
                        className="text-[10px] px-1.5 py-0 border-border/60 text-muted-foreground"
                      >
                        coming soon
                      </Badge>
                    )}
                  </div>
                  <div className="relative flex gap-1.5">
                    <Input
                      id={`key-${provider.id}`}
                      type={visible ? "text" : "password"}
                      placeholder={
                        supported
                          ? provider.keyPlaceholder
                          : "Not available in this build"
                      }
                      value={key}
                      disabled={!supported}
                      onChange={(e) =>
                        setDraftKeys((prev) => ({
                          ...prev,
                          [provider.id]: e.target.value,
                        }))
                      }
                      className="pr-10 font-mono text-xs disabled:cursor-not-allowed"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      disabled={!supported}
                      className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        setVisibleKeys((prev) => ({
                          ...prev,
                          [provider.id]: !prev[provider.id],
                        }))
                      }
                    >
                      {visible ? (
                        <EyeOff className="h-3.5 w-3.5" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </div>
                </div>
              )

              return (
                <div key={provider.id}>
                  {supported ? (
                    inputBlock
                  ) : (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="cursor-not-allowed">{inputBlock}</div>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs text-xs">
                        {COMING_SOON_TOOLTIP}
                      </TooltipContent>
                    </Tooltip>
                  )}
                </div>
              )
            })}
          </div>

          <Separator />

          {/* Model Selection */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Chat Model
            </h3>

            {!hasAnyKey && (
              <div className="flex items-start gap-2 rounded-lg bg-muted/50 border border-border/50 p-3">
                <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <p className="text-xs text-muted-foreground">
                  Add a Gemini or Groq API key above to choose a model.
                  Without a key, the server uses its default Gemini 3.5 Flash-Lite key.
                </p>
              </div>
            )}

            <Select
              value={currentModelValue}
              onValueChange={handleModelSelect}
              disabled={!hasAnyKey}
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select a model..." />
              </SelectTrigger>
              <SelectContent>
                {PROVIDERS.map((provider) => {
                  const hasKey = !!draftKeys[provider.id]?.trim()
                  const supported = SUPPORTED_PROVIDERS.has(provider.id)
                  return (
                    <SelectGroup key={provider.id}>
                      <SelectLabel className="flex items-center gap-2">
                        {provider.label}
                        {!supported && (
                          <span className="text-[10px] text-muted-foreground/60 font-normal">
                            (coming soon)
                          </span>
                        )}
                        {supported && !hasKey && (
                          <span className="text-[10px] text-muted-foreground/60 font-normal">
                            (no key)
                          </span>
                        )}
                      </SelectLabel>
                      {provider.models.map((model) => (
                        <SelectItem
                          key={`${provider.id}:${model.id}`}
                          value={`${provider.id}:${model.id}`}
                          disabled={!supported || !hasKey}
                          title={!supported ? COMING_SOON_TOOLTIP : undefined}
                        >
                          {model.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  )
                })}
              </SelectContent>
            </Select>

            {draftModel && (
              <p className="text-xs text-muted-foreground">
                Selected:{" "}
                <span className="font-medium text-foreground">
                  {PROVIDERS.find((p) => p.id === draftModel.provider)?.label}{" "}
                  &mdash;{" "}
                  {PROVIDERS.find((p) => p.id === draftModel.provider)
                    ?.models.find((m) => m.id === draftModel.model)?.label ??
                    draftModel.model}
                </span>
              </p>
            )}
          </div>

          <Separator />

          {/* Actions */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              Reset to defaults
            </Button>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onOpenChange(false)}
              >
                Cancel
              </Button>
              <Button size="sm" onClick={handleSave}>
                Save
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
