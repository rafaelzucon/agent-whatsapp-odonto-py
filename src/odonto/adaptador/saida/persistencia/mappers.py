"""Mappers explícitos domínio ↔ ORM. Só convertem; nenhuma regra de negócio aqui."""

import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID

from odonto.adaptador.saida.persistencia.orm import (
    BloqueioAgendaOrm,
    ConsultaOrm,
    ConversaOrm,
    MensagemOrm,
    PacienteOrm,
    PacienteTelefoneOrm,
    ProblemaOdontologicoOrm,
    ProntuarioOrm,
    QueixaRelatadaOrm,
)
from odonto.dominio.modelo.bloqueio import BloqueioAgenda
from odonto.dominio.modelo.consulta import Consulta
from odonto.dominio.modelo.conversa import Conversa, DadosConversa
from odonto.dominio.modelo.enums import (
    DirecaoMensagem,
    EtapaConversa,
    OrigemAgendamento,
    OrigemClassificacao,
    Prioridade,
    StatusConsulta,
    TipoMensagem,
    Uf,
)
from odonto.dominio.modelo.mensagem import Mensagem
from odonto.dominio.modelo.paciente import Paciente
from odonto.dominio.modelo.problema import ProblemaOdontologico
from odonto.dominio.modelo.prontuario import Prontuario, QueixaRelatada
from odonto.dominio.modelo.valores import DocumentoRg, Horario, NumeroProntuario, WaId

# --- Paciente ---------------------------------------------------------------------------------


def paciente_para_orm(paciente: Paciente, *, rg_hash: str) -> PacienteOrm:
    orm = PacienteOrm(id=paciente.id, rg_hash=rg_hash, telefones=[])
    atualizar_paciente_orm(orm, paciente)
    return orm


def atualizar_paciente_orm(orm: PacienteOrm, paciente: Paciente) -> None:
    orm.rg_cifrado = json.dumps([paciente.documento.numero, paciente.documento.uf.value])
    orm.nome_cifrado = paciente.nome
    orm.data_nascimento_cifrada = paciente.data_nascimento.isoformat()
    orm.responsavel_cifrado = paciente.responsavel
    orm.consentimento_lgpd = paciente.consentimento_lgpd
    orm.consentimento_em = paciente.consentimento_em
    orm.cadastrado_em = paciente.cadastrado_em
    existentes = {telefone.wa_id for telefone in orm.telefones}
    for wa_id in paciente.telefones:
        if wa_id.valor not in existentes:
            orm.telefones.append(PacienteTelefoneOrm(wa_id=wa_id.valor))


def paciente_do_orm(orm: PacienteOrm) -> Paciente:
    numero, uf = json.loads(orm.rg_cifrado)
    return Paciente(
        id=orm.id,
        documento=DocumentoRg(numero, Uf(uf)),
        nome=orm.nome_cifrado,
        data_nascimento=date.fromisoformat(orm.data_nascimento_cifrada),
        responsavel=orm.responsavel_cifrado,
        telefones=[WaId(telefone.wa_id) for telefone in orm.telefones],
        consentimento_lgpd=orm.consentimento_lgpd,
        consentimento_em=orm.consentimento_em,
        cadastrado_em=orm.cadastrado_em,
    )


# --- Catálogo ---------------------------------------------------------------------------------


def problema_do_orm(orm: ProblemaOdontologicoOrm) -> ProblemaOdontologico:
    return ProblemaOdontologico(
        codigo=orm.codigo,
        nome=orm.nome,
        descricao=orm.descricao,
        especialidade=orm.especialidade,
        prioridade=Prioridade(orm.prioridade),
        cid10=orm.cid10,
        palavras_chave=tuple(orm.palavras_chave),
        ativo=orm.ativo,
    )


# --- Prontuário -------------------------------------------------------------------------------


def prontuario_para_orm(prontuario: Prontuario) -> ProntuarioOrm:
    orm = ProntuarioOrm(
        id=prontuario.id,
        paciente_id=prontuario.paciente_id,
        numero=prontuario.numero.sequencial,
        aberto_em=prontuario.aberto_em,
        queixas=[],
    )
    atualizar_prontuario_orm(orm, prontuario)
    return orm


