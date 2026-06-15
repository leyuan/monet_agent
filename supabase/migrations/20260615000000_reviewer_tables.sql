-- supabase/migrations/20260615000000_reviewer_tables.sql

-- agent_reviews: the reviewer's verdicts (append-only audit trail)
create table agent_reviews (
  id uuid primary key default gen_random_uuid(),
  review_type text not null,
  subject text,
  verdict text not null,
  severity text not null default 'info',
  confidence numeric(3,2),
  evidence_refs jsonb default '{}',
  provenance jsonb default '{}',
  created_at timestamptz default now()
);

-- reviewer_memory: the reviewer's standing priors (namespaced: 'index', '{type}:detail', 'global')
create table reviewer_memory (
  id uuid primary key default gen_random_uuid(),
  namespace text unique not null,
  value jsonb not null,
  updated_at timestamptz default now()
);

create index idx_agent_reviews_type_created on agent_reviews(review_type, created_at desc);
create index idx_agent_reviews_created on agent_reviews(created_at desc);

alter table agent_reviews enable row level security;
alter table reviewer_memory enable row level security;

create policy "Authenticated users can read agent_reviews"
  on agent_reviews for select to authenticated using (true);
create policy "Authenticated users can read reviewer_memory"
  on reviewer_memory for select to authenticated using (true);
