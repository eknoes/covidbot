import re
import string


def adapt_text(text: str) -> str:
    # Replace bold with Unicode bold
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


def replace_bold(text: str) -> str:
    bold_str = [
        *"𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵𝗮̈𝘂̈𝗼̈𝗔̈𝗨̈𝗢̈ß"]
    normal_str = [*(string.ascii_letters + string.digits + "äüöÄÜÖß")]

    replace_list = list(zip(normal_str, bold_str))

    for i in range(len(replace_list)):
        text = text.replace(replace_list[i][0], replace_list[i][1])
    return text


def replace_italic(text: str) -> str:
    italic_str = [
        *"𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡0123456789𝘢̈𝘶̈𝘰̈𝘈̈𝘜̈𝘖̈ß"]
    normal_str = [*(string.ascii_letters + string.digits + "äüöÄÜÖß")]

    replace_list = list(zip(normal_str, italic_str))

    for i in range(len(replace_list)):
        text = text.replace(replace_list[i][0], replace_list[i][1])
    return text