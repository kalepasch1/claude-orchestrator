-- artifact_commit is a bare sha — without knowing which repo it belongs to,
-- the claim is unverifiable: the same 7-char prefix can appear in any of the
-- fleet's repos. This migration adds artifact_repo so every closure that
-- asserts delivered work is anchored to a specific repository.
--
-- It also tightens the MERGED transition: an executor must not mark a task
-- MERGED directly. Only the merge train (which resolves the sha in the target
-- branch) may do so, and it records the verification in note.

-- 1. Add artifact_repo column
ALTER TABLE public.tasks
  ADD COLUMN IF NOT EXISTS artifact_repo text;

COMMENT ON COLUMN public.tasks.artifact_repo IS
  'The project name (projects.name) whose repo contains artifact_commit. '
  'Required when artifact_commit is set on a closure state.';

-- 2. Replace the trigger function
CREATE OR REPLACE FUNCTION public.enforce_evidence_on_closure()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
declare
  v_other_slug text;
begin
  -- Only closures that assert delivered work are gated. BLOCKED, QUARANTINED,
  -- PHANTOM_UNVERIFIED, SUPERSEDED, CLOSED, DECOMPOSED etc. are all honest
  -- non-delivery states and stay freely writable.
  if new.state not in ('DONE','MERGED','DEPLOYED_AND_VERIFIED') then
    return new;
  end if;

  -- Unchanged state on an already-closed row: let it through so notes and
  -- bookkeeping updates on historical rows are not blocked.
  if tg_op = 'UPDATE' and old.state = new.state
     and old.artifact_commit is not distinct from new.artifact_commit then
    return new;
  end if;

  if new.artifact_commit is null or btrim(new.artifact_commit) = '' then
    if coalesce(new.note,'') like '%NO-ARTIFACT-JUSTIFIED:%' then
      return new;
    end if;
    raise exception using
      errcode = 'check_violation',
      message = format('task %s cannot close as %s with no artifact_commit', new.slug, new.state),
      detail  = 'A closure asserting delivered work must record the sha that proves it. '
             || 'Without one the claim cannot be reproduced, reverted or audited.',
      hint    = 'Record the commit sha in artifact_commit, or if this task genuinely '
             || 'produced no code, put "NO-ARTIFACT-JUSTIFIED: <reason>" in note.';
  end if;

  -- artifact_repo is required alongside artifact_commit so the sha is
  -- anchored to a verifiable repository. Phase 1: soft warning (NOTICE)
  -- so existing executors are not broken. Phase 2 will harden to exception
  -- once all callers pass artifact_repo.
  if new.artifact_repo is null or btrim(new.artifact_repo) = '' then
    if coalesce(new.note,'') not like '%NO-ARTIFACT-JUSTIFIED:%' then
      raise notice 'task % has artifact_commit but no artifact_repo — '
                   'bare sha is unverifiable (will become an error in phase 2)',
                   new.slug;
    end if;
  end if;

  -- MERGED requires verification evidence. An executor may close as DONE;
  -- only the merge train (merge_truth / approval_merge / batch_fusion) or
  -- an operator may transition to MERGED. The merge train writes notes
  -- containing 'merge-truth:' or 'merge-handler:' or the JUSTIFIED marker;
  -- rogue SQL writes that bypass the train carry none of these.
  if new.state = 'MERGED' then
    if coalesce(new.note,'') not like '%merge-truth:%'
       and coalesce(new.note,'') not like '%merge-handler:%'
       and coalesce(new.note,'') not like '%VERIFIED-MERGE:%'
       and coalesce(new.note,'') not like '%NO-ARTIFACT-JUSTIFIED:%'
       and coalesce(new.note,'') not like '%batch-fusion%' then
      raise exception using
        errcode = 'check_violation',
        message = format('task %s cannot be set to MERGED without verification', new.slug),
        detail  = 'Only a verifier (merge train) that has resolved the sha in the target '
               || 'repo and confirmed the commit is reachable may set MERGED.',
        hint    = 'Route through merge_truth.guarded_task_update(), or include '
               || '"VERIFIED-MERGE: <details>" in note.';
    end if;
  end if;

  -- One commit certifying many tasks is the documented slice-1-certifies-slice-2..N
  -- phantom. Allowed only when explicitly justified, same escape hatch.
  select t.slug into v_other_slug
    from public.tasks t
   where t.artifact_commit = new.artifact_commit
     and t.id <> new.id
     and t.state in ('DONE','MERGED','DEPLOYED_AND_VERIFIED')
   limit 1;

  if v_other_slug is not null and coalesce(new.note,'') not like '%NO-ARTIFACT-JUSTIFIED:%' then
    raise exception using
      errcode = 'check_violation',
      message = format('artifact_commit %s is already cited by task %s', new.artifact_commit, v_other_slug),
      detail  = 'One commit certifying several tasks is how slice-1 landing silently '
             || 'certified slice-2..N in the phantom-merge audit.',
      hint    = 'Point this task at its own commit, or add "NO-ARTIFACT-JUSTIFIED: '
             || 'shared commit because <reason>" to note.';
  end if;

  return new;
end;
$function$;
