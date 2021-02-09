import re
import string
from typing import List

from covidbot.covid_data import TrendValue


def adapt_text(text: str, threema_format=False) -> str:
    if threema_format:
        replace_bold = replace_bold_markdown
        replace_italic = replace_italic_markdown
    else:
        replace_bold = replace_bold_unicode
        replace_italic = replace_italic_unicode

    # Make <a href=X>text</a> to text (X)
    a_pattern = re.compile("<a href=[\"']([:/\w\-.]*)[\"']>([ \w\-.]*)</a>")
    matches = a_pattern.finditer(text)
    if matches:
        for match in matches:
            text = text.replace(match.group(0), f"{match.group(2)} ({match.group(1)})")

    bold_pattern = re.compile("<b>(.*?)</b>")
    matches = bold_pattern.finditer(text)
    if matches:
        for match in matches:
            text = text.replace(match.group(0), replace_bold(match.group(1)))

    bold_pattern = re.compile("<i>(.*?)</i>")
    matches = bold_pattern.finditer(text)
    if matches:
        for match in matches:
            text = text.replace(match.group(0), replace_italic(match.group(1)))

    # Strip non bold or italic
    pattern = re.compile("<[^<]+?>")
    return pattern.sub("", text)


def replace_bold_markdown(text: str) -> str:
    # Not real markdown but Threema formatting
    text = f"*{text}*"
    # Embed links
    link_pattern = re.compile("\s?(\(http[s]?://[\w.\-]*([/\w\-.])*\))\s?")
    text = link_pattern.sub("* \g<1> *", text)

    return text.replace("**", "").strip()


'*Mehr Infos hier* (https://test.de/)  *und da* (https://test2.de/) **'


def replace_italic_markdown(text: str) -> str:
    # Not real markdown but Threema formatting
    text = f"_{text}_"
    # Embed links
    link_pattern = re.compile("\s?(\(http[s]?://[\w.\-]*([/\w\-.])*\))\s?")
    text = link_pattern.sub("_ \g<1> _", text)

    return text.replace("__", "").strip()


def replace_bold_unicode(text: str) -> str:
    # To work with signal it must be char(776) + letter for umlauts - even if it looks weird in the editor
    d = chr(776)
    bold_str = [  # Umlauts are 2 unicode characters!
        *"𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
        "𝗼" + d, "𝘂" + d, "𝗮" + d, "𝗢" + d, "𝗨" + d, "𝗔" + d]
    normal_str = [*(string.ascii_letters + string.digits + "öüäÖÜÄ")]
    return replace_by_list(text, normal_str, bold_str)


def replace_italic_unicode(text: str) -> str:
    # To work with signal it must be char(776) + letter for umlauts - even if it looks weird in the editor
    d = chr(776)
    # No italic numbers as unicode
    italic_str = [
        *"𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡",
        "𝘰" + d, "𝘶" + d, "𝘢" + d, "𝘖" + d, "𝘜" + d, "𝘈" + d]
    normal_str = [*(string.ascii_letters + "öüäÖÜÄ")]
    return replace_by_list(text, normal_str, italic_str)


def replace_by_list(text: str, search: List[str], replace: List[str]) -> str:
    # Avoid links
    link_pattern = re.compile("((http[s]?://)[\w.\-]*([/\w\-.])*)")
    matches = link_pattern.finditer(text)
    tokens = []
    if matches:
        for match in matches:
            token = f"???!!!?!?!{match.start()}"
            tokens.append((token, match.group(0)))
            text = text.replace(match.group(0), token)

    replace_list = list(zip(search, replace))

    for i in range(len(replace_list)):
        text = text.replace(replace_list[i][0], replace_list[i][1])

    for t in tokens:
        text = text.replace(t[0], t[1])
    return text


def format_data_trend(value: TrendValue) -> str:
    if value == TrendValue.UP:
        return "↗"
    elif value == TrendValue.SAME:
        return "➡"
    elif value == TrendValue.DOWN:
        return "↘"
    else:
        return ""


def format_int(number: int) -> str:
    if number is not None:
        return "{:,}".format(number).replace(",", ".")
    return "Keine Daten"


def format_float(incidence: float) -> str:
    if incidence is not None:
        return "{0:.2f}".format(float(incidence)).replace(".", ",")
    return "Keine Daten"
