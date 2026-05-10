// Ink custom host elements for JSX type checking.
// React 19 uses React.JSX namespace, not global JSX.
import type { ReactNode } from 'react'

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'ink-box': {
        ref?: any
        tabIndex?: number
        autoFocus?: boolean
        onClick?: (event: any) => void
        onFocus?: (event: any) => void
        onFocusCapture?: (event: any) => void
        onBlur?: (event: any) => void
        onBlurCapture?: (event: any) => void
        onMouseEnter?: () => void
        onMouseLeave?: () => void
        onKeyDown?: (event: any) => void
        onKeyDownCapture?: (event: any) => void
        style?: Record<string, any>
        children?: ReactNode
      }
      'ink-text': {
        style?: Record<string, any>
        textStyles?: Record<string, any>
        children?: ReactNode
      }
      'ink-link': {
        href: string
        children?: ReactNode
      }
      'ink-raw-ansi': {
        rawText: string
        rawWidth: number
        rawHeight: number
      }
    }
  }
}
