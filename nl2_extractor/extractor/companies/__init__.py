from .bajaj_allianz import parse_bajaj_nl2
from .acko import parse_acko_nl2
from .ecgc import parse_ecgc_nl2
from .new_india import parse_new_india_nl2
from .narayana_health import parse_narayana_nl2

PARSER_REGISTRY = {
    "parse_bajaj_nl2":     parse_bajaj_nl2,
    "parse_acko_nl2":      parse_acko_nl2,
    "parse_ecgc_nl2":      parse_ecgc_nl2,
    "parse_new_india_nl2": parse_new_india_nl2,
    "parse_narayana_nl2":  parse_narayana_nl2,
}
