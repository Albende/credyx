"""Country adapter registry.

Returns the right CountryAdapter for an ISO 3166-1 alpha-2 country code. Real
adapters live in `packages.adapters.{cc}`; everything else falls through to
NotImplementedAdapter so the API surface stays consistent.
"""
from __future__ import annotations

from functools import lru_cache

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._stubs import build_stub_registry


def _build_real_adapters() -> dict[str, CountryAdapter]:
    from packages.adapters.al import ALAdapter
    from packages.adapters.am import AMAdapter
    from packages.adapters.ao import AOAdapter
    from packages.adapters.ar import ARAdapter
    from packages.adapters.at import ATAdapter
    from packages.adapters.au import AUAdapter
    from packages.adapters.az import AZAdapter
    from packages.adapters.ba import BAAdapter
    from packages.adapters.bd import BDAdapter
    from packages.adapters.be import BEAdapter
    from packages.adapters.bg import BGAdapter
    from packages.adapters.bh import BHAdapter
    from packages.adapters.bo import BOAdapter
    from packages.adapters.br import BRAdapter
    from packages.adapters.bw import BWAdapter
    from packages.adapters.by import BYAdapter
    from packages.adapters.ca import CAAdapter
    from packages.adapters.cd import CDAdapter
    from packages.adapters.ch import CHAdapter
    from packages.adapters.ci import CIAdapter
    from packages.adapters.cl import CLAdapter
    from packages.adapters.cm import CMAdapter
    from packages.adapters.co import COAdapter
    from packages.adapters.cr import CRAdapter
    from packages.adapters.cy import CYAdapter
    from packages.adapters.cz import CZAdapter
    from packages.adapters.de import DEAdapter
    from packages.adapters.dk import DKAdapter
    from packages.adapters.do import DOAdapter
    from packages.adapters.dz import DZAdapter
    from packages.adapters.ec import ECAdapter
    from packages.adapters.ee import EEAdapter
    from packages.adapters.eg import EGAdapter
    from packages.adapters.es import ESAdapter
    from packages.adapters.et import ETAdapter
    from packages.adapters.fi import FIAdapter
    from packages.adapters.fr import FRAdapter
    from packages.adapters.ge import GEAdapter
    from packages.adapters.gh import GHAdapter
    from packages.adapters.gr import GRAdapter
    from packages.adapters.hk import HKAdapter
    from packages.adapters.hr import HRAdapter
    from packages.adapters.hu import HUAdapter
    from packages.adapters.id_ import IDAdapter
    from packages.adapters.ie import IEAdapter
    from packages.adapters.il import ILAdapter
    from packages.adapters.in_ import INAdapter
    from packages.adapters.iq import IQAdapter
    from packages.adapters.is_ import ISAdapter
    from packages.adapters.it import ITAdapter
    from packages.adapters.jo import JOAdapter
    from packages.adapters.jp import JPAdapter
    from packages.adapters.ke import KEAdapter
    from packages.adapters.kg import KGAdapter
    from packages.adapters.kh import KHAdapter
    from packages.adapters.kr import KRAdapter
    from packages.adapters.kw import KWAdapter
    from packages.adapters.kz import KZAdapter
    from packages.adapters.lk import LKAdapter
    from packages.adapters.lt import LTAdapter
    from packages.adapters.lu import LUAdapter
    from packages.adapters.lv import LVAdapter
    from packages.adapters.ma import MAAdapter
    from packages.adapters.md import MDAdapter
    from packages.adapters.me import MEAdapter
    from packages.adapters.mg import MGAdapter
    from packages.adapters.mk import MKAdapter
    from packages.adapters.mm import MMAdapter
    from packages.adapters.mt import MTAdapter
    from packages.adapters.mu import MUAdapter
    from packages.adapters.mx import MXAdapter
    from packages.adapters.my import MYAdapter
    from packages.adapters.mz import MZAdapter
    from packages.adapters.ng import NGAdapter
    from packages.adapters.nl import NLAdapter
    from packages.adapters.no import NOAdapter
    from packages.adapters.np import NPAdapter
    from packages.adapters.nz import NZAdapter
    from packages.adapters.pe import PEAdapter
    from packages.adapters.ph import PHAdapter
    from packages.adapters.pk import PKAdapter
    from packages.adapters.pl import PLAdapter
    from packages.adapters.pt import PTAdapter
    from packages.adapters.py import PYAdapter
    from packages.adapters.qa import QAAdapter
    from packages.adapters.ro import ROAdapter
    from packages.adapters.rs import RSAdapter
    from packages.adapters.ru import RUAdapter
    from packages.adapters.sa import SAAdapter
    from packages.adapters.sc import SCAdapter
    from packages.adapters.se import SEAdapter
    from packages.adapters.sg import SGAdapter
    from packages.adapters.si import SIAdapter
    from packages.adapters.sk import SKAdapter
    from packages.adapters.sn import SNAdapter
    from packages.adapters.th import THAdapter
    from packages.adapters.tn import TNAdapter
    from packages.adapters.tr import TRAdapter
    from packages.adapters.tw import TWAdapter
    from packages.adapters.tz import TZAdapter
    from packages.adapters.ua import UAAdapter
    from packages.adapters.uk import UKAdapter
    from packages.adapters.us import USAdapter
    from packages.adapters.uy import UYAdapter
    from packages.adapters.uz import UZAdapter
    from packages.adapters.vn import VNAdapter
    from packages.adapters.xk import XKAdapter
    from packages.adapters.za import ZAAdapter
    from packages.adapters.zm import ZMAdapter
    from packages.adapters.zw import ZWAdapter

    return {
        "AE": __import__("packages.adapters.ae", fromlist=["AEAdapter"]).AEAdapter(),
        "AL": ALAdapter(),
        "AM": AMAdapter(),
        "AO": AOAdapter(),
        "AR": ARAdapter(),
        "AT": ATAdapter(),
        "AU": AUAdapter(),
        "AZ": AZAdapter(),
        "BA": BAAdapter(),
        "BD": BDAdapter(),
        "BE": BEAdapter(),
        "BG": BGAdapter(),
        "BH": BHAdapter(),
        "BO": BOAdapter(),
        "BR": BRAdapter(),
        "BW": BWAdapter(),
        "BY": BYAdapter(),
        "CA": CAAdapter(),
        "CD": CDAdapter(),
        "CH": CHAdapter(),
        "CI": CIAdapter(),
        "CL": CLAdapter(),
        "CM": CMAdapter(),
        "CO": COAdapter(),
        "CR": CRAdapter(),
        "CY": CYAdapter(),
        "CZ": CZAdapter(),
        "DE": DEAdapter(),
        "DK": DKAdapter(),
        "DO": DOAdapter(),
        "DZ": DZAdapter(),
        "EC": ECAdapter(),
        "EE": EEAdapter(),
        "EG": EGAdapter(),
        "ES": ESAdapter(),
        "ET": ETAdapter(),
        "FI": FIAdapter(),
        "FR": FRAdapter(),
        "GB": UKAdapter(),
        "GE": GEAdapter(),
        "GH": GHAdapter(),
        "GR": GRAdapter(),
        "HK": HKAdapter(),
        "HR": HRAdapter(),
        "HU": HUAdapter(),
        "ID": IDAdapter(),
        "IE": IEAdapter(),
        "IL": ILAdapter(),
        "IN": INAdapter(),
        "IQ": IQAdapter(),
        "IS": ISAdapter(),
        "IT": ITAdapter(),
        "JO": JOAdapter(),
        "JP": JPAdapter(),
        "KE": KEAdapter(),
        "KG": KGAdapter(),
        "KH": KHAdapter(),
        "KR": KRAdapter(),
        "KW": KWAdapter(),
        "KZ": KZAdapter(),
        "LK": LKAdapter(),
        "LT": LTAdapter(),
        "LU": LUAdapter(),
        "LV": LVAdapter(),
        "MA": MAAdapter(),
        "MD": MDAdapter(),
        "ME": MEAdapter(),
        "MG": MGAdapter(),
        "MK": MKAdapter(),
        "MM": MMAdapter(),
        "MT": MTAdapter(),
        "MU": MUAdapter(),
        "MX": MXAdapter(),
        "MY": MYAdapter(),
        "MZ": MZAdapter(),
        "NG": NGAdapter(),
        "NL": NLAdapter(),
        "NO": NOAdapter(),
        "NP": NPAdapter(),
        "NZ": NZAdapter(),
        "PE": PEAdapter(),
        "PH": PHAdapter(),
        "PK": PKAdapter(),
        "PL": PLAdapter(),
        "PT": PTAdapter(),
        "PY": PYAdapter(),
        "QA": QAAdapter(),
        "RO": ROAdapter(),
        "RS": RSAdapter(),
        "RU": RUAdapter(),
        "SA": SAAdapter(),
        "SC": SCAdapter(),
        "SE": SEAdapter(),
        "SG": SGAdapter(),
        "SI": SIAdapter(),
        "SK": SKAdapter(),
        "SN": SNAdapter(),
        "TH": THAdapter(),
        "TN": TNAdapter(),
        "TR": TRAdapter(),
        "TW": TWAdapter(),
        "TZ": TZAdapter(),
        "UA": UAAdapter(),
        "UK": UKAdapter(),  # alias of GB
        "US": USAdapter(),
        "UY": UYAdapter(),
        "UZ": UZAdapter(),
        "VN": VNAdapter(),
        "XK": XKAdapter(),
        "ZA": ZAAdapter(),
        "ZM": ZMAdapter(),
        "ZW": ZWAdapter(),
    }


@lru_cache(maxsize=1)
def get_adapter_registry() -> dict[str, CountryAdapter]:
    """Return the full registry: real adapters override stubs."""
    registry: dict[str, CountryAdapter] = {}
    for cc, stub in build_stub_registry().items():
        registry[cc.upper()] = stub
    for cc, real in _build_real_adapters().items():
        registry[cc.upper()] = real
    return registry


def get_adapter(country_code: str) -> CountryAdapter | None:
    return get_adapter_registry().get(country_code.upper())


def reset_registry() -> None:
    """Test helper — drop the cache."""
    get_adapter_registry.cache_clear()
