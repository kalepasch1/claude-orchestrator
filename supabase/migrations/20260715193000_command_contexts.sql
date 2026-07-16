-- Durable multimodal context for the universal Madeus command surface.
create table if not exists public.command_contexts (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.orchestrator_organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  command_text text not null default '',
  attachments jsonb not null default '[]'::jsonb,
  status text not null default 'ready' check (status in ('uploading','ready','expired','failed')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '30 days')
);

create index if not exists command_contexts_user_created_idx on public.command_contexts(user_id, created_at desc);
alter table public.command_contexts enable row level security;
drop policy if exists "command context owner read" on public.command_contexts;
create policy "command context owner read" on public.command_contexts for select using (auth.uid() = user_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('command-context', 'command-context', false, 8388608, array[
  'image/png','image/jpeg','image/webp','image/gif','application/pdf','text/plain','text/csv',
  'application/json','text/markdown','audio/webm','audio/mpeg','audio/mp4','video/mp4','video/webm'
]) on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit, allowed_mime_types = excluded.allowed_mime_types;

