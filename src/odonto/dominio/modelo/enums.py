"""Enumerações do domínio (``StrEnum``: o valor é o próprio nome, legível no banco e nos logs)."""

from datetime import date, time
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class Uf(StrEnum):
    """Unidades federativas do Brasil (UF do órgão emissor do RG)."""

    AC = "AC"
    AL = "AL"
    AP = "AP"
    AM = "AM"
    BA = "BA"
    CE = "CE"
    DF = "DF"
    ES = "ES"
    GO = "GO"
    MA = "MA"
    MT = "MT"
    MS = "MS"
    MG = "MG"
    PA = "PA"
    PB = "PB"
    PR = "PR"
    PE = "PE"
    PI = "PI"
    RJ = "RJ"
    RN = "RN"
    RS = "RS"
    RO = "RO"
    RR = "RR"
    SC = "SC"
    SP = "SP"
    SE = "SE"
    TO = "TO"


class Prioridade(StrEnum):
    """Prioridade de atendimento da queixa. Use ``nivel`` para comparar, nunca ``<``."""

    EMERGENCIA = "EMERGENCIA"
    URGENCIA = "URGENCIA"
    ROTINA = "ROTINA"

    @property
    def nivel(self) -> int:
        """Quanto maior, mais urgente."""
        return _NIVEIS_PRIORIDADE[self]

    @property
    def rotulo(self) -> str:
        """Texto amigável (usado nos avisos ao consultório)."""
        return _ROTULOS_PRIORIDADE[self]

    @staticmethod
    def mais_alta(primeira: Prioridade, *outras: Prioridade) -> Prioridade:
        """Devolve a prioridade mais urgente entre as informadas."""
        return max((primeira, *outras), key=lambda prioridade: prioridade.nivel)


_NIVEIS_PRIORIDADE: Final = MappingProxyType(
    {Prioridade.EMERGENCIA: 3, Prioridade.URGENCIA: 2, Prioridade.ROTINA: 1}
)
_ROTULOS_PRIORIDADE: Final = MappingProxyType(
    {
        Prioridade.EMERGENCIA: "Emergência",
        Prioridade.URGENCIA: "Urgência",
        Prioridade.ROTINA: "Rotina",
    }
)


class EtapaConversa(StrEnum):
    """Estados da máquina de estados da conversa com o paciente."""

    AGUARDANDO_RG = "AGUARDANDO_RG"
    AGUARDANDO_NOME = "AGUARDANDO_NOME"
    AGUARDANDO_DATA_NASCIMENTO = "AGUARDANDO_DATA_NASCIMENTO"
    AGUARDANDO_RESPONSAVEL = "AGUARDANDO_RESPONSAVEL"
    AGUARDANDO_CONSENTIMENTO = "AGUARDANDO_CONSENTIMENTO"
    AGUARDANDO_DECISAO_NOVA_CONSULTA = "AGUARDANDO_DECISAO_NOVA_CONSULTA"
    AGUARDANDO_PROBLEMA = "AGUARDANDO_PROBLEMA"
    AGUARDANDO_DATA_HORA = "AGUARDANDO_DATA_HORA"
    AGUARDANDO_CONFIRMACAO_SUGESTAO = "AGUARDANDO_CONFIRMACAO_SUGESTAO"
    CONCLUIDA = "CONCLUIDA"
    ENCERRADA_SEM_CONSENTIMENTO = "ENCERRADA_SEM_CONSENTIMENTO"
    ENCAMINHADA_ATENDIMENTO_HUMANO = "ENCAMINHADA_ATENDIMENTO_HUMANO"

    @property
    def final(self) -> bool:
        """Etapas que encerram a conversa (a próxima mensagem recomeça o fluxo)."""
        return self in _ETAPAS_FINAIS


_ETAPAS_FINAIS: Final = frozenset(
    {
        EtapaConversa.CONCLUIDA,
        EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO,
        EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO,
    }
)


class StatusConsulta(StrEnum):
    AGENDADA = "AGENDADA"
    CANCELADA = "CANCELADA"
    REALIZADA = "REALIZADA"
    FALTOU = "FALTOU"


