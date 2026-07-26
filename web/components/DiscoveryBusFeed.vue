<template>
  <div class="discovery-feed">
    <div class="feed-header">DISCOVERY BUS</div>
    <div v-if="!entries.length" class="empty-state">No discoveries yet</div>
    <div class="feed-entries">
      <div v-for="entry in entries" :key="entry.ts" class="entry" :class="entry.kind">
        <div class="entry-header">
          <span class="entry-kind">{{ entry.kind }}</span>
          <span class="entry-slug">{{ entry.slug }}</span>
          <span class="entry-confidence">{{ Math.round((entry.confidence || 0) * 100) }}%</span>
        </div>
        <div class="entry-summary">{{ entry.summary }}</div>
        <div v-if="entry.tags?.length" class="entry-tags">
          <span v-for="tag in entry.tags" :key="tag" class="tag">{{ tag }}</span>
        </div>
      </div>
    </div>
    <div v-if="stats" class="feed-stats">
      <span>{{ stats.total_entries || 0 }} entries</span>
      <span>{{ stats.unique_slugs || 0 }} sources</span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  entries: any[]
  stats?: Record<string, any>
}>()
</script>

<style scoped lang="postcss">
.discovery-feed {
  @apply text-xs;
}

.feed-header {
  @apply font-bold text-cyan-400 mb-2 text-sm tracking-wider;
}

.empty-state {
  @apply text-slate-500 italic py-4 text-center;
}

.feed-entries {
  @apply space-y-2 max-h-64 overflow-y-auto;

  .entry {
    @apply p-2 rounded bg-slate-800 border-l-2 border-slate-600;

    &.shared_file {
      @apply border-cyan-500;
    }

    &.export {
      @apply border-emerald-500;
    }

    &.api_route {
      @apply border-violet-500;
    }

    &.gotcha {
      @apply border-amber-500;
    }

    &.compliance_risk {
      @apply border-red-500;
    }

    &.conflict_predicted {
      @apply border-orange-500;
    }

    .entry-header {
      @apply flex items-center gap-2 mb-1;
    }

    .entry-kind {
      @apply px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 font-mono uppercase;
    }

    .entry-slug {
      @apply text-slate-400 flex-1 truncate;
    }

    .entry-confidence {
      @apply text-emerald-400 font-mono;
    }

    .entry-summary {
      @apply text-slate-300 leading-snug;
    }

    .entry-tags {
      @apply flex flex-wrap gap-1 mt-1;

      .tag {
        @apply px-1 py-0.5 rounded bg-slate-700 text-slate-400;
      }
    }
  }
}

.feed-stats {
  @apply flex gap-4 mt-2 text-slate-500 justify-end;
}
</style>
