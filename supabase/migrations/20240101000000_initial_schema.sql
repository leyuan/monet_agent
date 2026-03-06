-- Agent Memory: persistent beliefs & state
create table agent_memory (
  id uuid primary key default gen_random_uuid(),
  key text unique not null,
  value jsonb not null,
  updated_at timestamptz default now()
);

-- Agent Journal: timestamped reflections
create table agent_journal (
  id uuid primary key default gen_random_uuid(),
  entry_type text not null,
  title text not null,
  content text not null,
  symbols text[],
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Trades: trade log with rationale
create table trades (
  id uuid primary key default gen_random_uuid(),
  symbol text not null,
  side text not null,
  order_type text not null default 'market',
  quantity numeric(14,4) not null,
  limit_price numeric(14,4),
  filled_quantity numeric(14,4) default 0,
  filled_avg_price numeric(14,4),
  broker_order_id text,
  status text not null default 'pending',
  thesis text,
  confidence numeric(3,2),
  journal_id uuid references agent_journal(id),
  created_at timestamptz default now()
);

-- Watchlist: agent's symbols of interest
create table watchlist (
  id uuid primary key default gen_random_uuid(),
  symbol text unique not null,
  thesis text,
  target_entry numeric(14,4),
  target_exit numeric(14,4),
  added_at timestamptz default now()
);

-- Risk Settings: single row for risk rules
create table risk_settings (
  id uuid primary key default gen_random_uuid(),
  max_position_pct numeric(5,2) default 10.00,
  max_daily_loss numeric(14,2) default 500.00,
  max_total_exposure_pct numeric(5,2) default 80.00,
  default_stop_loss_pct numeric(5,2) default 5.00
);

-- Insert default risk settings
insert into risk_settings (max_position_pct, max_daily_loss, max_total_exposure_pct, default_stop_loss_pct)
values (10.00, 500.00, 80.00, 5.00);

-- Profiles: web UI viewers
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text,
  email text,
  created_at timestamptz default now()
);

-- RLS policies
alter table agent_memory enable row level security;
alter table agent_journal enable row level security;
alter table trades enable row level security;
alter table watchlist enable row level security;
alter table risk_settings enable row level security;
alter table profiles enable row level security;

-- Allow authenticated users to read agent data (monitoring)
create policy "Authenticated users can read agent_memory"
  on agent_memory for select to authenticated using (true);

create policy "Authenticated users can read agent_journal"
  on agent_journal for select to authenticated using (true);

create policy "Authenticated users can read trades"
  on trades for select to authenticated using (true);

create policy "Authenticated users can read watchlist"
  on watchlist for select to authenticated using (true);

create policy "Authenticated users can read risk_settings"
  on risk_settings for select to authenticated using (true);

-- Service role has full access (agent backend uses service role key)
-- Profiles: users can read/update their own
create policy "Users can read own profile"
  on profiles for select to authenticated using (id = auth.uid());

create policy "Users can update own profile"
  on profiles for update to authenticated using (id = auth.uid());

-- Create indexes
create index idx_journal_created_at on agent_journal(created_at desc);
create index idx_journal_entry_type on agent_journal(entry_type);
create index idx_trades_created_at on trades(created_at desc);
create index idx_trades_symbol on trades(symbol);
create index idx_trades_status on trades(status);

-- Function to auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, full_name, email)
  values (new.id, new.raw_user_meta_data->>'full_name', new.email);
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
