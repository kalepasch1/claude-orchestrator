import { listApps } from '../../utils/appClients'

export default defineEventHandler(() => {
  return { apps: listApps() }
})
