import { beginOAuth } from '../../../utils/connectorFabric'
export default defineEventHandler(async (event) => { const body = await readBody<any>(event); if (!body?.provider) throw createError({ statusCode: 400, message: 'provider_required' }); return beginOAuth(event, body.provider, Array.isArray(body.scopes) ? body.scopes : [], body.resource) })
