from app.helper.mirror_key import mirror_host
from app.helper.sites import SitesHelper
SITES = (('audiences', 'Audiences'), ('chdbits', 'CHDBits'), ('hdfans', 'HDFans'), ('hdhome', 'HDHome'), ('hdsky', 'HDSky'), ('hhclub', 'HHClub'), ('opencd', 'OpenCD'), ('ourbits', 'OurBits'), ('tccf', 'TCCF'), ('ttg', 'TTG'))
_DROP_KEYS = ('language', 'subtitles', 'api_domain', 'api_host')
_BASE_ID = 93000

def entries() -> list:
    host = mirror_host()
    rows = []
    for index, (slug, name) in enumerate(SITES, start=1):
        rows.append({'id': _BASE_ID + index, 'name': name, 'domain': f'{host}/{slug}', 'url': f'https://{host}/{slug}/', 'api_url': f'https://{host}', 'slug': slug, 'parser': 'mTorrent', 'schema': 'MTorrent', 'public': False, 'pri': 10 + index})
    return rows

def site_keys() -> list:
    host = mirror_host()
    return [host] + [f'{host}/{slug}' for slug, _ in SITES]

def site_hosts() -> list:
    host = mirror_host()
    return [f'{slug}.{host}' for slug, _ in SITES]

def token_of(site) -> str:
    token = str(getattr(site, 'apikey', '') or '').strip()
    if token:
        return token
    cookie = str(getattr(site, 'cookie', '') or '')
    for part in cookie.split(';'):
        name, _, value = part.partition('=')
        if name.strip() in ('mt_session', 'mirror_session') and value.strip():
            return value.strip()
    return ''

def _merge(existing, entry) -> dict:
    merged = dict(existing or {})
    merged.update(entry)
    for drop in _DROP_KEYS:
        merged.pop(drop, None)
    return merged

def register() -> None:
    try:
        helper = SitesHelper()
        sites = helper.get_indexsites() or {}
    except Exception:
        return
    if not isinstance(sites, dict):
        return
    for entry in entries():
        key = entry['domain']
        try:
            helper.add_indexer(key, _merge(sites.get(key), entry))
        except Exception:
            continue
    _install_site_test()

def _probe(site):
    from app.core.config import settings
    from app.utils.http import RequestUtils
    token = token_of(site)
    if not token:
        return (False, '未配置 API 密钥')
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    res = RequestUtils(headers=headers, proxies=settings.PROXY if getattr(site, 'proxy', 0) else None, timeout=getattr(site, 'timeout', 0) or 15).get_res(f'https://{mirror_host()}/api/v1/me')
    if res is None:
        return (False, '无法连接镜像站')
    if res.status_code == 200:
        return (True, '连接成功')
    if res.status_code == 401:
        return (False, 'API 密钥无效或已撤销')
    if res.status_code == 403:
        return (False, '账号被暂停或不可用')
    return (False, f'错误：{res.status_code}')

def _install_site_test() -> None:
    try:
        from app.chain.site import SiteChain
    except Exception:
        return
    if getattr(SiteChain, '_mirror_site_test_patched', False):
        return
    original = SiteChain.__init__

    def __init__(self, *args, **kwargs):
        original(self, *args, **kwargs)
        try:
            for key in site_keys() + site_hosts():
                self.special_site_test[key] = _probe
        except Exception:
            pass
    SiteChain.__init__ = __init__
    SiteChain._mirror_site_test_patched = True
