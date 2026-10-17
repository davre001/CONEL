"""GitHub App OAuth, encrypted server-side credentials and opaque sessions."""
import base64, hashlib, hmac, json, os, secrets, time
from urllib.parse import urlencode, urlparse
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class GitHubAuth:
    def __init__(self, store):
        self.store=store
        self.app_id=os.getenv('GITHUB_APP_ID','')
        self.client_id=os.getenv('GITHUB_APP_CLIENT_ID','')
        self.secret=os.getenv('GITHUB_APP_CLIENT_SECRET','')
        self.callback=os.getenv('GITHUB_APP_CALLBACK_URL','http://localhost:8000/api/auth/github/callback')
        self.origin=os.getenv('CONEL_FRONTEND_ORIGIN','http://localhost:3000').rstrip('/')
        self.secure=urlparse(self.callback).scheme=='https'
        self.key=os.getenv('CONEL_SESSION_ENCRYPTION_KEY','')
        self.configured=bool(self.app_id and self.client_id and self.secret and self.key)
        self.cookie='__Host-conel_session' if self.secure else 'conel_session'
        self.state_cookie='__Host-conel_oauth' if self.secure else 'conel_oauth'
        if self.configured:
            try: self.cipher=Fernet(self.key.encode())
            except ValueError: raise ValueError('Invalid CONEL_SESSION_ENCRYPTION_KEY') from None
            for url in (self.callback,self.origin):
                parsed=urlparse(url)
                if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in {'localhost','127.0.0.1'}):
                    raise ValueError('GitHub login requires HTTPS outside localhost')
                if parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise ValueError('Invalid authentication URL')

    def initialize(self):
        with self.store.transaction() as db:
            for table in ('oauth_states', 'github_connections', 'browser_sessions'):
                db.execute('SELECT 1 FROM '+table+' LIMIT 0')

    def require_configured(self):
        if not self.configured: raise HTTPException(503,'Configure GitHub App login settings first')

    def api(self, token, path):
        try:
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                r=client.get('https://api.github.com'+path,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10'})
                if r.status_code in {401,403,404}: raise HTTPException(403,'GitHub access revoked or repository not authorized')
                if r.status_code!=200: raise HTTPException(502,'GitHub access check failed')
                return r.json()
        except httpx.HTTPError: raise HTTPException(502,'GitHub connection failed') from None

    def token(self,user):
        self.require_configured()
        with self.store.transaction() as db:
            row=db.execute('SELECT * FROM github_connections WHERE user_id=? AND revoked=0 AND expires>?',(user,time.time())).fetchone()
        if not row: raise HTTPException(401,'Reconnect GitHub; authorization expired or disconnected')
        try: return self.cipher.decrypt(row['token'].encode()).decode()
        except InvalidToken: raise HTTPException(401,'Reconnect GitHub; credential unavailable') from None

    def repositories(self,user,include_private=False):
        token=self.token(user)
        repos=[]
        for page in range(1,11):
            result=self.api(token,f'/user/installations?per_page=100&page={page}')
            installs=result['installations']
            for installation in installs:
                if installation.get('suspended_at'): continue
                # Only installations belonging to this configured app are eligible.
                if str(installation.get('app_id',''))!=self.app_id: continue
                for rp in range(1,11):
                    found=self.api(token,f'/user/installations/{installation["id"]}/repositories?per_page=100&page={rp}')['repositories']
                    for repo in found:
                        if repo.get('private') and not include_private: continue
                        repos.append({'full_name':repo['full_name'],'default_branch':repo.get('default_branch','main'),'id':repo['id'],'installation_id':installation['id'],
                                      'permissions':repo.get('permissions',{}),'app_permissions':installation.get('permissions',{})})
                    if len(found)<100: break
                else: raise HTTPException(403,'Repository access exceeds supported pagination limit')
            if len(installs)<100: break
        else: raise HTTPException(403,'Installation access exceeds supported pagination limit')
        return repos

    def authorize_application(self, user, repository, write=False):
        for repo in self.repositories(user, include_private=True):
            if repo['full_name'].lower() != repository.lower(): continue
            permissions = repo['app_permissions']
            if permissions.get('contents') not in {'read', 'write'}:
                raise HTTPException(403, 'CONEL requires selected-repository Contents read access')
            if write and (not repo['permissions'].get('push') or permissions.get('contents') != 'write' or permissions.get('pull_requests') != 'write'):
                raise HTTPException(403, 'PR publication requires user push access and GitHub App Contents and Pull requests write access')
            return self.token(user)
        raise HTTPException(403, 'Install the CONEL GitHub App on this repository')

    def authenticate(self,request):
        raw=request.cookies.get(self.cookie,'')
        with self.store.transaction() as db:
            row=db.execute('SELECT * FROM browser_sessions WHERE hash=? AND expires>?',(digest(raw),time.time())).fetchone()
        if not row: raise HTTPException(401,'GitHub login required')
        self.token(row['user_id'])
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('origin')!=self.origin or not secrets.compare_digest(request.headers.get('x-csrf-token',''),row['csrf']):
                raise HTTPException(403,'Invalid request origin or CSRF token')
        return row['user_id']

    def routes(self,app):
        @app.get('/api/auth/github/connect')
        def connect(request:Request):
            self.require_configured()
            callback=urlparse(self.callback)
            if (request.url.hostname in {'localhost','127.0.0.1'}
                    and callback.hostname in {'localhost','127.0.0.1'}
                    and request.url.netloc != callback.netloc):
                # Bind the login cookie to the same host that receives the callback.
                return RedirectResponse(callback.scheme+'://'+callback.netloc+'/api/auth/github/connect',302)
            state=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(48)
            challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            with self.store.transaction() as db:
                db.execute('DELETE FROM oauth_states WHERE expires<?',(time.time(),))
                db.execute('INSERT INTO oauth_states VALUES(?,?,?)',(digest(state),self.cipher.encrypt(verifier.encode()).decode(),time.time()+600))
            response=RedirectResponse('https://github.com/login/oauth/authorize?'+urlencode({'client_id':self.client_id,'redirect_uri':self.callback,'state':state,'code_challenge':challenge,'code_challenge_method':'S256'}),302)
            response.set_cookie(self.state_cookie,state,max_age=600,httponly=True,secure=self.secure,samesite='lax',path='/')
            return response

        @app.get('/api/auth/github/callback')
        def callback(request:Request,code:str='',state:str=''):
            self.require_configured()
            cookie=request.cookies.get(self.state_cookie,'')
            if not state:
                raise HTTPException(400,'Start login at /api/auth/github/connect; callback requires OAuth state')
            if not cookie:
                raise HTTPException(400,'Login cookie missing. Enable cookies and start login using the callback hostname in the same browser')
            if not secrets.compare_digest(state,cookie):
                raise HTTPException(400,'Login state changed. Close older authorization tabs and start one new login')
            with self.store.transaction() as db:
                row=db.execute('SELECT * FROM oauth_states WHERE hash=? AND expires>?',(digest(state),time.time())).fetchone()
                db.execute('DELETE FROM oauth_states WHERE hash=?',(digest(state),))
            if not row or not code: raise HTTPException(400,'Expired or reused OAuth state')
            try:
                with httpx.Client(timeout=20,follow_redirects=False) as client:
                    r=client.post('https://github.com/login/oauth/access_token',headers={'Accept':'application/json'},data={'client_id':self.client_id,'client_secret':self.secret,'code':code,'redirect_uri':self.callback,'code_verifier':self.cipher.decrypt(row['verifier'].encode()).decode()})
                payload=r.json()
                token=payload.get('access_token')
                if r.status_code!=200 or not token or payload.get('error'): raise HTTPException(401,'GitHub authorization failed')
                profile=self.api(token,'/user')
                user='github:'+str(int(profile['id']))
                expires=time.time()+min(int(payload.get('expires_in',28800)),28800)
                raw=secrets.token_urlsafe(48); csrf=secrets.token_urlsafe(32)
                with self.store.transaction() as db:
                    db.execute('INSERT INTO users(id,github_login,created_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET github_login=excluded.github_login',(user,profile['login'],time.time()))
                    db.execute('INSERT INTO github_connections VALUES(?,?,?,?,0) ON CONFLICT(user_id) DO UPDATE SET login=excluded.login,token=excluded.token,expires=excluded.expires,revoked=0',(user,profile['login'],self.cipher.encrypt(token.encode()).decode(),expires))
                    db.execute('DELETE FROM browser_sessions WHERE user_id=?',(user,))
                    db.execute('INSERT INTO browser_sessions VALUES(?,?,?,?)',(digest(raw),user,csrf,expires))
                response=RedirectResponse(self.origin+'/dashboard',302)
                response.delete_cookie(self.state_cookie,path='/',secure=self.secure,httponly=True,samesite='lax')
                response.set_cookie(self.cookie,raw,max_age=max(1,int(expires-time.time())),httponly=True,secure=self.secure,samesite='lax',path='/')
                return response
            except (httpx.HTTPError,ValueError,KeyError,InvalidToken):
                raise HTTPException(502,'GitHub login failed') from None

        @app.get('/api/auth/session')
        def session(request:Request):
            user=self.authenticate(request)
            with self.store.transaction() as db:
                row=db.execute('SELECT s.csrf,c.login FROM browser_sessions s JOIN github_connections c USING(user_id) WHERE s.hash=?',(digest(request.cookies[self.cookie]),)).fetchone()
            github_id = user.removeprefix('github:')
            avatar = 'https://avatars.githubusercontent.com/u/'+github_id+'?v=4' if github_id.isdigit() else None
            response=JSONResponse({'user_id':user,'github_login':row['login'],'avatar_url':avatar,'csrf_token':row['csrf']})
            response.headers['Cache-Control']='no-store'
            return response

        @app.post('/api/auth/logout')
        def logout(request:Request):
            self.authenticate(request)
            with self.store.transaction() as db:
                db.execute('DELETE FROM browser_sessions WHERE hash=?', (digest(request.cookies.get(self.cookie,'')),))
            response=JSONResponse({'signed_out':True})
            response.delete_cookie(self.cookie,path='/',secure=self.secure,httponly=True,samesite='lax')
            response.headers['Cache-Control']='no-store'
            return response

        @app.post('/api/auth/disconnect')
        def disconnect(request:Request):
            user=self.authenticate(request)
            with self.store.transaction() as db:
                db.execute("UPDATE github_connections SET revoked=1,token='' WHERE user_id=?",(user,))
                db.execute('DELETE FROM browser_sessions WHERE user_id=?',(user,))
            response=JSONResponse({'disconnected':True})
            response.delete_cookie(self.cookie,path='/',secure=self.secure,httponly=True,samesite='lax')
            return response

        @app.post('/api/auth/github/webhook')
        async def webhook(request:Request):
            secret=os.getenv('GITHUB_APP_WEBHOOK_SECRET','')
            if not secret: raise HTTPException(503,'GitHub webhook secret not configured')
            body=await request.body()
            if len(body)>1048576: raise HTTPException(413,'Webhook too large')
            expected='sha256='+hmac.new(secret.encode(),body,hashlib.sha256).hexdigest()
            if not secrets.compare_digest(request.headers.get('x-hub-signature-256',''),expected):
                raise HTTPException(401,'Invalid GitHub webhook signature')
            try: payload=json.loads(body)
            except ValueError: raise HTTPException(400,'Invalid webhook JSON') from None
            if request.headers.get('x-github-event')=='github_app_authorization' and payload.get('action')=='revoked':
                try: user='github:'+str(int(payload['sender']['id']))
                except (KeyError,TypeError,ValueError): raise HTTPException(400,'Invalid revocation payload') from None
                with self.store.transaction() as db:
                    db.execute("UPDATE github_connections SET revoked=1,token='' WHERE user_id=?",(user,))
                    db.execute('DELETE FROM browser_sessions WHERE user_id=?',(user,))
            return {'received':True}
