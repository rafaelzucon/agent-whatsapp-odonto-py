"""Configurações da aplicação: dataclasses imutáveis, só com a biblioteca padrão.

A infraestrutura lê o ``config/odonto.yaml`` e as variáveis de ambiente (pydantic-settings) e o
``container.py`` converte tudo nestas dataclasses, que são o que os casos de uso conhecem.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, tzinfo
from types import MappingProxyType
from typing import Final

from odonto.aplicacao.excecoes import ConfiguracaoInvalidaError
from odonto.dominio.modelo.conversa import RegrasConversa
from odonto.dominio.modelo.enums import ChaveMensagem, EtapaConversa
from odonto.dominio.modelo.valores import Horario
from odonto.dominio.servico.agenda import DIAS_BUSCA_PADRAO, Agenda, HorarioFuncionamento
from odonto.dominio.servico.detector_sinais_alarme import PALAVRAS_ALARME_PADRAO

# Textos padrão das mensagens ao paciente (seção ``conversa.mensagens`` do YAML).
# Placeholders: NOME_CONSULTORIO, NOME_PACIENTE, DATA_HORA, ENDERECO, PRONTUARIO.
TEXTOS_PADRAO: Final[Mapping[ChaveMensagem, str]] = MappingProxyType(
    {
        ChaveMensagem.BOAS_VINDAS: (
            "Olá! Aqui é o assistente automático do NOME_CONSULTORIO. Para começar, informe o "
            "número do seu RG e a UF do órgão emissor (exemplo: 12.345.678-9 SP)."
        ),
        ChaveMensagem.PACIENTE_ENCONTRADO: (
            "Olá, NOME_PACIENTE! Que bom falar com você de novo. Conte, em poucas palavras, "
            "qual é o problema ou o motivo da consulta."
        ),
        ChaveMensagem.CONSULTA_FUTURA: (
            "Olá, NOME_PACIENTE! Você já tem uma consulta agendada para DATA_HORA. Deseja "
            "agendar outra consulta? Responda SIM ou NÃO."
        ),
        ChaveMensagem.NOVA_CONSULTA_RECUSADA: (
            "Combinado! Mantivemos sua consulta de DATA_HORA. Até lá!"
        ),
        ChaveMensagem.PEDIR_PROBLEMA: (
            "Certo! Conte, em poucas palavras, qual é o problema ou o motivo da nova consulta."
        ),
        ChaveMensagem.PEDIR_NOME: (
            "Não encontrei cadastro com esse RG. Vamos fazer agora, é rápido. Qual é o seu "
            "nome completo?"
        ),
        ChaveMensagem.PEDIR_DATA_NASCIMENTO: "Qual é a sua data de nascimento? (dd/mm/aaaa)",
        ChaveMensagem.PEDIR_RESPONSAVEL: (
            "Como o paciente é menor de idade, informe o nome completo do responsável legal."
        ),
        ChaveMensagem.PEDIR_CONSENTIMENTO: (
            "Para fazer seu cadastro e seu prontuário, o NOME_CONSULTORIO vai armazenar seus "
            "dados pessoais e de saúde com segurança, conforme a LGPD, e usar um sistema "
            "automatizado com inteligência artificial para organizar o atendimento. Você "
            "concorda? Responda SIM ou NÃO."
        ),
        ChaveMensagem.SEM_CONSENTIMENTO: (
            "Tudo bem, sua escolha foi registrada. Para agendar sem o cadastro pelo WhatsApp, "
            "ligue para o consultório ou aguarde: a equipe vai entrar em contato."
        ),
        ChaveMensagem.CADASTRO_CONCLUIDO: (
            "Cadastro concluído! Seu prontuário é o PRONTUARIO. Agora conte, em poucas palavras, "
            "qual é o problema ou o motivo da consulta."
        ),
        ChaveMensagem.EMERGENCIA: (
            "Pelo que você descreveu, pode ser uma emergência. Se houver dificuldade para "
            "respirar ou engolir, ou inchaço que se espalha pelo rosto ou pescoço, procure agora "
            "um pronto-socorro ou ligue para o SAMU (192). O consultório já foi avisado com "
            "prioridade."
        ),
        ChaveMensagem.PEDIR_DATA_HORA: (
            "Entendi. Para quando você gostaria de agendar? Pode escrever do seu jeito, por "
            "exemplo: amanhã às 14h, sexta de manhã, 25/11 às 10h."
        ),
        ChaveMensagem.HORARIO_INDISPONIVEL: (
            "Esse horário não está disponível. O horário livre mais próximo é DATA_HORA. Posso "
            "confirmar? Responda SIM, ou sugira outra data e horário."
        ),
        ChaveMensagem.SUGESTAO_HORARIO: (
            "O primeiro horário livre é DATA_HORA. Posso confirmar? Responda SIM, ou sugira "
            "outra data e horário."
        ),
        ChaveMensagem.AGENDADO: (
            "Consulta agendada para DATA_HORA, no endereço ENDERECO. Chegue com 10 minutos de "
            "antecedência e traga um documento com foto. Até lá!"
        ),
        ChaveMensagem.SEM_HORARIO: (
            "No momento não há horários livres nos próximos dias. A equipe do NOME_CONSULTORIO "
            "vai entrar em contato para combinar o melhor horário."
        ),
        ChaveMensagem.NAO_ENTENDI: "Desculpe, não entendi.",
        ChaveMensagem.ATENDIMENTO_HUMANO: (
            "Não consegui concluir o atendimento automático. A equipe do NOME_CONSULTORIO vai "
            "entrar em contato com você assim que possível."
        ),
        ChaveMensagem.PEDIR_TEXTO: (
            "Desculpe, não consigo entender esse tipo de mensagem por aqui. Por favor, responda "
            "com uma mensagem de texto."
        ),
    }
)

# Dicas curtas que acompanham o "não entendi" de cada etapa (seção ``conversa.dicas``).
DICAS_PADRAO: Final[Mapping[EtapaConversa, str]] = MappingProxyType(
    {
        EtapaConversa.AGUARDANDO_RG: (
            "Informe o número do RG e a UF do órgão emissor (exemplo: 12.345.678-9 SP)."
        ),
        EtapaConversa.AGUARDANDO_NOME: (
            "Informe o nome completo, com nome e sobrenome (exemplo: Maria da Silva)."
        ),
        EtapaConversa.AGUARDANDO_DATA_NASCIMENTO: (
            "Informe a data de nascimento no formato dd/mm/aaaa (exemplo: 15/03/1990)."
        ),
        EtapaConversa.AGUARDANDO_RESPONSAVEL: (
            "Informe o nome completo do responsável legal (exemplo: Ana Paula Souza)."
        ),
        EtapaConversa.AGUARDANDO_CONSENTIMENTO: (
            "Você concorda com o cadastro? Responda SIM ou NÃO."
        ),
        EtapaConversa.AGUARDANDO_DECISAO_NOVA_CONSULTA: (
            "Deseja agendar outra consulta? Responda SIM ou NÃO."
        ),
        EtapaConversa.AGUARDANDO_PROBLEMA: (
            "Conte, em poucas palavras, qual é o problema (exemplo: dor de dente ao mastigar)."
        ),
        EtapaConversa.AGUARDANDO_DATA_HORA: (
            "Escreva a data e o horário desejados (exemplos: amanhã às 14h, sexta de manhã, "
            "25/11 às 10h)."
        ),
        EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO: (
            "Responda SIM para confirmar o horário sugerido, ou escreva outra data e horário."
        ),
    }
)


def _converter_chaves[E: (ChaveMensagem, EtapaConversa)](
    tipo: type[E], valores: Mapping[str, str], secao: str
) -> dict[E, str]:
    convertidos: dict[E, str] = {}
    for chave, texto in valores.items():
        try:
            convertidos[tipo(chave)] = texto
        except ValueError:
            raise ConfiguracaoInvalidaError(f"Chave desconhecida em {secao}: {chave!r}.") from None
    return convertidos


@dataclass(frozen=True, slots=True)
class MensagensConversa:
    """Textos fixos enviados ao paciente e as dicas do "não entendi" por etapa."""

    textos: Mapping[ChaveMensagem, str]
    dicas: Mapping[EtapaConversa, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        vazias = [chave.value for chave in ChaveMensagem if not self.textos.get(chave, "").strip()]
        if vazias:
            raise ConfiguracaoInvalidaError(
                f"conversa.mensagens sem texto para: {', '.join(vazias)}."
            )
        object.__setattr__(self, "textos", MappingProxyType(dict(self.textos)))
        object.__setattr__(self, "dicas", MappingProxyType(dict(self.dicas)))

    @classmethod
    def padrao(cls) -> MensagensConversa:
        return cls(TEXTOS_PADRAO, DICAS_PADRAO)

    def com_alteracoes(
        self, *, textos: Mapping[str, str] | None = None, dicas: Mapping[str, str] | None = None
    ) -> MensagensConversa:
        """Sobrepõe os textos e dicas do YAML (chaves em texto) aos atuais."""
        return MensagensConversa(
            {
                **self.textos,
                **_converter_chaves(ChaveMensagem, textos or {}, "conversa.mensagens"),
            },
            {**self.dicas, **_converter_chaves(EtapaConversa, dicas or {}, "conversa.dicas")},
        )

    def texto(self, chave: ChaveMensagem) -> str:
        return self.textos[chave]

    def dica(self, etapa: EtapaConversa) -> str | None:
        return self.dicas.get(etapa)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoConversa:
    """Dados do consultório usados nas mensagens e as regras da conversa."""

    nome_consultorio: str
    endereco: str
    regras: RegrasConversa = field(default_factory=RegrasConversa)

    def __post_init__(self) -> None:
        if not self.nome_consultorio.strip():
            raise ConfiguracaoInvalidaError("Informe o nome do consultório (consultorio.nome).")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoAgenda:
    """Expediente, feriados e limite de busca. Cria a ``Agenda`` do domínio com os dados do
    banco (consultas e bloqueios) já carregados."""

    funcionamento: HorarioFuncionamento
    feriados: frozenset[date] = frozenset()
    dias_busca_maxima: int = DIAS_BUSCA_PADRAO

    @property
    def fuso(self) -> tzinfo:
        return self.funcionamento.fuso

    def criar_agenda(
        self, *, ocupados: Iterable[Horario] = (), bloqueios: Iterable[Horario] = ()
    ) -> Agenda:
        return Agenda(
            self.funcionamento,
            feriados=self.feriados,
            bloqueios=bloqueios,
            ocupados=ocupados,
            dias_busca_maxima=self.dias_busca_maxima,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoClassificacao:
    """Confiança mínima para aceitar a classificação da IA e a lista de sinais de alarme."""

    confianca_minima: float = 0.6
    palavras_alarme: tuple[str, ...] = PALAVRAS_ALARME_PADRAO

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianca_minima <= 1.0:
            raise ConfiguracaoInvalidaError(
                "classificacao.confianca_minima deve estar entre 0 e 1."
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoNotificacao:
    """Fuso usado para escrever data e hora nos avisos ao consultório."""

    fuso: tzinfo


def _variantes_numero(numero: str) -> set[str]:
    """O número só com dígitos e, se for celular do Brasil, com e sem o nono dígito (o
    ``wa_id`` de alguns celulares chega sem ele)."""
    digitos = "".join(caractere for caractere in numero if caractere.isdigit())
    variantes = {digitos} if digitos else set()
    if digitos.startswith("55") and len(digitos) == 13 and digitos[4] == "9":
        variantes.add(digitos[:4] + digitos[5:])
    elif digitos.startswith("55") and len(digitos) == 12 and digitos[4] in "6789":
        variantes.add(digitos[:4] + "9" + digitos[4:])
    return variantes


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoRecebimento:
    """Números cujas mensagens são ignoradas (ex.: o celular da recepção que recebe os avisos)."""

    numeros_ignorados: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        variantes: set[str] = set()
        for numero in self.numeros_ignorados:
            variantes |= _variantes_numero(numero)
        object.__setattr__(self, "numeros_ignorados", frozenset(variantes))

    def ignora(self, wa_id: str) -> bool:
        return not _variantes_numero(wa_id).isdisjoint(self.numeros_ignorados)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguracaoRetencao:
    """Prazo de guarda das mensagens do WhatsApp (LGPD: só o necessário)."""

    mensagens_dias: int = 90

    def __post_init__(self) -> None:
        if self.mensagens_dias < 1:
            raise ConfiguracaoInvalidaError("retencao.mensagens_dias deve ser >= 1.")
