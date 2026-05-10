import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

type ExecOptions = {
  input?: string
  useCwd?: boolean
  timeout?: number
}

type ExecResult = {
  code: number
  stdout: string
  stderr: string
}

export async function execFileNoThrow(
  file: string,
  args: string[],
  options?: ExecOptions,
): Promise<ExecResult> {
  try {
    const spawnOptions: import('child_process').ExecFileOptions = {}
    if (options?.timeout) spawnOptions.timeout = options.timeout
    if (options?.useCwd !== false) spawnOptions.cwd = process.cwd()

    const { stdout, stderr } = await execFileAsync(file, args, spawnOptions)
    return { code: 0, stdout: String(stdout ?? ''), stderr: String(stderr ?? '') }
  } catch (e: any) {
    return { code: e?.code ?? 1, stdout: e?.stdout ?? '', stderr: e?.stderr ?? '' }
  }
}
