-- Run in Supabase SQL Editor once.
create table if not exists public.profiles (
 id uuid primary key references auth.users(id) on delete cascade,
 email text not null, full_name text not null default '',
 role text not null default 'student' check (role in ('student','faculty','admin')),
 created_at timestamptz not null default now()
);
create table if not exists public.documents (
 id uuid primary key, title text not null, subject text not null,
 semester text not null, department text not null,
 owner_id uuid not null references public.profiles(id),
 latest_version integer not null default 1,
 created_at timestamptz not null default now()
);
create table if not exists public.file_versions (
 id uuid primary key default gen_random_uuid(),
 document_id uuid not null references public.documents(id) on delete cascade,
 version integer not null, storage_path text not null unique,
 original_name text not null, uploaded_by uuid not null references public.profiles(id),
 created_at timestamptz not null default now(),
 unique(document_id,version)
);
create or replace function public.my_role() returns text language sql stable security definer
set search_path = '' as $$ select role from public.profiles where id = (select auth.uid()) $$;
create or replace function public.handle_new_user() returns trigger language plpgsql security definer
set search_path = '' as $$
begin
 insert into public.profiles(id,email,full_name,role)
 values(new.id, coalesce(new.email,''), coalesce(new.raw_user_meta_data->>'full_name',''), 'student');
 return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute procedure public.handle_new_user();
alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.file_versions enable row level security;
create policy "read own or admin profiles" on public.profiles for select to authenticated using (id = (select auth.uid()) or public.my_role() = 'admin');
create policy "admin updates roles" on public.profiles for update to authenticated using (public.my_role() = 'admin') with check (public.my_role() = 'admin');
create policy "read documents" on public.documents for select to authenticated using (true);
create policy "faculty insert documents" on public.documents for insert to authenticated with check (owner_id = (select auth.uid()) and public.my_role() in ('faculty','admin'));
create policy "owner updates documents" on public.documents for update to authenticated using ((owner_id = (select auth.uid()) and public.my_role() = 'faculty') or public.my_role() = 'admin') with check ((owner_id = (select auth.uid()) and public.my_role() = 'faculty') or public.my_role() = 'admin');
create policy "owner deletes documents" on public.documents for delete to authenticated using ((owner_id = (select auth.uid()) and public.my_role() = 'faculty') or public.my_role() = 'admin');
create policy "read versions" on public.file_versions for select to authenticated using (true);
create policy "owner inserts versions" on public.file_versions for insert to authenticated with check (uploaded_by = (select auth.uid()) and public.my_role() in ('faculty','admin') and exists (select 1 from public.documents d where d.id = document_id and (d.owner_id = (select auth.uid()) or public.my_role() = 'admin')));
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('department-files','department-files',false,10485760,array['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.presentationml.presentation','text/plain','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'])
on conflict (id) do nothing;
create policy "authenticated download" on storage.objects for select to authenticated using (bucket_id='department-files');
create policy "faculty upload" on storage.objects for insert to authenticated with check (bucket_id='department-files' and public.my_role() in ('faculty','admin') and (storage.foldername(name))[1] is not null);
create policy "faculty cleanup" on storage.objects for delete to authenticated using (bucket_id='department-files' and public.my_role() in ('faculty','admin'));
-- After creating your own account, promote it ONCE in SQL Editor:
-- update public.profiles set role='admin' where email='your-email@example.com';
