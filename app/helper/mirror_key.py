import os
from urllib.parse import urlparse
from app.utils.string import StringUtils
DEFAULT_MIRROR_HOST = 'ptroom.shop'

def mirror_host() -> str:
    return (os.getenv('MIRROR_SITE_HOST') or DEFAULT_MIRROR_HOST).strip().lower()

def site_key(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    probe = raw if '://' in raw else 'https://' + raw
    try:
        parsed = urlparse(probe)
    except ValueError:
        return StringUtils.get_url_domain(raw)
    host = (parsed.hostname or '').lower()
    if not host or host != mirror_host():
        return StringUtils.get_url_domain(raw)
    segments = [seg for seg in (parsed.path or '').split('/') if seg]
    if not segments:
        return host
    return host + '/' + segments[0]

def mirror_slug(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    probe = raw if '://' in raw else 'https://' + raw
    try:
        parsed = urlparse(probe)
    except ValueError:
        return ''
    if (parsed.hostname or '').lower() != mirror_host():
        return ''
    segments = [seg for seg in (parsed.path or '').split('/') if seg]
    return segments[0] if segments else ''

def mirror_origin(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    probe = raw if '://' in raw else 'https://' + raw
    try:
        parsed = urlparse(probe)
    except ValueError:
        return ''
    if not parsed.hostname:
        return ''
    scheme = parsed.scheme or 'https'
    return f'{scheme}://{parsed.hostname}'

def token_from_cookie(cookie) -> str:
    for part in str(cookie or '').split(';'):
        name, _, value = part.partition('=')
        if name.strip() in ('mt_session', 'mirror_session') and value.strip():
            return value.strip()
    return ''

def slug_of_name(name) -> str:
    try:
        from app.helper.mirror_sites import SITES
    except Exception:
        return ''
    target = str(name or '').strip().lower()
    if not target:
        return ''
    for slug, label in SITES:
        if label.lower() == target or slug.lower() == target:
            return slug
    return ''

def keep_mirror_site_url(url, name='') -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    probe = raw if '://' in raw else 'https://' + raw
    try:
        parsed = urlparse(probe)
    except ValueError:
        return ''
    host = (parsed.hostname or '').lower()
    if not host or host != mirror_host():
        return ''
    slug = mirror_slug(probe) or slug_of_name(name)
    scheme = parsed.scheme or 'https'
    if slug:
        return f'{scheme}://{host}/{slug}/'
    return f'{scheme}://{host}/'
