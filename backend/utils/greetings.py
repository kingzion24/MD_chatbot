"""
Time-aware Swahili greeting pool for the Mage assistant.

Greetings are split into three time buckets based on East Africa Time (EAT, UTC+3).
get_time_aware_greeting() is the only public symbol; it selects one greeting at
random from the bucket that matches the current hour and slots in the business name.
"""

import random
from datetime import datetime, timezone, timedelta

# East Africa Time — no external dependency required
_EAT = timezone(timedelta(hours=3))

# ---------------------------------------------------------------------------
# Greeting pools
# ---------------------------------------------------------------------------
# Rules enforced across all pools:
#   • Always introduce the assistant as "Mage"
#   • Slot in {business_name}
#   • Under 20 words per greeting
#   • Focus on asking the boss what task to handle (mauzo, hifadhi, gharama…)
# ---------------------------------------------------------------------------

# Hours 05:00 – 11:59 EAT
# Hours 05:00 – 11:59 EAT
_MORNING = [
    "Asubuhi njema tajiri wangu {business_name}! Mimi ni Mage, msaidizi wa biashara yako, leo tunashughulika na nini — mauzo, hifadhi, au unataka ushauri wa kukuza biashara?",
    "Za asubuhi bossi wa {business_name}! Mimi naitwa Mage, msaidizi wa biashara yako niko tayari, Je tuanze na mauzo ya jana au mbinu za kupata wateja wapya?",
    "Habari za asubuhi! Nimeripoti kazini mimi naitwa Mage, msaidizi wa biashara yako {business_name}, Je leo nikushauri mbinu za masoko au tuangalie hesabu?",
    "Asubuhi njema Mkubwa! Mimi naitwa Mage, msaidizi wa biashara yako, leo tuangalie mauzo ya {business_name} au jinsi ya kutumia mitandao kuleta wateja?",
    "Za asubuhi sana bossi! Mimi ni Mage, msaidizi wako, nikusaidie kuangalia mauzo au mbinu za kuuza bidhaa zilizokaa muda mrefu hapa {business_name}?",
    "Asubuhi njema Tajiri! Mimi ni Mage, msaidizi wa biashara yako {business_name}, Je unataka tuone mapato ya wiki au nikupe siri za kuongeza faida?",
    "Za asubuhi bossi! Mimi naitwa Mage, msaidizi wa biashara yako, tuanze na nini leo — hesabu za duka au ushauri wa kibiashara?",
    "Habari za asubuhi! Mimi naitwa Mage, msaidizi wako, Je tunafanya hesabu au nikupe mbinu za kutumia WhatsApp kibiashara hapa {business_name}?",
    "Asubuhi njema sana! Mimi ni Mage, msaidizi wa biashara yako, nipo hapa kukusaidia, Je unataka tuangalie mauzo au mikakati ya kukuza {business_name}?",
    "Za asubuhi tajiri wangu! Mimi ni Mage, msaidizi wako, nipo fresh leo, Je tunaanza na mauzo au ushauri wa jinsi ya kupunguza gharama za {business_name}?",
    "Asubuhi njema bossi! Nimeripoti kazini mimi ni Mage, msaidizi wa biashara yako, Je leo nikupe mbinu za ushindani au tuangalie hali ya duka {business_name}?",
    "Za asubuhi mkubwa wangu! Mimi naitwa Mage, msaidizi wa biashara yako, Je tuangalie hesabu za {business_name} au mbinu za kuvutia wateja wa kudumu?",
    "Habari za asubuhi tajiri! Mimi ni Mage, msaidizi wa biashara yako, biashara ya {business_name} leo ianze kwa hesabu au kwa ushauri wa masoko?",
    "Asubuhi njema bossi wa {business_name}! Mimi naitwa Mage, msaidizi wako, Je tuone stock ya leo au nikupe mbinu za kuongeza mauzo ya haraka?",
    "Za asubuhi safi tajiri wangu! Mimi ni Mage, msaidizi wa biashara yako, Je tunashughulika na nini leo asubuhi — data au ushauri wa kukuza {business_name}?"
]

