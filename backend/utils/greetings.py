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
# Must contain "Za asubuhi" OR "Asubuhi njema"
_MORNING = [
    "Asubuhi njema bossi wa {business_name}! Mimi ni Mage, leo tunashughulika na nini — mauzo au hifadhi?",
    "Za asubuhi {business_name}! Mage yuko tayari, tuanze na hesabu au bidhaa za leo?",
    "Habari za asubuhi {business_name}! Mage ameripoti — tunafanya nini leo asubuhi?",
    "Asubuhi njema mkubwa wa {business_name}! Mage hapa, duka linafungua vizuri — tunaangalia nini leo?",
    "Za asubuhi sana bossi {business_name}! Mage hapa, sema tu — mauzo, gharama, au hifadhi?",
    "Asubuhi njema {business_name}! Mage amewasili mapema, tuone bidhaa au mapato ya wiki?",
    "Za asubuhi bossi! {business_name} imeingia vizuri, Mage yuko — tuanze na nini leo?",
    "Habari asubuhi {business_name}! Mage amesimama tayari, tunafanya hesabu au tunaongeza bidhaa leo?",
    "Asubuhi njema sana {business_name}! Mage hapa kukusaidia, unataka tuangalie nini kwanza?",
    "Za asubuhi {business_name}! Mage yuko fresh leo asubuhi, tunaanza na mauzo au gharama?",
    "Asubuhi njema bossi {business_name}! Mage ameripoti, siku mpya — tunashughulika nini leo?",
    "Za asubuhi mkubwa {business_name}! Mage hapa, biashara inaanza — tunaangalia nini kwanza?",
    "Habari za asubuhi bossi! {business_name} leo inafanya nini? Mage yuko, niambie tuanze.",
    "Asubuhi njema {business_name}! Mage amesha ingia, tuone stock au mauzo ya jana?",
    "Za asubuhi safi bossi wa {business_name}! Mage yuko hapa, tunafanya kazi gani leo asubuhi?",
]

# Hours 12:00 – 17:59 EAT
# Must contain "Za mchana" OR "Mchana mzuri"
_AFTERNOON = [
    "Za mchana bossi wa {business_name}! Mage hapa mchana huu, tunashughulika na nini sasa?",
    "Habari za mchana {business_name}! Mage yuko, biashara inakwenda vipi — tunaendelea na nini?",
    "Za mchana sana {business_name}! Mage ameripoti, mchana huu tunafanya hesabu au bidhaa?",
    "Mchana mzuri bossi! {business_name} leo inakwenda vipi? Mage hapa, sema tunafanya nini.",
    "Za mchana mkubwa wa {business_name}! Mage hapa tayari, unataka nini mchana huu?",
    "Habari mchana {business_name}! Mage yuko ofisini, tunaangalia mauzo au hifadhi sasa?",
    "Za mchana bossi {business_name}! Mage hapa, mchana huu tunashughulika na nini pamoja?",
    "Mchana mzuri {business_name}! Mage amesimama tayari, tunafanya hesabu au tunaona mauzo?",
    "Za mchana safi {business_name}! Mage hapa, duka linakwenda vizuri — tunaangalia nini leo?",
    "Habari za mchana mkubwa! {business_name} inakuwaje leo? Mage yuko, tuanze na nini?",
    "Za mchana {business_name}! Mage hapa mchana huu, biashara inaendaje — tuangalie pamoja?",
    "Mchana mzuri bossi wa {business_name}! Mage ameripoti, unataka tuone mauzo au hifadhi?",
    "Za mchana sana bossi {business_name}! Mage hapa, mchana huu tufanye kazi gani pamoja?",
    "Habari mchana {business_name}! Mage yuko, sema tu — tunafanya nini sasa mchana huu?",
    "Za mchana mkubwa {business_name}! Mage amewasili, tunashughulika na mauzo au gharama?",
]

# Hours 18:00 – 04:59 EAT
# EVERY greeting in this bucket MUST start with "Pole na kazi"
_EVENING = [
    "Pole na kazi bossi wa {business_name}! Mage hapa jioni hii, tumalize siku na nini?",
    "Pole na kazi {business_name}! Mage yuko, siku imekwenda vizuri? Tuangalie hesabu za leo.",
    "Pole na kazi mkubwa! {business_name} leo imefanya vipi? Mage hapa, tuone pamoja jioni.",
    "Pole na kazi bossi {business_name}! Mage ameripoti jioni, tumalize na hesabu au hifadhi?",
    "Pole na kazi sana {business_name}! Mage hapa kukusaidia kufunga siku, tunaangalia nini?",
    "Pole na kazi {business_name}! Siku nzuri? Mage yuko jioni hii, tufanye hesabu ya leo.",
    "Pole na kazi bossi wa {business_name}! Mage hapa jioni, mauzo ya leo yamekwenda vipi?",
    "Pole na kazi mkubwa wa {business_name}! Mage yuko, jioni hii tunafunga na nini pamoja?",
    "Pole na kazi {business_name}! Mage amesimama pamoja nawe, tuone hesabu za siku nzima.",
    "Pole na kazi bossi {business_name}! Mage hapa jioni hii, bidhaa au mauzo — tunaangalia nini?",
    "Pole na kazi sana bossi! {business_name} leo imefanya kazi nzuri? Mage yuko, sema.",
    "Pole na kazi {business_name}! Jioni njema, Mage hapa kukusaidia kufunga siku vizuri.",
    "Pole na kazi mkubwa {business_name}! Mage amesha ingia, tunafunga siku na hesabu gani?",
    "Pole na kazi bossi wa {business_name}! Mage yuko jioni hii, tukague mauzo ya leo pamoja.",
    "Pole na kazi {business_name}! Mage hapa jioni, tunafanya nini — hesabu au hifadhi ya leo?",
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
