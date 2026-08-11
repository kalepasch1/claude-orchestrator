import { readFleetHealth } from '../utils/fleetHealth'

export default defineEventHandler(async () => readFleetHealth())
