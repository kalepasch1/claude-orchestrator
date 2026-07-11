import { getDeployHistory } from '~/server/utils/canaryDeploy'

export default defineEventHandler(() => {
  return { deploys: getDeployHistory() }
})
