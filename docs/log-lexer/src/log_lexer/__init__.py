from pygments.lexer import RegexLexer, words
from pygments.token import Whitespace, Keyword, Name, Generic, Number, Text, String


class LogLexer(RegexLexer):
    name = "log"

    tokens = {
        "root": [
            (r"\w+=", Keyword),
            (r"\n", Whitespace),
            (r"\s+", Whitespace),
            (r"^(\[(\w+)[\.\w+]*]): ", Keyword),
            (r"'(.*?)'", String),
            (words(["None", "True", "False"]), Name.Builtin.Pseudo),
            (words(["initialization", "mapping", "fetching", "translation"]), Generic.Emph),
            (r"(0x)[abcdef\d]+", Number.Hex),
            (r"\d+", Number),
            (r"\w+", Text),
        ]
    }
