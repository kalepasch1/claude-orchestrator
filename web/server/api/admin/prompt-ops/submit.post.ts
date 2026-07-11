import { processPromptFile, approveAndExecute } from '~/server/utils/promptOps'

export default defineEventHandler(async (event) => {
  const body = await readBody<{ content: string; autoExecute?: boolean }>(event)

  if (!body?.content?.trim()) {
    throw createError({ statusCode: 400, message: 'content is required' })
  }

  const filename = `PROMPT-${Date.now()}.md`
  const op = await processPromptFile(filename, body.content.trim())

  // If auto-execute is requested and we parsed successfully, run it
  if (body.autoExecute && op.status === 'parsed' && op.actions && op.actions.length > 0) {
    await approveAndExecute(op.id)
  }

  return { op }
})
