from pygments.lexer import RegexLexer, words
from pygments.token import Generic, Keyword, Name, Number, String, Text, Whitespace


class LogLexer(RegexLexer):
    name = "log"

    tokens = {  # noqa: RUF012
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
