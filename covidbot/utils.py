import re
import string
from enum import Enum
from typing import List, Optional, Union, Callable

from covidbot.covid_data.models import TrendValue
from covidbot.interfaces.bot_response import BotResponse

a_pattern = re.compile("<a href=[\"\']([:/\w\-.=?&]*)[\"\']>([ \w\-.]*)</a>")
bold_pattern = re.compile("<b>(.*?)</b>")
italic_pattern = re.compile("<i>(.*?)</i>")
general_tag_pattern = re.compile("<[^<]+?>")
link_pattern = re.compile("\s?(\(http[s]?://[\w.\-]*([/\w\-.])*\))\s?")


def adapt_text(text: Union[BotResponse, str], threema_format=False, just_strip=False) -> Union[BotResponse, str]:
    response = None
    if type(text) == BotResponse:
        response = text
        text = response.message

    if threema_format:
        replace_bold = replace_bold_markdown
        replace_italic = replace_italic_markdown
    else:
        replace_bold = replace_bold_unicode
        replace_italic = replace_italic_unicode

    # Make <a href=X>text</a> to text (X)
    matches = a_pattern.finditer(text)
    if matches:
        for match in matches:
            text = text.replace(match.group(0), f"{match.group(2)} ({match.group(1)})")

    old_text = text.replace("</p>", "\n").replace("<p>", "\n")
    text = ""
    for line in old_text.splitlines():
        text += line.strip() + "\n"
    text = text.strip("\n")

    if not just_strip:
        matches = bold_pattern.finditer(text)
        if matches:
            for match in matches:
                text = text.replace(match.group(0), replace_bold(match.group(1)))

        matches = italic_pattern.finditer(text)
        if matches:
            for match in matches:
                text = text.replace(match.group(0), replace_italic(match.group(1)))

    # Strip non bold or italic
    text = general_tag_pattern.sub("", text)

    if response:
        response.message = text
        text = response
    return text


def replace_bold_markdown(text: str) -> str:
    # Not real markdown but Threema formatting
    text = f"*{text}*"
    # Embed links
    text = link_pattern.sub("* \g<1> *", text)

    return text.replace("**", "").strip()


def replace_italic_markdown(text: str) -> str:
    # Not real markdown but Threema formatting
    text = f"_{text}_"
    # Embed links
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


def replace_by_list(text: str, search: List[str], replace: List[str], ignore_links=False) -> str:
    tokens = []
    if not ignore_links:
        matches = link_pattern.finditer(text)
        if matches:
            for match in matches:
                token = f"???!!!?!?!{match.start()}"
                tokens.append((token, match.group(0)))
                text = text.replace(match.group(0), token)

    replace_list = list(zip(search, replace))

    for i in range(len(replace_list)):
        text = text.replace(replace_list[i][0], replace_list[i][1])

    if not ignore_links and tokens:
        for t in tokens:
            text = text.replace(t[0], t[1])
    return text


def format_data_trend(value: TrendValue) -> str:
    if value == TrendValue.UP:
        return " ↗"
    elif value == TrendValue.SAME:
        return " ➡"
    elif value == TrendValue.DOWN:
        return " ↘"
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


class FormattableNoun(Enum):
    NEW_INFECTIONS = 1
    DEATHS = 2
    DISTRICT = 3
    DAYS = 4
    BEDS = 5
    PERSONS = 6
    WORKING_DAYS = 7
    INFECTIONS = 8
    REPORT = 9


def format_noun(number: int, noun: FormattableNoun, hashtag: str = "") -> str:
    singular: Optional[str] = None
    plural: Optional[str] = None
    if noun == FormattableNoun.NEW_INFECTIONS:
        singular = "Neuinfektion"
        plural = "Neuinfektionen"
    elif noun == FormattableNoun.INFECTIONS:
        singular = "Infektion"
        plural = "Infektionen"
    elif noun == FormattableNoun.DEATHS:
        singular = "Todesfall"
        plural = "Todesfälle"
    elif noun == FormattableNoun.DISTRICT:
        singular = "Ort"
        plural = "Orte"
    elif noun == FormattableNoun.DAYS:
        singular = "Tag"
        plural = "Tagen"
    elif noun == FormattableNoun.WORKING_DAYS:
        singular = "Werktag"
        plural = "Werktagen"
    elif noun == FormattableNoun.BEDS:
        singular = "Bett"
        plural = "Betten"
    elif noun == FormattableNoun.REPORT:
        singular = "Bericht"
        plural = "Berichte"
    elif noun == FormattableNoun.PERSONS:
        singular = "Person"
        plural = "Personen"

    if number == 1:
        return f"{format_int(number)} {hashtag}{singular}"
    if number == 0 and noun == FormattableNoun.DAYS:
        return "heute"
    return f"{format_int(number)} {hashtag}{plural}"


def str_bytelen(s) -> int:
    return len(s.encode('utf-8'))


def split_message(message: str, max_chars: Optional[int] = None, max_bytes: Optional[int] = None) -> List[str]:
    if not max_bytes and not max_chars:
        raise ValueError("Either max_bytes or max_chars have to be set")

    len_function: Callable[[str], int] = len
    max_length = max_chars
    if max_bytes:
        len_function = str_bytelen
        max_length = max_bytes

    current_part = ""
    messages = []
    for part in message.split('\n'):
        if len_function(part) + len_function(current_part) + len_function('\n') < max_length:
            current_part += part + '\n'
        else:
            current_part.strip('\n')
            messages.append(current_part)
            current_part = part
    if current_part:
        messages.append(current_part.strip('\n'))
    return messages


class MessageType(Enum):
    CASES_GERMANY = "cases-germany"
    VACCINATION_GERMANY = "vaccinations-germany"
    ICU_GERMANY = "icu-germany"
    USER_MESSAGE = "user-message"


def message_type_name(item: MessageType) -> str:
    if item == MessageType.CASES_GERMANY:
        return "Infektionen"
    elif item == MessageType.ICU_GERMANY:
        return "Intensivbetten"
    elif item == MessageType.VACCINATION_GERMANY:
        return "Impfungen"
    return ""


def get_trend(prev_value: Optional[Union[int, float]], current_value: Optional[Union[int, float]]) -> Optional[TrendValue]:
    if not prev_value or not current_value:
        return None
    elif prev_value < 0.99 * current_value:
        return TrendValue.UP
    elif prev_value > 1.01 * current_value:
        return TrendValue.DOWN
    else:
        return TrendValue.SAME