# Hours 12:00 – 17:59 EAT
_AFTERNOON = [
    "Za mchana tajiri wangu wa {business_name}! Mimi ni Mage, msaidizi wa biashara yako, Je mchana huu tuangalie mauzo au mbinu za kupata faida zaidi?",
    "Habari za mchana! Mimi naitwa Mage, msaidizi wa biashara yako, Je biashara ya {business_name} inaendaje? Nikupe mbinu za kuuza bidhaa ghafi?",
    "Za mchana sana bossi! Nimeripoti mimi ni Mage, msaidizi wako, Je tunafanya hesabu au nikupe ushauri wa kutumia Facebook/Instagram kwa {business_name}?",
    "Mchana mzuri Mkubwa! Mimi naitwa Mage, msaidizi wa biashara yako, Je nikupe mbinu za kusimamia gharama au tuangalie mauzo ya {business_name} mchana huu?",
    "Za mchana mkubwa wangu! Mimi ni Mage, msaidizi wako nipo hapa, Je unataka nikupe ushauri wa kibiashara au tuangalie stock ya {business_name}?",
    "Habari za mchana tajiri! Mimi naitwa Mage, msaidizi wa biashara yako, Je leo tunashughulika na mauzo au mipango ya kukuza mtaji wa {business_name}?",
    "Za mchana bossi! Mimi ni Mage, msaidizi wako, Je mchana huu nikupe mbinu za kuongeza wateja hapa {business_name} au tuangalie hesabu?",
    "Mchana mzuri tajiri wangu wa {business_name}! Mimi naitwa Mage, msaidizi wako, nimesimama tayari kukupa ushauri wa kibiashara au kuangalia mauzo.",
    "Za mchana safi bossi! Mimi ni Mage, msaidizi wa biashara yako, duka linakwenda vizuri? Je nikupe mbinu za kisasa za masoko kwa ajili ya {business_name}?",
    "Habari za mchana mkubwa! Mimi naitwa Mage, msaidizi wako, Je tuanze na hesabu au ushauri wa jinsi ya kuuza bidhaa ambazo hazitoki haraka?",
    "Za mchana tajiri! Mimi ni Mage, msaidizi wako, Je biashara ya {business_name} inaendaje — tuangalie data au nikupe mbinu mpya za biashara?",
    "Mchana mzuri bossi wa {business_name}! Nimeripoti kazini mimi ni Mage, msaidizi wako, Je tuone mauzo au nikupe mbinu za huduma bora kwa wateja?",
    "Za mchana sana tajiri wangu! Mimi ni Mage, msaidizi wako, mchana huu nikupe ushauri wa kukuza {business_name} au tuangalie gharama?",
    "Habari za mchana! Mimi naitwa Mage, msaidizi wa biashara yako {business_name}, Je nikushauri jinsi ya kuongeza kipato au tuangalie hesabu za leo?",
    "Za mchana mkubwa wangu! Mimi ni Mage, msaidizi wako, Je tunashughulika na mauzo au ushauri wa jinsi ya kupanga bidhaa kuvutia wateja hapa {business_name}?"
]

# Hours 18:00 – 04:59 EAT
_EVENING = [
    "Pole na kazi tajiri wangu wa {business_name}! Mimi ni Mage, msaidizi wako, Je tumalize siku na hesabu au mipango ya kuongeza mauzo kesho?",
    "Pole na kazi bossi! Mimi naitwa Mage, msaidizi wa biashara yako, Je tuangalie hesabu za leo au nikupe ushauri wa kukuza {business_name} kwa kesho?",
    "Pole na kazi Mkubwa! Mimi ni Mage, msaidizi wako, Je biashara ya {business_name} imefanya vipi leo? Nikupe mbinu za kufunga mauzo mengi zaidi?",
    "Pole na kazi bossi wa {business_name}! Mimi naitwa Mage, nimeripoti jioni, Je tumalize na hesabu au ushauri wa jinsi ya kutumia mitandao usiku huu?",
    "Pole na kazi sana tajiri wangu! Mimi ni Mage, msaidizi wako, Je tuangalie faida ya leo au nikupe mbinu za kuuza stock iliyobaki {business_name}?",
    "Pole na kazi! Mimi naitwa Mage, msaidizi wa biashara yako, Je tufanye hesabu ya leo au nikupe mbinu za kuanza kesho kwa nguvu zaidi hapa {business_name}?",
    "Pole na kazi bossi! Mimi ni Mage, msaidizi wako, Je mauzo ya {business_name} yameendaje leo? Nikushauri mbinu za kuongeza faida?",
    "Pole na kazi mkubwa wangu! Mimi naitwa Mage, msaidizi wako, Je tunafunga siku na nini — hesabu au ushauri wa masoko kwa ajili ya {business_name}?",
    "Pole na kazi tajiri! Mimi ni Mage, msaidizi wa biashara yako, Je tuone hesabu za siku nzima au nikupe siri za mafanikio kwa biashara kama {business_name}?",
    "Pole na kazi bossi wa {business_name}! Mimi naitwa Mage, msaidizi wako, Je tuangalie mauzo au nikupe mbinu za kuhudumia wateja wengi kwa muda mfupi?",
    "Pole na kazi sana tajiri wangu! Mimi ni Mage, msaidizi wa biashara yako {business_name}, Je nikupe ushauri wa kibiashara kabla hatujafunga hesabu za leo?",
    "Pole na kazi! Jioni njema bossi, mimi ni Mage, msaidizi wako, nipo hapa kukupa ushauri au kukusaidia hesabu za kufunga siku {business_name}.",
    "Pole na kazi Mkubwa! Mimi ni Mage, msaidizi wa biashara yako, Je tunafunga siku na hesabu gani au mbinu za kuwafikia wateja wengi zaidi?",
    "Pole na kazi bossi wa {business_name}! Mimi naitwa Mage, msaidizi wako, tukague mauzo ya leo au nikupe ushauri wa jinsi ya kuendesha biashara kisasa?",
    "Pole na kazi tajiri wangu! Mimi ni Mage, msaidizi wako, Je tunafanya nini — hesabu au ushauri wa kukuza faida ya {business_name} kwa siku ya kesho?"
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_time_aware_greeting(business_name: str) -> str:
    """
    Return a randomised, time-aware Swahili greeting personalised with
    the business name.

    The current hour is read in East Africa Time (UTC+3).
    Buckets:
        05:00–11:59  →  morning  (asubuhi)
        12:00–17:59  →  afternoon (mchana)
        18:00–04:59  →  evening  (jioni) — always starts with "Pole na kazi"

    Falls back to "Bossi" when business_name is empty so a missing DB
    lookup never produces an awkward blank in the greeting string.
    """
    name = business_name.strip() if business_name else ""
    name = name or "Bossi"

    hour = datetime.now(_EAT).hour

    if 5 <= hour < 12:
        pool = _MORNING
    elif 12 <= hour < 18:
        pool = _AFTERNOON
    else:
        pool = _EVENING

    return random.choice(pool).format(business_name=name)
