export function logError(_error: unknown, _context?: string): void {
  // Stub: log to stderr if needed
  if (process.env.CLAUDE_CODE_DEBUG) {
    process.stderr.write(String(_error) + '\n')
  }
}
