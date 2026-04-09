from .bajaj_allianz import parse_bajaj_nl2
from .acko import parse_acko_nl2
from .ecgc import parse_ecgc_nl2
from .new_india import parse_new_india_nl2

PARSER_REGISTRY = {
    "bajaj_allianz": parse_bajaj_nl2,
    "acko": parse_acko_nl2,
    "ecgc": parse_ecgc_nl2,
    "new_india": parse_new_india_nl2,
}
