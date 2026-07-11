import { suggestPolicies } from '../../../utils/policyEngine'

export default defineEventHandler(async () => {
  const suggestions = await suggestPolicies()
  return { suggestions }
})
