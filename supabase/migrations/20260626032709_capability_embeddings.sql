
alter table capabilities add column if not exists embedding vector(1536);

create index if not exists capabilities_embedding_idx
  on capabilities using ivfflat (embedding vector_cosine_ops) with (lists = 10);

create or replace function match_capabilities(
  query_embedding vector(1536),
  match_threshold float default 0.95,
  match_count int default 3
)
returns table (id uuid, slug text, name text, similarity float)
language sql stable
as $$
  select id, slug, name,
         1 - (embedding <=> query_embedding) as similarity
  from capabilities
  where embedding is not null
    and 1 - (embedding <=> query_embedding) >= match_threshold
  order by embedding <=> query_embedding
  limit match_count;
$$;
;
