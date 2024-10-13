class FG:
    """
    ANSI escape codes for terminal foreground colors.
    """

    black = "\033[30m"
    darkgray = "\033[90m"
    lightgray = "\033[37m"
    white = "\033[97m"
    red = "\033[31m"
    orange = "\033[33m"
    yellow = "\033[93m"
    green = "\033[32m"
    blue = "\033[34m"
    cyan = "\033[36m"
    purple = "\033[35m"
    magenta = "\033[95m"
    lightred = "\033[91m"
    lightgreen = "\033[92m"
    lightblue = "\033[94m"
    lightcyan = "\033[96m"

class BG:
    """
    ANSI escape codes for terminal background colors.
    """

    black = "\033[40m"
    darkgray = "\033[100m"
    lightgray = "\033[47m"
    white = "\033[107m"
    red = "\033[41m"
    orange = "\033[43m"
    yellow = "\033[103m"
    green = "\033[42m"
    blue = "\033[44m"
    cyan = "\033[46m"
    purple = "\033[45m"
    magenta = "\033[105m"
    lightred = "\033[101m"
    lightgreen = "\033[102m"
    lightblue = "\033[104m"
    lightcyan = "\033[106m"

RESET = "\033[0m"

def info(message: str) -> None:
    """ Log information message. """

    print(f"{FG.lightcyan}[INFO]{RESET} {message}")

def fail(message: str) -> None:
    """ Log fail/error message. """

    print(f"{FG.lightred}[FAIL]{RESET} {message}")

def done(message: str) -> None:
    """ Log done/success message. """

    print(f"{FG.lightgreen}[DONE]{RESET} {message}")