class OrigemClassificacao(StrEnum):
    """Quem classificou a queixa no catálogo."""

    IA = "IA"
    PALAVRA_CHAVE = "PALAVRA_CHAVE"
    MANUAL = "MANUAL"


class OrigemAgendamento(StrEnum):
    """Canal que criou a consulta (a recepção não gera aviso para si mesma)."""

    WHATSAPP = "WHATSAPP"
    RECEPCAO = "RECEPCAO"


class MotivoSugestao(StrEnum):
    """Por que o agente sugere um horário em vez de agendar o pedido."""

    HORARIO_INDISPONIVEL = "HORARIO_INDISPONIVEL"
    PREFERENCIA_INCOMPLETA = "PREFERENCIA_INCOMPLETA"
    PRIMEIRO_LIVRE = "PRIMEIRO_LIVRE"


class DiaSemana(StrEnum):
    SEG = "SEG"
    TER = "TER"
    QUA = "QUA"
    QUI = "QUI"
    SEX = "SEX"
    SAB = "SAB"
    DOM = "DOM"

    @staticmethod
    def de_data(dia: date) -> DiaSemana:
        return _DIAS_POR_INDICE[dia.weekday()]

    @property
    def nome(self) -> str:
        """Nome por extenso em português (ex.: "quarta-feira")."""
        return _NOMES_DIAS[self]


_DIAS_POR_INDICE: Final = tuple(DiaSemana)
_NOMES_DIAS: Final = MappingProxyType(
    {
        DiaSemana.SEG: "segunda-feira",
        DiaSemana.TER: "terça-feira",
        DiaSemana.QUA: "quarta-feira",
        DiaSemana.QUI: "quinta-feira",
        DiaSemana.SEX: "sexta-feira",
        DiaSemana.SAB: "sábado",
        DiaSemana.DOM: "domingo",
    }
)

_MEIO_DIA: Final = time(12, 0)
_SEIS_DA_TARDE: Final = time(18, 0)


class PeriodoDia(StrEnum):
    """Período do dia: manhã (antes das 12h), tarde (12h às 18h) e noite (a partir das 18h)."""

    MANHA = "MANHA"
    TARDE = "TARDE"
    NOITE = "NOITE"

    def contem(self, hora: time) -> bool:
        match self:
            case PeriodoDia.MANHA:
                return hora < _MEIO_DIA
            case PeriodoDia.TARDE:
                return _MEIO_DIA <= hora < _SEIS_DA_TARDE
            case PeriodoDia.NOITE:
                return hora >= _SEIS_DA_TARDE


class DirecaoMensagem(StrEnum):
    RECEBIDA = "RECEBIDA"
    ENVIADA = "ENVIADA"


class TipoMensagem(StrEnum):
    TEXTO = "TEXTO"
    AUDIO = "AUDIO"
    TEMPLATE = "TEMPLATE"
    OUTRO = "OUTRO"


class ChaveMensagem(StrEnum):
    """Mensagens fixas ao paciente. O valor é a chave em ``conversa.mensagens`` do YAML."""

    BOAS_VINDAS = "boas_vindas"
    PACIENTE_ENCONTRADO = "paciente_encontrado"
    CONSULTA_FUTURA = "consulta_futura"
    NOVA_CONSULTA_RECUSADA = "nova_consulta_recusada"
    PEDIR_PROBLEMA = "pedir_problema"
    PEDIR_NOME = "pedir_nome"
    PEDIR_DATA_NASCIMENTO = "pedir_data_nascimento"
    PEDIR_RESPONSAVEL = "pedir_responsavel"
    PEDIR_CONSENTIMENTO = "pedir_consentimento"
    SEM_CONSENTIMENTO = "sem_consentimento"
    CADASTRO_CONCLUIDO = "cadastro_concluido"
    EMERGENCIA = "emergencia"
    PEDIR_DATA_HORA = "pedir_data_hora"
    HORARIO_INDISPONIVEL = "horario_indisponivel"
    SUGESTAO_HORARIO = "sugestao_horario"
    AGENDADO = "agendado"
    SEM_HORARIO = "sem_horario"
    NAO_ENTENDI = "nao_entendi"
    ATENDIMENTO_HUMANO = "atendimento_humano"
    PEDIR_TEXTO = "pedir_texto"
