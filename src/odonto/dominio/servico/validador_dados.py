"""Validação das respostas do paciente: RG + UF, nome completo, nascimento e SIM/NÃO."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Final

from odonto.dominio.excecoes import DadoInvalidoError
from odonto.dominio.modelo.enums import Uf
from odonto.dominio.modelo.paciente import validar_nome_completo
from odonto.dominio.modelo.valores import IDADE_MAXIMA, DocumentoRg, idade_em
from odonto.dominio.servico.texto import MESES, normalizar, remover_acentos

# --- RG + UF -------------------------------------------------------------------------------

_REGEX_NUMERO_RG: Final = re.compile(r"(?<!\w)\d(?:[.\-]?\d|\s\d)*(?:[.\-\s]?[xX])?(?!\w)")
_REGEX_LETRA_DIGITO: Final = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-WYZa-wyz])")
_REGEX_TOKEN_LETRAS: Final = re.compile(r"[A-Za-z]+")
_REGEX_SEPARADORES_RG: Final = re.compile(r"[\s.\-]")
_REGEX_PARA_ACENTUADO: Final = re.compile(r"(?<!\w)pará(?!\w)")
_TAMANHO_MINIMO_RG: Final = 5
_TAMANHO_MAXIMO_RG: Final = 14

_UFS: Final = frozenset(uf.value for uf in Uf)
# Siglas que também são palavras comuns ("se", "pé", "má"...): só valem se nada melhor aparecer.
_UFS_AMBIGUAS: Final = frozenset({Uf.SE, Uf.TO, Uf.ES, Uf.PE, Uf.MA, Uf.PA, Uf.AL, Uf.AM, Uf.CE})
# Órgãos emissores escritos colados à UF (ex.: "SSPSP", "DETRANRJ").
_ORGAOS_EMISSORES: Final = (
    "SSP",
    "SESP",
    "SDS",
    "SJS",
    "SJTC",
    "SEJUSP",
    "SESDC",
    "SSPDS",
    "DETRAN",
    "DGPC",
    "PC",
    "IFP",
    "IGP",
    "IIRGD",
    "POLITEC",
    "SPTC",
    "SEPC",
    "ITEP",
    "DIC",
    "SEDS",
    "PTC",
)
# Nomes por extenso (os mais longos primeiro, para "mato grosso do sul" vencer "mato grosso").
_NOMES_ESTADOS: Final = (
    ("mato grosso do sul", Uf.MS),
    ("rio grande do norte", Uf.RN),
    ("rio grande do sul", Uf.RS),
    ("distrito federal", Uf.DF),
    ("espirito santo", Uf.ES),
    ("rio de janeiro", Uf.RJ),
    ("santa catarina", Uf.SC),
    ("minas gerais", Uf.MG),
    ("mato grosso", Uf.MT),
    ("pernambuco", Uf.PE),
    ("sao paulo", Uf.SP),
    ("tocantins", Uf.TO),
    ("brasilia", Uf.DF),
    ("maranhao", Uf.MA),
    ("rondonia", Uf.RO),
    ("alagoas", Uf.AL),
    ("amazonas", Uf.AM),
    ("paraiba", Uf.PB),
    ("roraima", Uf.RR),
    ("sergipe", Uf.SE),
    ("parana", Uf.PR),
    ("amapa", Uf.AP),
    ("bahia", Uf.BA),
    ("ceara", Uf.CE),
    ("goias", Uf.GO),
    ("minas", Uf.MG),
    ("piaui", Uf.PI),
    ("acre", Uf.AC),
)
_PADROES_ESTADOS: Final = tuple(
    (re.compile(rf"(?<![a-z]){r'\s+'.join(nome.split())}(?![a-z])"), uf)
    for nome, uf in _NOMES_ESTADOS
)


@dataclass(frozen=True, slots=True)
class _CandidatoUf:
    posicao: int
    uf: Uf
    forte: bool


def _numero_rg(texto: str) -> tuple[str, int, int]:
    """Primeiro número com tamanho de RG: (número normalizado, início, fim)."""
    for achado in _REGEX_NUMERO_RG.finditer(texto):
        numero = _REGEX_SEPARADORES_RG.sub("", achado.group()).upper()
        if _TAMANHO_MINIMO_RG <= len(numero) <= _TAMANHO_MAXIMO_RG:
            return numero, achado.start(), achado.end()
    raise DadoInvalidoError(
        "rg", "Informe o número do RG (de 5 a 14 caracteres) e a UF do órgão emissor."
    )


def _uf_do_token(token: str, texto_todo_maiusculo: bool) -> tuple[Uf, bool] | None:
    """UF citada no token e se ela é "forte" (sem ambiguidade com palavras comuns)."""
    sigla = token.upper()
    if len(sigla) == 2 and sigla in _UFS:
        uf = Uf(sigla)
        destacada = token.isupper() and not texto_todo_maiusculo
        return uf, destacada or uf not in _UFS_AMBIGUAS
    for orgao in _ORGAOS_EMISSORES:
        if sigla.startswith(orgao) and sigla.removeprefix(orgao) in _UFS:
            return Uf(sigla.removeprefix(orgao)), True
    return None


def _candidatos_uf(base: str, original: str, inicio: int, fim: int) -> list[_CandidatoUf]:
    texto_todo_maiusculo = not any(caractere.islower() for caractere in base)
    candidatos: list[_CandidatoUf] = []
    for token in _REGEX_TOKEN_LETRAS.finditer(base):
        if inicio <= token.start() < fim:
            continue
        if (achado := _uf_do_token(token.group(), texto_todo_maiusculo)) is not None:
            uf, forte = achado
            candidatos.append(_CandidatoUf(token.start(), uf, forte))
    minusculo = base.casefold()
    ocupados: list[tuple[int, int]] = []
    for padrao, uf in _PADROES_ESTADOS:
        for estado in padrao.finditer(minusculo):
            if any(estado.start() < f and i < estado.end() for i, f in ocupados):
                continue
            ocupados.append(estado.span())
            candidatos.append(_CandidatoUf(estado.start(), uf, forte=True))
    candidatos.extend(
        _CandidatoUf(para.start(), Uf.PA, forte=True)
        for para in _REGEX_PARA_ACENTUADO.finditer(original.casefold())
    )
    return candidatos


def _escolher_uf(candidatos: list[_CandidatoUf], inicio: int, fim: int) -> Uf:
    """Prefere a UF depois do número; siglas ambíguas só se não houver outra opção."""
    for forte in (True, False):
        depois = [c for c in candidatos if c.forte is forte and c.posicao >= fim]
        if depois:
            return min(depois, key=lambda c: c.posicao).uf
        antes = [c for c in candidatos if c.forte is forte and c.posicao < inicio]
        if antes:
            return max(antes, key=lambda c: c.posicao).uf
    raise DadoInvalidoError(
        "uf", "Informe também a UF do órgão emissor do RG (exemplo: 12.345.678-9 SP)."
    )


# --- Nome completo ---------------------------------------------------------------------------

_PREFIXOS_NOME: Final = (
    r"(?:(?:o|a)\s+)?(?:(?:meu|seu|o)\s+)?nome\s+(?:completo\s+)?"
    r"(?:d[oa]\s+(?:respons[aá]vel|paciente)\s+)?(?:[eé]|eh)\b",
    r"(?:eu\s+)?me\s+chamo\b",
    r"(?:eu\s+)?sou\b(?:\s+(?:o|a)\b)?",
    r"(?:(?:o|a)\s+)?respons[aá]vel(?:\s+legal)?(?:\s+(?:[eé]|eh)\b)?",
    r"(?:(?:o|meu)\s+)?nome(?:\s+completo)?\b",
)
_REGEX_PREFIXO_NOME: Final = re.compile(
    rf"^\s*(?:{'|'.join(_PREFIXOS_NOME)})\s*[:\-–,]?\s*", re.IGNORECASE
)
_CARACTERES_EXTRAS_NOME: Final = frozenset(" '’-.")
_PARTICULAS_NOME: Final = frozenset({"da", "das", "de", "do", "dos", "e", "di", "du"})
_MAXIMO_PALAVRAS_NOME: Final = 10
# Respostas que passariam como "duas palavras", mas claramente não são nomes.
_PALAVRAS_QUE_NAO_SAO_NOME: Final = frozenset(
    {
        "oi",
        "ola",
        "bom",
        "boa",
        "dia",
        "tarde",
        "noite",
        "sim",
        "nao",
        "quero",
        "marcar",
        "agendar",
        "consulta",
        "dente",
        "dentes",
        "dor",
        "obrigado",
        "obrigada",
        "sei",
        "rg",
        "cpf",
        "nome",
        "meu",
        "minha",
        "tudo",
        "bem",
        "por",
        "favor",
        "ok",
    }
)
_REGEX_INICIAL_PALAVRA: Final = re.compile(r"(^|[-'’])(\w)")
# Partícula elidida no meio do nome ("Maria d'Ávila", "Joana d’Arc"): o "d" fica minúsculo.
_REGEX_PARTICULA_ELIDIDA: Final = re.compile(r"^d['’](?=\w)", re.IGNORECASE)


def _capitalizar(nome: str) -> str:
    """Capitaliza nomes digitados todo em minúsculas ou maiúsculas ("maria da silva")."""
    palavras_nome = nome.split(" ")
    if not nome.isupper() and all(
        p[:1].isupper()
        or p.casefold() in _PARTICULAS_NOME
        or (indice > 0 and _REGEX_PARTICULA_ELIDIDA.match(p) is not None)
        for indice, p in enumerate(palavras_nome)
    ):
        return nome
    resultado = []
    for indice, palavra in enumerate(palavras_nome):
        minuscula = palavra.lower()
        if indice > 0 and minuscula in _PARTICULAS_NOME:
            resultado.append(minuscula)
            continue
        capitalizada = _REGEX_INICIAL_PALAVRA.sub(
            lambda m: m.group(1) + m.group(2).upper(), minuscula
        )
        if indice > 0 and _REGEX_PARTICULA_ELIDIDA.match(capitalizada):
            capitalizada = "d" + capitalizada[1:]
        resultado.append(capitalizada)
    return " ".join(resultado)


# --- Data de nascimento --------------------------------------------------------------------

_REGEX_DATA_NUMERICA: Final = re.compile(
    r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})(?!\d)"
)
_REGEX_DATA_EXTENSO: Final = re.compile(
    r"(?<!\d)(\d{1,2})\s*o?\s+(?:de\s+)?([a-z]+)[.,]?\s+(?:de\s+)?(\d{4})(?!\d)"
)
_REGEX_DATA_COMPACTA: Final = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{4})(?!\d)")


def _ano_completo(ano: str, hoje: date) -> int:
    if len(ano) == 4:
        return int(ano)
    seculo_atual = 2000 + int(ano)
    return seculo_atual if seculo_atual <= hoje.year else 1900 + int(ano)


def _partes_data(normalizado: str, hoje: date) -> tuple[int, int, int] | None:
    if achado := _REGEX_DATA_NUMERICA.search(normalizado):
        dia, mes, ano = achado.groups()
        return int(dia), int(mes), _ano_completo(ano, hoje)
    for achado in _REGEX_DATA_EXTENSO.finditer(normalizado):
        dia, nome_mes, ano = achado.groups()
        if nome_mes in MESES:
            return int(dia), MESES[nome_mes], int(ano)
    if achado := _REGEX_DATA_COMPACTA.search(normalizado):
        dia, mes, ano = achado.groups()
        return int(dia), int(mes), int(ano)
    return None


# --- SIM / NÃO e cortesia -------------------------------------------------------------------

_POSITIVAS: Final = frozenset(
    {
        "sim",
        "s",
        "concordo",
        "aceito",
        "autorizo",
        "confirmo",
        "confirmado",
        "confirmada",
        "confirma",
        "confirmar",
        "claro",
        "certeza",
        "ok",
        "okay",
        "isso",
        "certo",
        "positivo",
        "afirmativo",
        "pode",
        "quero",
        "beleza",
        "blz",
        "perfeito",
        "combinado",
        "fechado",
        "otimo",
        "acordo",
        "uhum",
        "aham",
        "bora",
        "vamos",
        "yes",
    }
)
_NEGATIVAS: Final = frozenset(
    {"nao", "n", "discordo", "recuso", "negativo", "nem", "nunca", "jamais"}
)
_NEUTRAS: Final = frozenset(
    {
        "eu",
        "com",
        "por",
        "favor",
        "obrigado",
        "obrigada",
        "ser",
        "posso",
        "consigo",
        "prefiro",
        "estou",
        "de",
        "do",
        "da",
        "os",
        "as",
        "o",
        "a",
        "e",
        "que",
        "termos",
        "termo",
        "tudo",
        "bem",
        "ta",
        "esta",
        "sera",
        "seria",
        "agora",
        "entao",
        "marcar",
        "marca",
        "agendar",
        "agenda",
        "esse",
        "este",
        "horario",
        "mesmo",
        "sem",
        "duvida",
        "problema",
        "problemas",
        "muito",
        "plenamente",
        "totalmente",
        "perfeitamente",
        "completamente",
        "tambem",
    }
)
# "Sem dúvida" e "sem problema" são concordância, embora "sem" sozinho não seja.
_EXPRESSOES_SIM: Final = re.compile(r"\bsem\s+(?:duvidas?|problemas?)\b")
_VOCABULARIO_SIM_NAO: Final = _POSITIVAS | _NEGATIVAS | _NEUTRAS
_EMOJIS_SIM: Final = frozenset("👍👌✅✔☑🆗")
_EMOJIS_NAO: Final = frozenset("👎❌✖🚫")
_MODIFICADORES_EMOJI: Final = frozenset(
    {"\ufe0e", "\ufe0f", "\U0001f3fb", "\U0001f3fc", "\U0001f3fd", "\U0001f3fe", "\U0001f3ff"}
)

_GRATIDAO: Final = frozenset(
    {
        "obrigado",
        "obrigada",
        "obg",
        "obgd",
        "obgda",
        "brigado",
        "brigada",
        "valeu",
        "vlw",
        "agradeco",
        "grato",
        "grata",
        "gratidao",
        "thanks",
    }
)
_CONFIRMACOES_CURTAS: Final = frozenset(
    {
        "ok",
        "okay",
        "okey",
        "certo",
        "beleza",
        "blz",
        "combinado",
        "perfeito",
        "otimo",
        "show",
        "entendi",
        "top",
        "joia",
        "ta",
        "tchau",
        "tchauzinho",
        "falou",
        "flw",
        "fechado",
    }
)
# Despedidas ("até mais", "até amanhã", "até sexta", "até dia 20") contam como confirmação curta.
_DESPEDIDAS: Final = re.compile(
    r"\bate\s+(?:mais|logo|la|breve|amanha|a\s+proxima|o\s+dia\s+\d{1,2}|dia\s+\d{1,2}"
    r"|(?:segunda|terca|quarta|quinta|sexta)(?:-feira)?|sabado|domingo)\b"
)
_LIGACAO_CORTESIA: Final = frozenset(
    {
        "muito",
        "muitissimo",
        "mto",
        "mt",
        "a",
        "o",
        "e",
        "de",
        "pela",
        "pelo",
        "atencao",
        "ajuda",
        "deus",
        "abencoe",
        "tudo",
        "td",
        "bem",
        "voce",
        "voces",
        "vc",
        "vcs",
        "sim",
        "abraco",
        "abracos",
        "bom",
        "boa",
        "dia",
        "tarde",
        "noite",
        "nada",
        "entao",
        "ate",
        "logo",
        "mais",
        "la",
        "aguardo",
        "pra",
        "por",
        "proxima",
    }
)
_REGEX_PALAVRAS_LATINAS: Final = re.compile(r"[a-z]+")


def _resposta_por_emoji(texto: str) -> bool | None:
    simbolos = {c for c in texto if not c.isspace() and c not in _MODIFICADORES_EMOJI}
    if simbolos and simbolos <= _EMOJIS_SIM:
        return True
    if simbolos and simbolos <= _EMOJIS_NAO:
        return False
    return None


class ValidadorDados:
    """Interpreta e valida o que o paciente digitou. Erros viram ``DadoInvalidoError``."""

    @staticmethod
    def rg(texto: str) -> DocumentoRg:
        """RG + UF em formatos livres: "12.345.678-9 SP", "MG-12.345.678", "1234567X ssp/rj"."""
        preparado = _REGEX_LETRA_DIGITO.sub(" ", unicodedata.normalize("NFC", texto))
        base = remover_acentos(preparado)
        numero, inicio, fim = _numero_rg(base)
        uf = _escolher_uf(_candidatos_uf(base, preparado, inicio, fim), inicio, fim)
        return DocumentoRg.criar(numero, uf.value)

    @staticmethod
    def nome_completo(texto: str, campo: str = "nome") -> str:
        """Nome e sobrenome, sem números ou símbolos; tira prefixos como "meu nome é"."""
        sem_prefixo = _REGEX_PREFIXO_NOME.sub("", texto.strip(), count=1)
        nome = " ".join(sem_prefixo.split()).strip(" .!")
        if not nome or any(
            not (caractere.isalpha() or caractere in _CARACTERES_EXTRAS_NOME) for caractere in nome
        ):
            raise DadoInvalidoError(campo, "Informe só o nome completo, sem números ou símbolos.")
        nome = validar_nome_completo(nome, campo)
        palavras_normalizadas = normalizar(nome).replace(".", " ").split()
        if len(palavras_normalizadas) > _MAXIMO_PALAVRAS_NOME or any(
            palavra in _PALAVRAS_QUE_NAO_SAO_NOME for palavra in palavras_normalizadas
        ):
            raise DadoInvalidoError(campo, "Informe o nome completo (nome e sobrenome).")
        return _capitalizar(nome)

    @staticmethod
    def data_nascimento(texto: str, hoje: date) -> date:
        """Aceita dd/mm/aaaa (também com "-" ou "."), "15 de março de 1990" e ddmmaaaa."""
        partes = _partes_data(normalizar(texto), hoje)
        if partes is None:
            raise DadoInvalidoError(
                "data_nascimento", "Informe a data de nascimento no formato dd/mm/aaaa."
            )
        dia, mes, ano = partes
        try:
            nascimento = date(ano, mes, dia)
        except ValueError:
            raise DadoInvalidoError("data_nascimento", "Essa data não existe.") from None
        if nascimento > hoje:
            raise DadoInvalidoError(
                "data_nascimento", "A data de nascimento não pode estar no futuro."
            )
        if idade_em(nascimento, hoje) > IDADE_MAXIMA:
            raise DadoInvalidoError("data_nascimento", "Confira o ano de nascimento.")
        return nascimento

    @staticmethod
    def sim_nao(texto: str) -> bool | None:
        """``True`` para SIM, ``False`` para NÃO e ``None`` se a resposta não for clara.

        Compara sem acentos e sem diferenciar maiúsculas. Qualquer palavra fora do vocabulário
        (ou número) torna a resposta ambígua, para não confundir "não posso amanhã" com "não".
        """
        por_emoji = _resposta_por_emoji(texto)
        if por_emoji is not None:
            return por_emoji
        normalizado = _EXPRESSOES_SIM.sub("sim", normalizar(texto))
        tokens = _REGEX_PALAVRAS_LATINAS.findall(normalizado)
        if (
            not tokens
            or any(caractere.isdigit() for caractere in normalizado)
            or any(token not in _VOCABULARIO_SIM_NAO for token in tokens)
        ):
            return None
        if any(token in _NEGATIVAS for token in tokens):
            return False
        if any(token in _POSITIVAS for token in tokens):
            return True
        return None

    @staticmethod
    def e_cortesia(texto: str) -> bool:
        """Agradecimento ou confirmação curta ("obrigado!", "ok, até lá", "👍🙏")."""
        normalizado = _DESPEDIDAS.sub("tchau", normalizar(texto))
        if not normalizado:
            return False
        tokens = re.findall(r"\w+", normalizado)
        if not tokens:
            return True
        vocabulario = _GRATIDAO | _CONFIRMACOES_CURTAS | _LIGACAO_CORTESIA
        return all(token in vocabulario for token in tokens) and any(
            token in _GRATIDAO or token in _CONFIRMACOES_CURTAS for token in tokens
        )
