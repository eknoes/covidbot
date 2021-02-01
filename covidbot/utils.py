import re
import string
from typing import List


def adapt_text(text: str, markdown=False) -> str:
    if markdown:
        replace_bold = replace_bold_markdown
        replace_italic = replace_italic_markdown
    else:
        replace_bold = replace_bold_unicode
        replace_italic = replace_italic_unicode

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

    # Make <a href=X>text</a> to text (X)
    a_pattern = re.compile("<a href=[\"']([:/\w\-.]*)[\"']>([ \w\-.]*)</a>")
    matches = a_pattern.finditer(text)
    if matches:
        for match in matches:
            text = text.replace(match.group(0), f"{match.group(2)} ({match.group(1)})")

    # Strip non bold or italic
    pattern = re.compile("<[^<]+?>")
    return pattern.sub("", text)


def replace_bold_markdown(text: str) -> str:
    return f"**{text}**"


def replace_italic_markdown(text: str) -> str:
    return f"*{text}*"


def replace_bold_unicode(text: str) -> str:
    bold_str = [  # Umlauts are 2 unicode characters!
        *"𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵",
        "̈𝗼", "̈𝘂", "̈𝗮", "̈𝗢", "̈𝗨", "̈𝗔"]
    normal_str = [*(string.ascii_letters + string.digits + "öüäÖÜÄ")]
    return replace_by_list(text, normal_str, bold_str)


def replace_italic_unicode(text: str) -> str:
    # No italic numbers as unicode
    italic_str = [
        *"𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡",
        "̈𝘢", "̈𝘶", "̈𝘰", "̈𝘈", "̈𝘜", "̈𝘖"]
    normal_str = [*(string.ascii_letters + "äüöÄÜÖ")]
    return replace_by_list(text, normal_str, italic_str)


def replace_by_list(text: str, search: List[str], replace: List[str]) -> str:
    replace_list = list(zip(search, replace))

    for i in range(len(replace_list)):
        text = text.replace(replace_list[i][0], replace_list[i][1])
    return text
