<template>
  <div class="compliance-panel">
    <div class="panel-header">
      COMPLIANCE MONITOR
      <span v-if="unacknowledgedCount > 0" class="alert-badge">{{ unacknowledgedCount }}</span>
    </div>
    <div v-if="stats" class="panel-stats">
      <div class="stat">
        <span class="stat-value">{{ stats.total_events || 0 }}</span>
        <span class="stat-label">total events</span>
      </div>
      <div class="stat" :class="{ alert: (stats.unacknowledged_high_critical || 0) > 0 }">
        <span class="stat-value">{{ stats.unacknowledged_high_critical || 0 }}</span>
        <span class="stat-label">unacked risks</span>
      </div>
    </div>
    <div v-if="!risks.length" class="empty-state">No unacknowledged risks</div>
    <div class="risks">
      <div v-for="risk in risks" :key="risk.id" class="risk" :class="risk.severity">
        <div class="risk-header">
          <span class="severity-badge">{{ risk.severity?.toUpperCase() }}</span>
          <span class="risk-category">{{ risk.risk_category }}</span>
          <span v-if="risk.file_path" class="risk-file">{{ risk.file_path }}</span>
        </div>
        <div class="risk-summary">{{ risk.summary }}</div>
        <div class="risk-meta">
          <span v-if="risk.task_slug">task: {{ risk.task_slug }}</span>
          <span v-if="risk.escalated" class="escalated-badge">ESCALATED</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  risks: any[]
  stats?: Record<string, any>
}>()

const unacknowledgedCount = computed(() => props.stats?.unacknowledged_high_critical || 0)
</script>

<style scoped lang="postcss">
.compliance-panel {
  @apply text-xs;
}

.panel-header {
  @apply font-bold text-amber-400 mb-2 text-sm tracking-wider flex items-center gap-2;

  .alert-badge {
    @apply px-1.5 py-0.5 rounded-full bg-red-600 text-white text-xs font-bold;
  }
}

.panel-stats {
  @apply flex gap-4 mb-3;

  .stat {
    @apply flex flex-col items-center p-2 rounded bg-slate-800 flex-1;

    &.alert {
      @apply bg-red-900/30 border border-red-800;
    }

    .stat-value {
      @apply text-lg font-bold text-slate-200;
    }

    .stat-label {
      @apply text-slate-500;
    }
  }
}

.empty-state {
  @apply text-slate-500 italic py-4 text-center;
}

.risks {
  @apply space-y-2 max-h-64 overflow-y-auto;

  .risk {
    @apply p-2 rounded bg-slate-800 border-l-2;

    &.critical {
      @apply border-red-500 bg-red-900/20;
    }

    &.high {
      @apply border-orange-500;
    }

    &.medium {
      @apply border-amber-500;
    }

    &.low {
      @apply border-slate-500;
    }

    &.info {
      @apply border-slate-600;
    }

    .risk-header {
      @apply flex items-center gap-2 mb-1;
    }

    .severity-badge {
      @apply px-1.5 py-0.5 rounded font-bold text-xs;
    }

    .risk.critical .severity-badge {
      @apply bg-red-800 text-red-200;
    }

    .risk.high .severity-badge {
      @apply bg-orange-800 text-orange-200;
    }

    .risk-category {
      @apply text-slate-400 font-mono;
    }

    .risk-file {
      @apply text-cyan-400 font-mono flex-1 text-right truncate;
    }

    .risk-summary {
      @apply text-slate-300 leading-snug;
    }

    .risk-meta {
      @apply flex gap-3 mt-1 text-slate-500;

      .escalated-badge {
        @apply px-1.5 py-0.5 rounded bg-red-900 text-red-300 font-bold;
      }
    }
  }
}
</style>
