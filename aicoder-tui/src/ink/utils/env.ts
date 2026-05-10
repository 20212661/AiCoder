import memoize from 'lodash-es/memoize.js'

function detectTerminal(): string | undefined {
  const termProgram = process.env.TERM_PROGRAM
  if (termProgram) return termProgram
  if (process.env.WT_SESSION) return 'windows-terminal'
  if (process.env.KITTY_WINDOW_ID) return 'kitty'
  if (process.env.TERM) return process.env.TERM
  return undefined
}

export const env = {
  platform: process.platform as string,
  terminal: detectTerminal(),
  isRunningWithBun: memoize(() => false),
}
