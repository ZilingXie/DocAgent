from app.qa.messages import INSUFFICIENT_EVIDENCE_REPLY

OUT_OF_SCOPE_REPLY = (
    "I'm Agora Document Agent. I'm only able to answer questions about Agora documents."
)

_STRONG_AGORA_HINTS: tuple[str, ...] = (
    "agora",
    "声网",
    "agorartc",
    "video calling",
    "video-calling",
    "rtc",
    "rtm",
    "实时音视频",
)

_WEAK_AGORA_HINTS: tuple[str, ...] = (
    "appid",
    "app id",
    "token",
    "uid",
    "channel",
    "join channel",
    "sdk",
    "cloud proxy",
    "cloud recording",
    "screen share",
    "screen sharing",
    "spatial audio",
    "console",
    "频道",
    "加入频道",
    "鉴权",
    "录制",
    "音视频",
    "推流",
    "拉流",
)

_OUT_OF_SCOPE_HINTS: tuple[str, ...] = (
    "weather",
    "temperature",
    "forecast",
    "rain",
    "snow",
    "humidity",
    "stock",
    "stocks",
    "bitcoin",
    "btc",
    "eth",
    "crypto",
    "nba",
    "nfl",
    "mlb",
    "epl",
    "soccer",
    "football",
    "score",
    "match",
    "news",
    "politics",
    "president",
    "election",
    "recipe",
    "cook",
    "cooking",
    "travel",
    "flight",
    "hotel",
    "movie",
    "music",
    "song",
    "joke",
    "poem",
    "story",
    "translate",
    "translation",
    "天气",
    "温度",
    "预报",
    "下雨",
    "下雪",
    "股票",
    "股价",
    "比特币",
    "加密货币",
    "体育",
    "比赛",
    "新闻",
    "政治",
    "总统",
    "选举",
    "菜谱",
    "做饭",
    "旅行",
    "航班",
    "酒店",
    "电影",
    "音乐",
    "笑话",
    "翻译",
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def looks_agora_related(question: str) -> bool:
    normalized = _normalize(question)
    if not normalized:
        return False
    if _contains_hint(normalized, _STRONG_AGORA_HINTS):
        return True
    has_out_of_scope_hints = _contains_hint(normalized, _OUT_OF_SCOPE_HINTS)
    return _contains_hint(normalized, _WEAK_AGORA_HINTS) and not has_out_of_scope_hints


def is_obviously_out_of_scope(question: str) -> bool:
    normalized = _normalize(question)
    if not normalized:
        return False
    return _contains_hint(normalized, _OUT_OF_SCOPE_HINTS) and not looks_agora_related(
        normalized
    )


def should_replace_insufficient_reply(
    question: str,
    answer_text: str,
    has_history: bool,
) -> bool:
    if has_history:
        return False
    if answer_text.strip() != INSUFFICIENT_EVIDENCE_REPLY:
        return False
    return not looks_agora_related(question)
