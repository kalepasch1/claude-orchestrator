import { listPromptOps } from '~/server/utils/promptOps'

export default defineEventHandler(() => {
  return { ops: listPromptOps() }
})
