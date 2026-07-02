// GET /api/fleet/forecast?minRisk=0.5 — predictive admin: forecast recurring admin
// events before they fire, ranked by risk, so remediations can be pre-staged as co-pilot.
import { forecastFromEvents, type AdminEvent } from '@darwin/kernel/fleetAdmin';
import { serviceClient } from '../../utils/fleetSupabase';

export default defineEventHandler(async (event) => {
  const minRisk = Number(getQuery(event).minRisk ?? 0.5);
  const sb = serviceClient();
  const { data } = await sb
    .from('fleet_admin_events')
    .select('id,product,domain,category,severity,title,summary,at')
    .order('at', { ascending: true })
    .limit(5000);
  const events = (data ?? []) as AdminEvent[];
  const forecasts = forecastFromEvents(events, new Date().toISOString(), minRisk);
  return { forecasts, total: forecasts.length };
});
