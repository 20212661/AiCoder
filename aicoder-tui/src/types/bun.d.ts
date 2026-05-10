/**
 * Minimal type declarations for Bun globals used as optional performance
 * optimizations. These APIs are always guarded by `typeof Bun !== 'undefined'`
 * at runtime, so Node.js environments fall back to pure-JS implementations.
 */
declare const Bun: {
  hash(data: string, seed?: number): bigint
  stringWidth(str: string, opts?: { ambiguousIsNarrow?: boolean }): number
  wrapAnsi(input: string, columns: number, options?: { hard?: boolean; wordWrap?: boolean; trim?: boolean }): string
  semver: {
    order(a: string, b: string): -1 | 0 | 1
    satisfies(version: string, range: string): boolean
  }
}
