"""Keyword rules that tag Indian market news and policy items.

Tags are pointers for a human reader, not a classifier: open the story.
"""

import re
from typing import List, Tuple

NEWS_TAGS: List[Tuple[str, str]] = [
    ("results", r"\bresults?\b|\bQ[1-4]\b|\bquarterly\b|\bearnings\b|\bprofit\b|\bnet loss\b|\brevenue\b|\bEBITDA\b|\bPAT\b|financial results"),
    ("order-win", r"\border(s)? (win|worth|received|bag|from)\b|\bbags?\b.*\border\b|\bcontract\b|\bLoA\b|letter of award"
                  r"|\bwins?\b.*\b(order|contract|deal)\b"),
    ("deal", r"\bacqui|\bmerger\b|\bamalgamation\b|\btakeover\b|\bstake (buy|sale)\b|\bdemerger\b|\bJV\b|joint venture|\bscheme of arrangement\b"),
    ("rating", r"\bupgrade|\bdowngrade|\btarget price\b|\btarget of\b|\bbuy rating\b|\bsell rating\b|\b(buy|sell|hold|accumulate|reduce)\b.*\btarget\b"
               r"|\bbrokerage\b|\boverweight\b|\bunderweight\b|\btarget\b|\bcoverage\b|credit rating"),
    ("concall", r"con\. ?call|conference call|analysts?/institutional|investor meet|earnings call"),
    ("corporate-action", r"\bdividend\b|\bbonus\b|\bsplit\b|\bbuyback\b|\brecord date\b|\brights issue\b"),
    ("fund-raise", r"\bQIP\b|\bIPO\b|\bOFS\b|\bfund ?rais|\bpreferential\b|\bNCD\b|\bdebentures?\b"),
    ("stake", r"\bblock deal\b|\bbulk deal\b|\bpromoter\b|\bpledge\b|\bstake\b|\binsider\b"),
    ("management", r"\bCEO\b|\bMD\b|\bCFO\b|\bchairman\b|\bresign|\bappoint|\bstep(s|ped)? down\b|\bKMP\b|senior management"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bpenalt|\bfine[ds]?\b|\bprobe\b|\braid\b|\bshow cause\b|\bban\b|\bNCLT\b|\binsolvency\b|\bCCI\b"
                   r"|\bUSFDA\b|\bwarning letter\b|\bobservation"),
    ("guidance", r"\bguidance\b|\boutlook\b|\bforecast\b"),
    ("macro", r"\bRBI policy\b|\brepo rate\b|\binflation\b|\bCPI\b|\bWPI\b|\bGDP\b|\bFed\b|\bFOMC\b|\bcrude\b|\brupee\b|\bFII|\bFPI|\bDII\b"
              r"|\btariff|\bbudget\b|\bGST\b|\bbond yield"),
    ("market", r"\bSensex\b|\bNifty\b|\bstock market\b|\bmarket(s)? (today|close|open)\b|\bBank Nifty\b"),
]

POLICY_THEMES: List[Tuple[str, str]] = [
    ("rbi-rates", r"\brepo\b|\bmonetary policy\b|\bMPC\b|\bpolicy rate\b|\bCRR\b|\bSLR\b"),
    ("rbi-liquidity", r"\bVRR\b|\bVRRR\b|\bliquidity\b|\bLAF\b|\bOMO\b|\bauction\b"),
    ("banking-rules", r"\bbank(s|ing)?\b.*\b(direction|guideline|norms?|circular)|\bNBFC\b|\bKYC\b|\bprovisioning\b"),
    ("fno-rules", r"\bF&O\b|\bderivative|\bexpiry\b|\blot size\b|\bposition limit|\bmargin\b|\boptions?\b"),
    ("ban-surveillance", r"\bban period\b|\bsecurities in ban\b|\bASM\b|\bGSM\b|\bsurveillance\b|\bcircuit\b|\bprice band"),
    ("listing-ipo", r"\bIPO\b|\blisting\b|\bSME\b|\boffer document\b"),
    ("investor-caution", r"\bcaution\b|\bfraud|\bunregistered\b|\bWhatsApp\b|\binvestor alert"),
    ("trade-policy", r"\bFTA\b|\btrade (deal|pact|agreement)\b|\bexport\b|\bimport duty\b|\btariff"),
    ("tax-fiscal", r"\bGST\b|\btax\b|\bfiscal\b|\bbudget\b|\bSTT\b|\bdisinvestment\b"),
    ("macro-data", r"\binflation\b|\bCPI\b|\bWPI\b|\bGDP\b|\bIIP\b|\bPMI\b|\bforex reserves\b|\btrade deficit\b|\bcore sector\b"),
]

_NEWS_RULES = [(name, re.compile(rx, re.I)) for name, rx in NEWS_TAGS]
_POLICY_RULES = [(name, re.compile(rx, re.I)) for name, rx in POLICY_THEMES]


def tag(text: str) -> List[str]:
    return [name for name, rx in _NEWS_RULES if rx.search(text)]


def policy_themes(text: str) -> List[str]:
    return [name for name, rx in _POLICY_RULES if rx.search(text)]