def atualizar_prontuario_orm(orm: ProntuarioOrm, prontuario: Prontuario) -> None:
    """Acrescenta as queixas novas e atualiza as existentes (reclassificação, consulta)."""
    por_id = {queixa.id: queixa for queixa in orm.queixas}
    for queixa in prontuario.queixas:
        queixa_orm = por_id.get(queixa.id)
        if queixa_orm is None:
            queixa_orm = QueixaRelatadaOrm(id=queixa.id, prontuario_id=prontuario.id)
            orm.queixas.append(queixa_orm)
        queixa_orm.texto_cifrado = queixa.texto_original
        queixa_orm.problema_codigo = queixa.problema.codigo
        queixa_orm.prioridade = queixa.prioridade.value
        queixa_orm.confianca = queixa.confianca
        queixa_orm.origem = queixa.origem.value
        queixa_orm.sintomas_cifrados = json.dumps(list(queixa.sintomas), ensure_ascii=False)
        queixa_orm.registrada_em = queixa.registrada_em
        queixa_orm.reclassificada_em = queixa.reclassificada_em
        queixa_orm.consulta_id = queixa.consulta_id


def prontuario_do_orm(orm: ProntuarioOrm) -> Prontuario:
    return Prontuario(
        id=orm.id,
        numero=NumeroProntuario(orm.numero),
        paciente_id=orm.paciente_id,
        aberto_em=orm.aberto_em,
        queixas=[_queixa_do_orm(queixa) for queixa in orm.queixas],
    )


def _queixa_do_orm(orm: QueixaRelatadaOrm) -> QueixaRelatada:
    return QueixaRelatada(
        id=orm.id,
        texto_original=orm.texto_cifrado,
        problema=problema_do_orm(orm.problema),
        prioridade=Prioridade(orm.prioridade),
        confianca=orm.confianca,
        origem=OrigemClassificacao(orm.origem),
        sintomas=tuple(json.loads(orm.sintomas_cifrados or "[]")),
        registrada_em=orm.registrada_em,
        reclassificada_em=orm.reclassificada_em,
        consulta_id=orm.consulta_id,
    )


# --- Agenda -----------------------------------------------------------------------------------


def consulta_para_orm(consulta: Consulta) -> ConsultaOrm:
    orm = ConsultaOrm(id=consulta.id)
    atualizar_consulta_orm(orm, consulta)
    return orm


def atualizar_consulta_orm(orm: ConsultaOrm, consulta: Consulta) -> None:
    orm.paciente_id = consulta.paciente_id
    orm.queixa_id = consulta.queixa_id
    orm.inicio = consulta.horario.inicio
    orm.fim = consulta.horario.fim
    orm.status = consulta.status.value
    orm.prioridade = consulta.prioridade.value
    orm.origem = consulta.origem.value
    orm.agendada_em = consulta.agendada_em
    orm.atualizada_em = consulta.atualizada_em


def consulta_do_orm(orm: ConsultaOrm) -> Consulta:
    return Consulta(
        id=orm.id,
        paciente_id=orm.paciente_id,
        queixa_id=orm.queixa_id,
        horario=Horario(orm.inicio, orm.fim),
        status=StatusConsulta(orm.status),
        prioridade=Prioridade(orm.prioridade),
        origem=OrigemAgendamento(orm.origem),
        agendada_em=orm.agendada_em,
        atualizada_em=orm.atualizada_em,
    )


def bloqueio_para_orm(bloqueio: BloqueioAgenda) -> BloqueioAgendaOrm:
    return BloqueioAgendaOrm(
        id=bloqueio.id,
        inicio=bloqueio.periodo.inicio,
        fim=bloqueio.periodo.fim,
        motivo=bloqueio.motivo,
        criado_em=bloqueio.criado_em,
    )


def bloqueio_do_orm(orm: BloqueioAgendaOrm) -> BloqueioAgenda:
    return BloqueioAgenda(
        id=orm.id,
        periodo=Horario(orm.inicio, orm.fim),
        motivo=orm.motivo,
        criado_em=orm.criado_em,
    )


