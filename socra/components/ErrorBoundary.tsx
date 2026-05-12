"use client"

import { Component, type ReactNode } from "react"
import { AlertTriangle, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div className="flex flex-col items-center justify-center min-h-[300px] p-8 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive/10 mb-5">
            <AlertTriangle className="h-6 w-6 text-destructive" />
          </div>
          <h2 className="font-serif text-xl font-medium mb-2">
            Something went wrong
          </h2>
          <p className="text-sm text-muted-foreground max-w-md mb-6 leading-relaxed">
            An unexpected error occurred. Try refreshing the page or going back to
            the dashboard.
          </p>
          <div className="flex gap-3">
            <Button
              variant="outline"
              className="gap-2"
              onClick={() => this.setState({ hasError: false, error: undefined })}
            >
              <RotateCcw className="h-4 w-4" />
              Try Again
            </Button>
            <Button onClick={() => (window.location.href = "/dashboard")}>
              Go to Dashboard
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
