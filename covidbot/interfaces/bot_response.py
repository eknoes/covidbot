from dataclasses import dataclass
from typing import Optional, List


@dataclass
class UserChoice:
    label: str
    callback_data: str
    alt_text: Optional[str] = None
    alt_help: Optional[str] = None


@dataclass
class BotResponse:
    message: str
    images: Optional[List[str]] = None
    choices: List[UserChoice] = None

    def __str__(self):
        if not self.choices:
            return self.message

        message = self.message + '\n\n'
        message += "<b>🙋 Mögliche Aktionen:</b>\n"
        for choice in self.choices:
            if choice.alt_text:
                message += f'• {choice.alt_text}\n'

        if self.choices[0].alt_help:
            message += f'\n{self.choices[0].alt_help}'
        else:
            message += '\nDu kannst auch einen Ort oder einen anderen Befehl senden um fortzufahren'

        return message
