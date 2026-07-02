export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogLine {
  /** epoch ms or ISO string; rendered as HH:MM:SS */
  ts?: number | string
  level: LogLevel
  message: string
  source?: string
}
