"""Global news themes and what each usually means for Indian stocks.

The impact notes are textbook cause and effect, not predictions: markets
often price news before it is printed.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Pattern


@dataclass(frozen=True)
class Theme:
    name: str
    pattern: str
    india_impact: str
    regex: Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "regex", re.compile(self.pattern, re.I))


THEMES: List[Theme] = [
    Theme("fed-rates",
          r"\bFed\b|\bFOMC\b|\bPowell\b|rate (cut|hike)s?|\binterest rates?\b|\bhawkish\b|\bdovish\b|\bTreasur(y|ies)\b|\byields?\b",
          "US rates/yields: higher yields pull FII money out of India (rupee weaker, banks/NBFCs/realty pressured); "
          "lower yields help FII inflows and rate-sensitive stocks."),
    Theme("us-data",
          r"\bCPI\b|\binflation\b|\bjobs report\b|\bpayrolls?\b|\bjobless\b|\bunemployment\b|\bPMI\b|\bGDP\b"
          r"|\bretail sales\b|\bPCE\b|\bconsumer (sentiment|confidence)\b",
          "US economic data moves Fed expectations: hot data = higher yields and dollar (negative for FII flows); "
          "soft data = the opposite. A weak US economy also hurts Indian IT demand."),
    Theme("crude",
          r"\boil\b|\bcrude\b|\bBrent\b|\bWTI\b|\bOPEC\b|\bgasoline\b",
          "Crude up: hurts OMCs (BPCL, HPCL, IOC), paints (Asian Paints, Berger), aviation (IndiGo), tyres, chemicals, "
          "and the rupee and inflation; helps ONGC, Oil India. Crude down: the reverse."),
    Theme("tech-ai",
          r"\bNasdaq\b|\bNvidia\b|\bMicrosoft\b|\bApple\b|\bAlphabet\b|\bGoogle\b|\bMeta\b|\bAmazon\b|\bAI\b|\bchips?\b"
          r"|\bsemiconductor|\btech (stocks|selloff|rally)\b|\bcloud\b",
          "US tech and AI spending: drives Indian IT (Infosys, TCS, Wipro, HCL Tech, Tech Mahindra, LTIMindtree, "
          "Persistent, Coforge) via client budgets and sentiment."),
    Theme("tariffs-trade",
          r"\btariffs?\b|\btrade (war|deal|talks)\b|\bsanctions?\b|\bexport (curbs|controls)\b|\bH-1B\b|\bvisa\b",
          "Tariffs and trade: hit Indian exporters (IT services, pharma, textiles, auto components, gems and jewellery, "
          "seafood); H-1B/visa changes hit IT. Trade deals help them."),
    Theme("dollar-fx",
          r"\bdollar\b|\bDXY\b|\brupee\b|\byen\b|\byuan\b|\bcurrenc",
          "Dollar strength: rupee weaker, FII outflows (negative for Nifty), but IT and pharma exporters earn more in "
          "rupees. Dollar weakness: the reverse."),
    Theme("china",
          r"\bChina\b|\bChinese\b|\bBeijing\b|\bstimulus\b|\bHang Seng\b|\bPBOC\b",
          "China: stimulus lifts metals (Tata Steel, JSW Steel, Hindalco, Vedanta, NMDC); a China rally can pull FII "
          "money from India; Chinese weakness can push it to India."),
    Theme("geopolitics",
          r"\bwar\b|\bmissile\b|\battack|\bstrikes?\b|\bUkraine\b|\bRussia\b|\bIsrael\b|\bIran\b|\bGaza\b|\bHouthi"
          r"|\bTaiwan\b|\bconflict\b|\bmilitary\b",
          "Geopolitical risk: risk-off (Nifty and VIX swing), crude and gold up; defence stocks (HAL, BEL, BDL) often "
          "gain; OMCs and aviation suffer."),
    Theme("earnings",
          r"\bearnings\b|\bresults\b|\bquarter(ly)?\b|\bguidance\b|\brevenue\b|\bprofit\b|\bbeats?\b|\bmiss(es)?\b",
          "US earnings: read across to Indian peers (Accenture/Cognizant -> Indian IT; US banks -> risk mood; "
          "US pharma -> Indian generics)."),
    Theme("pharma-fda",
          r"\bFDA\b|\bdrug\b|\bpharma\b|\bgenerics?\b|\bbiotech\b|\bvaccine\b",
          "US pharma and FDA: Indian generic makers (Sun Pharma, Dr Reddy's, Cipla, Lupin, Aurobindo, Zydus) earn "
          "heavily in the US; FDA actions and US drug pricing move them."),
    Theme("banks-credit",
          r"\bbanks?\b|\bcredit\b|\bdefault|\bbankruptcy\b|\bliquidity\b|\bbond market\b|\bspreads\b",
          "US bank or credit stress: global risk-off and FII selling; watch Indian banks and NBFCs."),
    Theme("gold-metals",
          r"\bgold\b|\bsilver\b|\bcopper\b|\baluminium\b|\baluminum\b|\bmetals?\b",
          "Metals: copper/aluminium up helps Hindalco, Vedanta, Nalco; gold up helps gold lenders (Muthoot, "
          "Manappuram) and hurts jewellery margins."),
    Theme("risk-mood",
          r"\bselloff\b|\bsell-off\b|\brout\b|\bplunge|\bcrash\b|\brally\b|\brecord high\b|\bVIX\b|\bvolatility\b"
          r"|\brisk-off\b|\brisk-on\b",
          "Global risk mood: sharp US/Asian selloffs usually mean a weak Indian open (gap-down) and higher India VIX; "
          "strong rallies a gap-up."),
]

IMPACT: Dict[str, str] = {theme.name: theme.india_impact for theme in THEMES}


def themes_of(text: str) -> List[str]:
    return [theme.name for theme in THEMES if theme.regex.search(text)]
