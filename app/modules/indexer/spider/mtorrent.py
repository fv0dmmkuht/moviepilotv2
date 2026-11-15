import re
from datetime import datetime
from typing import List, Optional, Tuple
from app.core.config import settings
from app.helper.mirror_key import mirror_host, mirror_origin, mirror_slug
from app.log import logger
from app.schemas import MediaType
from app.utils.http import AsyncRequestUtils, RequestUtils
DEFAULT_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'

class MTorrentSpider:
    _size = 100
    _timeout = 15
    _legacy_hosts = ('m-team.io', 'm-team.cc', 'm-team.vip')
    _movie_category = ['401', '419', '420', '421', '439', '405', '404']
    _tv_category = ['403', '402', '435', '438', '404', '405']
    _movie_words = ('电影', '影片', '剧场', 'movie', 'film')
    _tv_words = ('剧', '电视', '综艺', '纪录', '动漫', '动画', 'series', 'tv', 'anime', 'documentary')

    def __init__(self, indexer: dict):
        indexer = indexer or {}
        self._name = indexer.get('name') or ''
        self._entry = indexer
        url = str(indexer.get('url') or indexer.get('domain') or '')
        domain = str(indexer.get('domain') or '')
        self._origin = str(indexer.get('api_url') or '').rstrip('/') or mirror_origin(url) or mirror_origin(domain)
        self._slug = str(indexer.get('slug') or '').strip() or mirror_slug(url) or mirror_slug(domain)
        self._base = (str(indexer.get('api_url') or '') or self._origin).rstrip('/')
        self._legacy = self._detect_legacy(domain, url, indexer)
        if self._legacy and (not self._origin):
            self._origin = str(url or domain).strip().rstrip('/')
        self._apikey = str(indexer.get('apikey') or '').strip()
        self._cookie = indexer.get('cookie')
        self._ua = indexer.get('ua')
        self._proxy = settings.PROXY if indexer.get('proxy') else None
        self._timeout = indexer.get('timeout') or self._timeout
        self.error_detail: Optional[str] = None

    @classmethod
    def get_search_page_size(cls, keyword: Optional[str]=None) -> Optional[int]:
        return cls._size

    def _detect_legacy(self, domain: str, url: str, indexer: dict) -> bool:
        text = f'{domain} {url}'.lower()
        if any((host in text for host in self._legacy_hosts)):
            return True
        if str(indexer.get('slug') or '').strip():
            return False
        cookie = str(indexer.get('cookie') or '')
        return 'mt_session=' in cookie and (not str(indexer.get('apikey') or '').strip())

    def _headers(self) -> dict:
        headers = {'Accept': 'application/json', 'User-Agent': self._ua or DEFAULT_UA}
        if self._apikey:
            headers['Authorization'] = f'Bearer {self._apikey}'
        return headers

    def _http_kwargs(self) -> dict:
        return {'headers': self._headers(), 'cookies': self._cookie, 'proxies': self._proxy, 'timeout': self._timeout}

    def _params(self, keyword: Optional[str], mtype: Optional[MediaType], cat: Optional[str], page: Optional[int]) -> dict:
        words = keyword or ''
        if words.startswith('tt'):
            words = f'https://www.imdb.com/title/{words}'
        params = {'q': words, 'page': int(page or 0) + 1, 'page_size': self._size}
        if not self._legacy:
            return params
        if cat:
            categories = [c.strip() for c in str(cat).split(',') if c.strip()]
        elif not mtype:
            categories = []
        elif mtype == MediaType.TV:
            categories = self._tv_category
        else:
            categories = self._movie_category
        params['cat'] = ','.join(categories)
        return params

    def _url(self) -> str:
        base = self._origin or self._base
        if self._legacy:
            return f'{base}/api/local/torrents'
        return f'{base}/api/v1/sites/{self._slug}/torrents'

    def search(self, keyword: Optional[str], mtype: Optional[MediaType]=None, cat: Optional[str]=None, page: Optional[int]=0) -> Tuple[bool, List[dict]]:
        if not self._url_ready():
            return (True, [])
        res = RequestUtils(**self._http_kwargs()).get_res(self._url(), params=self._params(keyword, mtype, cat, page))
        return self._process(res)

    async def async_search(self, keyword: Optional[str], mtype: Optional[MediaType]=None, cat: Optional[str]=None, page: Optional[int]=0) -> Tuple[bool, List[dict]]:
        if not self._url_ready():
            return (True, [])
        res = await AsyncRequestUtils(**self._http_kwargs()).get_res(self._url(), params=self._params(keyword, mtype, cat, page))
        return self._process(res)

    def _url_ready(self) -> bool:
        if self._legacy:
            if not (self._origin or self._base):
                self.error_detail = '站点地址为空'
                return False
            return True
        if not (self._origin or self._base) or not self._slug:
            self.error_detail = '站点地址或站点标识为空'
            logger.warning(f'{self._name} 搜索失败：{self.error_detail}')
            return False
        return True

    def _process(self, res) -> Tuple[bool, List[dict]]:
        self.error_detail = None
        if res is None:
            self.error_detail = f'无法连接 {self._origin or self._base}'
            logger.warning(f'{self._name} 搜索失败：{self.error_detail}')
            return (True, [])
        status_code = getattr(res, 'status_code', 0)
        if status_code != 200:
            self.error_detail = self._error_text(status_code)
            logger.warning(f'{self._name} 搜索失败，{self.error_detail}')
            return (True, [])
        try:
            payload = res.json()
        except Exception as err:
            self.error_detail = '响应不是合法 JSON'
            logger.warning(f'{self._name} 搜索失败：{self.error_detail}（{err}）')
            return (True, [])
        items = self._items(payload)
        torrents = []
        for item in items:
            mapped = self._map_legacy(item) if self._legacy else self._map_mirror(item)
            if mapped:
                torrents.append(mapped)
        return (False, torrents)

    @staticmethod
    def _items(payload) -> list:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get('items'), list):
            return payload['items']
        data = payload.get('data')
        if isinstance(data, dict) and isinstance(data.get('items'), list):
            return data['items']
        return []

    @staticmethod
    def _error_text(status_code: int) -> str:
        if status_code == 401:
            return 'API 密钥无效或已撤销（401）'
        if status_code == 403:
            return '站点未授权、已到期或额度用尽（403）'
        if status_code == 429:
            return '请求过于频繁，已被限流（429）'
        return f'HTTP {status_code}'

    def _enclosure(self, tid: str) -> str:
        base = self._origin or self._base
        if self._legacy:
            return f'{base}/api/local/torrents/{tid}/file'
        return f'{base}/api/v1/sites/{self._slug}/torrents/{tid}/file'

    def _page_url(self, tid: str) -> str:
        host = mirror_host()
        if self._legacy:
            return f'{self._origin or self._base}/torrent/{tid}'
        return f'https://{host}/{self._slug}/torrents/{tid}'

    def _map_mirror(self, item: dict) -> Optional[dict]:
        if not isinstance(item, dict):
            return None
        tid = item.get('torrent_id') or item.get('id')
        if tid in (None, ''):
            return None
        tid = str(tid)
        category = str(item.get('category') or '')
        return {'title': item.get('title'), 'description': category or None, 'enclosure': self._enclosure(tid), 'pubdate': self._format_time(item.get('published_at')), 'size': int(item.get('size_bytes') or 0), 'seeders': int(item.get('seeders') or 0), 'peers': int(item.get('leechers') or 0), 'grabs': int(item.get('completed') or 0), 'downloadvolumefactor': 1.0, 'uploadvolumefactor': 1.0, 'page_url': self._page_url(tid), 'imdbid': '', 'labels': [], 'category': self._media_type(category)}

    def _map_legacy(self, item: dict) -> Optional[dict]:
        if not isinstance(item, dict):
            return None
        tid = item.get('id')
        if tid in (None, ''):
            return None
        tid = str(tid)
        category = str(item.get('category') or '')
        labels = [str(x) for x in item.get('labels') or [] if x]
        if item.get('has_chinese_subtitle') and '中字' not in labels:
            labels.append('中字')
        return {'title': item.get('name'), 'description': item.get('small_descr'), 'enclosure': self._enclosure(tid), 'pubdate': self._format_time(item.get('created_at')), 'size': int(item.get('size_bytes') or 0), 'seeders': int((item.get('status') or {}).get('seeders') or 0), 'peers': int((item.get('status') or {}).get('leechers') or 0), 'grabs': int((item.get('status') or {}).get('completed') or 0), 'downloadvolumefactor': 1.0, 'uploadvolumefactor': 1.0, 'page_url': self._page_url(tid), 'imdbid': self._find_imdbid(item.get('imdb')), 'labels': labels, 'category': self._media_type(category, cat_id=True)}

    @classmethod
    def _media_type(cls, category: str, cat_id: bool=False) -> str:
        text = str(category or '').strip()
        if cat_id:
            if text in cls._movie_category:
                return MediaType.MOVIE.value
            if text in cls._tv_category:
                return MediaType.TV.value
            return MediaType.UNKNOWN.value
        lowered = text.lower()
        if any((word in lowered for word in cls._movie_words)):
            return MediaType.MOVIE.value
        if any((word in lowered for word in cls._tv_words)):
            return MediaType.TV.value
        return MediaType.UNKNOWN.value

    @staticmethod
    def _format_time(value) -> Optional[str]:
        if value in (None, ''):
            return None
        if isinstance(value, (int, float)):
            seconds = float(value)
            if seconds > 1000000000000.0:
                seconds /= 1000.0
            return datetime.fromtimestamp(seconds).strftime('%Y-%m-%d %H:%M:%S')
        text = str(value).strip()
        if text.isdigit():
            return MTorrentSpider._format_time(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            return text
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _find_imdbid(imdb: Optional[str]) -> str:
        if not imdb:
            return ''
        found = re.search('tt\\d+', str(imdb))
        return found.group(0) if found else ''

    def get_subtitle_links(self, page_url: str) -> List[str]:
        return []

    def get_subtitle_links_by_id(self, torrent_id: str) -> List[str]:
        return []
