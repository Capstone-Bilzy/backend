from supabase import create_client, Client
from core.config import settings

# 일반 클라이언트 (anon key) - RLS 적용됨
supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

# 서비스 클라이언트 (service role key) - RLS 우회, 관리 작업용
supabase_admin: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
