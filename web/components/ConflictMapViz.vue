<template>
  <div class="conflict-map">
    <div class="map-header">FILE LOCKS</div>
    <div v-if="stats" class="map-stats">
      <div class="stat">
        <span class="stat-value">{{ stats.active_locks || 0 }}</span>
        <span class="stat-label">active locks</span>
      </div>
    </div>
    <div v-if="!locks.length" class="empty-state">No active file locks</div>
    <div class="locks">
      <div v-for="lock in locks" :key="lock.id" class="lock" :class="lock.lock_type">
        <div class="lock-header">
          <span class="lock-icon">{{ lock.lock_type === 'exclusive' ? '🔒' : '🔓' }}</span>
          <span class="lock-file">{{ lock.file_path }}</span>
          <span class="lock-type">{{ lock.lock_type }}</span>
        </div>
        <div class="lock-meta">
          <span class="lock-holder">{{ lock.locked_by }}</span>
          <span v-if="lock.task_slug" class="lock-task">{{ lock.task_slug }}</span>
          <span class="lock-project">{{ lock.project_id }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  locks: any[]
  stats?: Record<string, any>
}>()
</script>

<style scoped lang="postcss">
.conflict-map {
  @apply text-xs;
}

.map-header {
  @apply font-bold text-orange-400 mb-2 text-sm tracking-wider;
}

.map-stats {
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

.locks {
  @apply space-y-2 max-h-64 overflow-y-auto;

  .lock {
    @apply p-2 rounded bg-slate-800 border-l-2 border-slate-600;

    &.exclusive {
      @apply border-red-500;
    }

    &.shared {
      @apply border-emerald-500;
    }

    .lock-header {
      @apply flex items-center gap-2 mb-1;
    }

    .lock-icon {
      @apply text-sm;
    }

    .lock-file {
      @apply font-mono text-cyan-400 flex-1 truncate;
    }

    .lock-type {
      @apply px-1.5 py-0.5 rounded bg-slate-700 text-slate-300;
    }

    .lock-meta {
      @apply flex gap-3 text-slate-500;

      .lock-holder {
        @apply text-amber-400 font-mono;
      }

      .lock-task {
        @apply text-slate-400;
      }

      .lock-project {
        @apply text-slate-500 ml-auto;
      }
    }
  }
}
</style>
