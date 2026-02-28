create table if not exists meetings (
  id text primary key,
  created_at timestamptz not null,
  last_extracted_at timestamptz
);

create table if not exists transcripts (
  id text primary key,
  speaker text not null,
  text text not null,
  is_final boolean not null,
  ts timestamptz not null
);

create table if not exists action_items (
  id text primary key,
  title text not null,
  description text not null,
  owner text not null,
  due_date text,
  confidence double precision not null,
  status text not null,
  source_transcript_ids text[] not null,
  execution_plan jsonb,
  execution_result text,
  error text,
  updated_at timestamptz not null
);
