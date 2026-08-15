PROJECT: kalepasch-com

- id: chatgpt-local-reconcile-kalepasch-com-bc0e208ad8e3
  title: Reconcile local ChatGPT/Codex build evidence for kalepasch-com
  material: yes
  depends: []
  proof: every evidence item is classified and all still-useful absent code is durably queued or integrated
  prompt: |
    Reconcile the local ChatGPT/Codex build evidence below without destroying or overwriting it.

    This is a recovery-and-consideration task, not permission to prefer legacy code over current code.
    Treat every source path, stash, rescue ref, and worktree as read-only. Compare each item against
    the current default branch, remote branches, merged history, and live orchestrator tasks. Classify
    each item as ALREADY_PRESENT, SUPERSEDED_BY_NEWER, ACTIVE_IN_ANOTHER_TASK, RECOVERABLE_VALUE, or
    CONFLICTED_NEEDS_FOCUSED_TASK. The newest/most complete implementation wins.

    For RECOVERABLE_VALUE, work only in a newly allocated isolated worktree, apply the minimum coherent
    diff, run relevant tests, and deliver through the normal agent branch + merge train. For conflicts,
    queue a focused follow-up rather than forcing an overwrite. Do not delete, reset, clean, pop, or move
    the evidence source. Do not duplicate work already represented by a live task or remote branch.

    Write one `coordination_tasks` recovery-ledger record per evidence item using audit fingerprint
    `bc0e208ad8e39ec3ee6066d44c7e822dc0f1bf223f982bac70326c772e44b093`, including source, classification, disposition, and resulting task/branch/commit. Completion
    requires zero UNKNOWN items and durable queue/branch provenance for every item with remaining value.

    Evidence snapshot (large ref/file collections are represented by a complete digest plus a
    sample; enumerate the live source during reconciliation so every item is classified):
    [
      {
        "branch": "agent/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter",
        "change_count": 63,
        "changes_digest": "be79e2c9762d927a384d017a7ea31433f7504b15d0a70c2cad1c30fecc132f18",
        "changes_sample": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-2fc37310e761.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-405bb4ce0350.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-7378316f5497.txt",
          ".recovery-intent-relfix-kalepasch-com-4fa4039b57dc.txt",
          ".recovery-intent-relfix-kalepasch-com-6878adfdd49e-deduplicate-pricing-grid-reconstruction.txt",
          ".recovery-intent-relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-run-build-tests-analyz.txt",
          "app/app.vue",
          "app/assets/css/main.css",
          "app/components/AppFooter.vue",
          "app/components/AppNavbar.vue",
          "app/components/BriefingSignup.vue",
          "app/components/ConsultationForm.vue",
          "app/components/ContactInfo.vue",
          "app/components/FeaturedCarousel.vue",
          "app/components/IntroCover.vue",
          "app/components/IntroCoverKale.vue",
          "app/components/IntroCoverMandy.vue",
          "app/components/ProjectCard.vue",
          "app/components/ProjectFilter.vue",
          "app/components/ProjectGallery.vue",
          "app/components/ProjectImageCarousel.vue",
          "app/components/TriageMark.vue",
          "app/components/VenturePreview.vue",
          "app/components/admin/AdminSidebar.vue",
          "app/components/admin/CategoryManager.vue",
          "app/components/admin/ConsultationList.vue",
          "app/components/admin/ImageUploader.vue"
        ],
        "changes_total": 63,
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786740270,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/dropbox-mission-complete-merge-and-deploy-the-full-backlog-to-vercel-p5-pause-arbiter"
      },
      {
        "branch": "agent/orch-cross-project-depends",
        "change_count": 63,
        "changes_digest": "be79e2c9762d927a384d017a7ea31433f7504b15d0a70c2cad1c30fecc132f18",
        "changes_sample": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-2fc37310e761.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-405bb4ce0350.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-7378316f5497.txt",
          ".recovery-intent-relfix-kalepasch-com-4fa4039b57dc.txt",
          ".recovery-intent-relfix-kalepasch-com-6878adfdd49e-deduplicate-pricing-grid-reconstruction.txt",
          ".recovery-intent-relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-run-build-tests-analyz.txt",
          "app/app.vue",
          "app/assets/css/main.css",
          "app/components/AppFooter.vue",
          "app/components/AppNavbar.vue",
          "app/components/BriefingSignup.vue",
          "app/components/ConsultationForm.vue",
          "app/components/ContactInfo.vue",
          "app/components/FeaturedCarousel.vue",
          "app/components/IntroCover.vue",
          "app/components/IntroCoverKale.vue",
          "app/components/IntroCoverMandy.vue",
          "app/components/ProjectCard.vue",
          "app/components/ProjectFilter.vue",
          "app/components/ProjectGallery.vue",
          "app/components/ProjectImageCarousel.vue",
          "app/components/TriageMark.vue",
          "app/components/VenturePreview.vue",
          "app/components/admin/AdminSidebar.vue",
          "app/components/admin/CategoryManager.vue",
          "app/components/admin/ConsultationList.vue",
          "app/components/admin/ImageUploader.vue"
        ],
        "changes_total": 63,
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786740169,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/orch-cross-project-depends"
      },
      {
        "branch": "agent/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch",
        "change_count": 63,
        "changes_digest": "be79e2c9762d927a384d017a7ea31433f7504b15d0a70c2cad1c30fecc132f18",
        "changes_sample": [
          ".aider.chat.history.md",
          ".deploy-canary",
          ".recovery-intent-curation-snapshot-diff-alerts.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-2fc37310e761.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-405bb4ce0350.txt",
          ".recovery-intent-recover-missing-branch-relfix-kalepasch-com-7378316f5497.txt",
          ".recovery-intent-relfix-kalepasch-com-4fa4039b57dc.txt",
          ".recovery-intent-relfix-kalepasch-com-6878adfdd49e-deduplicate-pricing-grid-reconstruction.txt",
          ".recovery-intent-relfix-kalepasch-com-ca392a3ba8b4-add-nuxt-dev-dependency-run-build-tests-analyz.txt",
          "app/app.vue",
          "app/assets/css/main.css",
          "app/components/AppFooter.vue",
          "app/components/AppNavbar.vue",
          "app/components/BriefingSignup.vue",
          "app/components/ConsultationForm.vue",
          "app/components/ContactInfo.vue",
          "app/components/FeaturedCarousel.vue",
          "app/components/IntroCover.vue",
          "app/components/IntroCoverKale.vue",
          "app/components/IntroCoverMandy.vue",
          "app/components/ProjectCard.vue",
          "app/components/ProjectFilter.vue",
          "app/components/ProjectGallery.vue",
          "app/components/ProjectImageCarousel.vue",
          "app/components/TriageMark.vue",
          "app/components/VenturePreview.vue",
          "app/components/admin/AdminSidebar.vue",
          "app/components/admin/CategoryManager.vue",
          "app/components/admin/ConsultationList.vue",
          "app/components/admin/ImageUploader.vue"
        ],
        "changes_total": 63,
        "head": "97cf9d17ad3c727823c22ea4438c16554b7f425e",
        "kind": "dirty_worktree",
        "newest_change_mtime": 1786740211,
        "path": "/Users/kpasch/Documents/smarter/pasch-wt/relfix-racefeed-07060650-fix-typescript-and-build--slice-4-fix-missing-branch"
      }
    ]
