<template>
  <div class="hivemind-panel">
    <div class="panel-header">HIVEMIND MEMORY</div>
    <div v-if="stats" class="panel-stats">
      <div class="stat">
        <span class="stat-value">{{ stats.total_patterns || 0 }}</span>
        <span class="stat-label">patterns</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ stats.promoted_to_hivemind || 0 }}</span>
        <span class="stat-label">promoted</span>
      </div>
      <div class="stat">
        <span class="stat-value">{{ stats.pending_promotion || 0 }}</span>
        <span class="stat-label">pending</span>
      </div>
    </div>
    <div v-if="!patterns.length" class="empty-state">No patterns stored</div>
    <div class="patterns">
      <div v-for="pattern in patterns" :key="pattern.id" class="pattern" :class="{ promoted: pattern.promoted }">
        <div class="pattern-header">
          <span class="pattern-project">{{ pattern.project_id }}</span>
          <span class="pattern-type">{{ pattern.pattern_type }}</span>
          <span class="pattern-quality">{{ Math.round((pattern.quality_score || 0) * 100) }}%</span>
        </div>
        <div class="pattern-summary">{{ pattern.summary }}</div>
        <div class="pattern-meta">
          <span>reused {{ pattern.reuse_count || 0 }}x</span>
          <span v-if="pattern.promoted" class="promoted-badge">PROMOTED</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  patterns: any[]
  stats?: Record<string, any>
}>()
</script>

<style scoped lang="postcss">
.hivemind-panel {
  @apply text-xs;
}

.panel-header {
  @apply font-bold text-violet-400 mb-2 text-sm tracking-wider;
}

.panel-stats {
  @apply flex gap-4 mb-3;

  .stat {
    @apply flex flex-col items-center p-2 rounded bg-slate-800 flex-1;

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

.patterns {
  @apply space-y-2 max-h-64 overflow-y-auto;

  .pattern {
    @apply p-2 rounded bg-slate-800 border-l-2 border-slate-600;

    &.promoted {
      @apply border-violet-500;
    }

    .pattern-header {
      @apply flex items-center gap-2 mb-1;
    }

    .pattern-project {
      @apply px-1.5 py-0.5 rounded bg-slate-700 text-cyan-400 font-mono;
    }

    .pattern-type {
      @apply text-slate-400 flex-1;
    }

    .pattern-quality {
      @apply text-emerald-400 font-mono;
    }

    .pattern-summary {
      @apply text-slate-300 leading-snug;
    }

    .pattern-meta {
      @apply flex gap-3 mt-1 text-slate-500;

      .promoted-badge {
        @apply px-1.5 py-0.5 rounded bg-violet-900 text-violet-300 font-bold;
      }
    }
  }
}
</style>