# --- Conversa ---------------------------------------------------------------------------------

type _Conversor = Callable[[Any], Any]

_CONVERSORES_DADOS: dict[str, tuple[_Conversor, _Conversor]] = {
    "documento": (
        lambda d: [d.numero, d.uf.value],
        lambda v: DocumentoRg(v[0], Uf(v[1])),
    ),
    "nome": (str, str),
    "data_nascimento": (date.isoformat, date.fromisoformat),
    "responsavel": (str, str),
    "paciente_id": (str, UUID),
    "nome_paciente": (str, str),
    "numero_prontuario": (lambda n: n.sequencial, NumeroProntuario),
    "queixa_id": (str, UUID),
    "prioridade": (lambda p: p.value, Prioridade),
    "horario_sugerido": (datetime.isoformat, datetime.fromisoformat),
    "consulta_futura": (datetime.isoformat, datetime.fromisoformat),
    "consulta_id": (str, UUID),
}


def dados_conversa_para_json(dados: DadosConversa) -> str:
    serializado = {
        campo: para_json(getattr(dados, campo))
        for campo, (para_json, _) in _CONVERSORES_DADOS.items()
        if getattr(dados, campo) is not None
    }
    return json.dumps(serializado, ensure_ascii=False, sort_keys=True)


def dados_conversa_do_json(texto: str) -> DadosConversa:
    bruto: dict[str, Any] = json.loads(texto)
    return DadosConversa(
        **{
            campo: _CONVERSORES_DADOS[campo][1](valor)
            for campo, valor in bruto.items()
            if campo in _CONVERSORES_DADOS
        }
    )


def atualizar_conversa_orm(orm: ConversaOrm, conversa: Conversa) -> None:
    orm.id = conversa.id
    orm.wa_id = conversa.wa_id.valor
    orm.etapa = conversa.etapa.value
    orm.dados_cifrados = dados_conversa_para_json(conversa.dados)
    orm.tentativas_invalidas = conversa.tentativas_invalidas
    orm.ultima_interacao = conversa.ultima_interacao
    orm.iniciada_em = conversa.iniciada_em
    orm.encerrada_em = conversa.encerrada_em


def conversa_do_orm(orm: ConversaOrm) -> Conversa:
    return Conversa(
        id=orm.id,
        wa_id=WaId(orm.wa_id),
        etapa=EtapaConversa(orm.etapa),
        dados=dados_conversa_do_json(orm.dados_cifrados),
        tentativas_invalidas=orm.tentativas_invalidas,
        ultima_interacao=orm.ultima_interacao,
        iniciada_em=orm.iniciada_em,
        encerrada_em=orm.encerrada_em,
    )


# --- Mensagem ---------------------------------------------------------------------------------


def mensagem_para_valores(mensagem: Mensagem) -> dict[str, Any]:
    """Valores das colunas (para ``insert ... on conflict``)."""
    return {
        "id": mensagem.id,
        "wa_id": mensagem.wa_id.valor,
        "direcao": mensagem.direcao.value,
        "tipo": mensagem.tipo.value,
        "texto_cifrado": mensagem.texto,
        "wa_message_id": mensagem.wa_message_id,
        "midia_id": mensagem.midia_id,
        "automatica": mensagem.automatica,
        "momento": mensagem.momento,
        "criada_em": mensagem.criada_em,
        "processada_em": mensagem.processada_em,
    }


def mensagem_para_orm(mensagem: Mensagem) -> MensagemOrm:
    return MensagemOrm(**mensagem_para_valores(mensagem))


def mensagem_do_orm(orm: MensagemOrm) -> Mensagem:
    return Mensagem(
        id=orm.id,
        wa_id=WaId(orm.wa_id),
        direcao=DirecaoMensagem(orm.direcao),
        tipo=TipoMensagem(orm.tipo),
        texto=orm.texto_cifrado,
        wa_message_id=orm.wa_message_id,
        midia_id=orm.midia_id,
        automatica=orm.automatica,
        momento=orm.momento,
        criada_em=orm.criada_em,
        processada_em=orm.processada_em,
    )
