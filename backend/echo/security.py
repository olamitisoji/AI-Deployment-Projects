import hashlib,hmac,json,secrets
from cryptography.fernet import Fernet
import jwt
from fastapi import HTTPException,Request

class Vault:
    def __init__(self,key):
        self._key=key.encode();self._fernet=Fernet(self._key)
    def seal(self,value): return self._fernet.encrypt(json.dumps(value,ensure_ascii=False).encode()).decode()
    def open(self,value): return json.loads(self._fernet.decrypt(value.encode()))
    def phone_hash(self,phone): return hmac.new(self._key,phone.encode(),hashlib.sha256).hexdigest()

def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()

class ResearcherAuth:
    def __init__(self,settings):
        self.settings=settings
        self.jwks=jwt.PyJWKClient(settings.supabase_url.rstrip('/')+'/auth/v1/.well-known/jwks.json',cache_keys=True) if settings.auth_mode=='supabase' else None
    def __call__(self,request:Request)->str:
        auth=request.headers.get('authorization','')
        if not auth.startswith('Bearer '):raise HTTPException(401,'Researcher sign-in required')
        token=auth[7:]
        if self.settings.auth_mode=='local':
            if not secrets.compare_digest(token,self.settings.researcher_token.get_secret_value()):raise HTTPException(401,'Invalid researcher token')
            return 'local-researcher'
        try:
            key=self.jwks.get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256','ES256'],audience=self.settings.supabase_jwt_audience,issuer=self.settings.supabase_url.rstrip('/')+'/auth/v1',options={'require':['sub','exp','aud','iss']})
            if claims.get('role')!='authenticated':raise ValueError('Invalid role')
            return claims['sub']
        except Exception:
            raise HTTPException(401,'Invalid or expired researcher session') from None
