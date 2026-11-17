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
    _ensure_site_cards()
    _install_site_test()

def _ensure_site_cards() -> None:
    import sqlite3
    from datetime import datetime
    from app.core.config import settings
    try:
        db_path = settings.CONFIG_PATH / 'user.db'
        if not db_path.exists():
            return
        host = mirror_host()
        con = sqlite3.connect(str(db_path), timeout=10)
        try:
            con.execute('PRAGMA busy_timeout=8000')
            exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='site'").fetchone()
            if not exists:
                return
            current = {row[0] for row in con.execute('SELECT domain FROM site')}
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for index, (slug, name) in enumerate(SITES, start=1):
                domain = f'{host}/{slug}'
                if domain in current:
                    continue
                con.execute('INSERT INTO site (name, domain, url, pri, rss, cookie, ua, apikey, token, proxy, filter, render, public, note, limit_interval, limit_count, limit_seconds, timeout, is_active, downloader, lst_mod_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (name, domain, f'https://{host}/{slug}/', 10 + index, '', '', '', '', '', 0, '', 0, 0, None, 0, 0, 0, 15, 1, None, now))
            con.commit()
        finally:
            con.close()
    except Exception as err:
        try:
            from app.log import logger
            logger.warning(f'mirror site cards skipped: {err}')
        except Exception:
            pass

def legacy_keys() -> list:
    return [entry['domain'] for entry in LEGACY_SITES]

def _probe_legacy(site):
    from app.core.config import settings
    from app.utils.http import RequestUtils
    token = token_of(site)
    if not token:
        return (False, '未配置 API 密钥')
    base = str(getattr(site, 'url', '') or getattr(site, 'domain', '') or '').strip().rstrip('/')
    if not base:
        return (False, '站点地址为空')
    if '://' not in base:
        base = 'https://' + base
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    res = RequestUtils(headers=headers, proxies=settings.PROXY if getattr(site, 'proxy', 0) else None, timeout=getattr(site, 'timeout', 0) or 15).get_res(f'{base}/api/local/user/me')
    if res is None:
        return (False, '无法连接站点')
    if res.status_code == 200:
        try:
            payload = res.json() or {}
        except Exception:
            payload = {}
        if (payload.get('data') or {}).get('user'):
            return (True, '连接成功')
        return (False, '密钥无效或返回异常')
    if res.status_code == 401:
        return (False, 'API 密钥无效或未登录')
    if res.status_code == 403:
        return (False, '令牌仅支持只读访问或账号受限')
    return (False, f'错误：{res.status_code}')

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
            for key in legacy_keys():
                self.special_site_test[key] = _probe_legacy
        except Exception:
            pass
    SiteChain.__init__ = __init__
    SiteChain._mirror_site_test_patched = True
