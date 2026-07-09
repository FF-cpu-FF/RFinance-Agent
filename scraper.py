"""
Reddit Finanz-Agent – scraper.py (RSS + Feed-Auth Version)
Läuft stündlich via GitHub Actions. Nutzt private Feed-Tokens gegen Rate-Limits.
"""

import json
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import defaultdict
import os

SUBREDDITS = ["Mauerstrassenwetten", "wallstreetbets", "Ameisenstrassenwetten"]
SORT   = "hot"
LIMIT  = 50
OUTPUT = "docs/data.json"

SKIP = {
    "DD","YOLO","WSB","ETF","CEO","IPO","FDA","GDP","EUR","USD","GBP","CHF",
    "SPY","QQQ","PUT","CALL","BUY","SELL","HOLD","EPS","PE","ATH","ATL","OP",
    "FED","ECB","DAX","IMO","FOMO","DIY","USA","UK","EU","DE","AG","SE","SA",
    "NV","LTD","INC","PLC","LLC","EDIT","TL","DR","EV","AI","ML","IT","TV",
    "PC","AM","PM","OK","DM","TA","WTF","LMAO","LOL","OMG","PS","IQ","HQ",
    "HR","PR","CTO","CFO","COO","HOT","NEW","TOP","THE","AND","FOR","YOU",
    "ARE","NOT","BUT","ALL","CAN",
