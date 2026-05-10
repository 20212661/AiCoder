declare module 'bidi-js' {
  interface BidiEngine {
    getReorderSegments(text: string, direction?: string): Array<{start: number; end: number}>
    getReorderedString(text: string, direction?: string): string
    getEmbeddingLevels(text: string, direction?: string): any
  }
  export default function createBidiEngine(): BidiEngine
}

declare module 'stack-utils' {
  interface StackUtilsOptions {
    ignoredPackages?: string[]
    cwd?: string
    internals?: StackUtils['internals']
  }
  class StackUtils {
    constructor(opts?: StackUtilsOptions)
    clean(stack: string): string
    capture(limit?: number, startAtFunction?: Function): StackFrame[]
    captureString(limit?: number, startAtFunction?: Function): string
    static nodeInternals: RegExp
    parseLine(line: string): any | null
    internals: RegExp
    internalsRegex: RegExp
  }
  interface StackFrame {
    line: number
    column: number
    file: string
    functionName: string
    type: string
    native: boolean
    evalOrigin: string
  }
  export = StackUtils
}

declare module 'react-reconciler' {
  import { ReactNode } from 'react'
  export default function createReconciler<T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12, T13, T14>(
    config: any
  ): any
  export const ConcurrentRoot: number
  export const LegacyRoot: number
}

declare module 'react-reconciler/constants.js' {
  export const ConcurrentRoot: number
  export const LegacyRoot: number
  export const ContinuousEventPriority: number
  export const DefaultEventPriority: number
  export const DiscreteEventPriority: number
  export const NoEventPriority: number
}

declare module 'lodash-es/memoize.js' {
  import { memoize } from 'lodash-es'
  export default memoize
}

declare module 'lodash-es/noop.js' {
  import { noop } from 'lodash-es'
  export default noop
}

declare module 'lodash-es/throttle.js' {
  import { throttle } from 'lodash-es'
  export default throttle
}

declare module 'semver' {
  export function gt(v1: string, v2: string, options?: { loose?: boolean }): boolean
  export function gte(v1: string, v2: string, options?: { loose?: boolean }): boolean
  export function lt(v1: string, v2: string, options?: { loose?: boolean }): boolean
  export function lte(v1: string, v2: string, options?: { loose?: boolean }): boolean
  export function satisfies(version: string, range: string, options?: { loose?: boolean }): boolean
  export function compare(v1: string, v2: string, options?: { loose?: boolean }): -1 | 0 | 1
  export function coerce(version: string | { toString(): string }): { version: string; toString(): string } | null
}
