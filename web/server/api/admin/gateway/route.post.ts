import { route } from '~/server/utils/apiGateway'

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const { app, method, path, body: reqBody, caller } = body || {}

  if (!app || !method || !path) {
    throw createError({
      statusCode: 400,
      message: 'Missing required fields: app, method, path',
    })
  }

  const validMethods = ['GET', 'POST', 'PUT', 'DELETE']
  if (!validMethods.includes(method.toUpperCase())) {
    throw createError({
      statusCode: 400,
      message: `Invalid method: ${method}. Must be one of: ${validMethods.join(', ')}`,
    })
  }

  try {
    const response = await route({
      app,
      method: method.toUpperCase(),
      path,
      body: reqBody,
      caller: caller || 'admin-ui',
    })
    return response
  } catch (e: any) {
    console.error('[Gateway] route error:', e)
    throw createError({
      statusCode: 500,
      message: e.message || 'Failed to route request',
    })
  }
})
