"""Máquina de estados da conversa: fluxos completos, respostas inválidas, expiração e silêncio."""

from datetime import date, datetime, timedelta
from uuid import uuid7

import pytest

from odonto.dominio.excecoes import DadoInvalidoError, TransicaoInvalidaError
from odonto.dominio.modelo.conversa import (
    AcaoConversa,
    AgendarHorario,
    BuscarPaciente,
    CadastrarPaciente,
    ClassificarQueixa,
    Conversa,
    DadosConversa,
    InterpretarDataHora,
    OferecerPrimeiroHorario,
    RegrasConversa,
)
from odonto.dominio.modelo.enums import ChaveMensagem, EtapaConversa, MotivoSugestao, Prioridade
from odonto.dominio.modelo.eventos import AtendimentoHumanoNecessario, ConsentimentoRecusado
from odonto.dominio.modelo.valores import NumeroProntuario
from tests.apoio import AGORA, RG, WA_ID, em

REGRAS = RegrasConversa()
PACIENTE_ID = uuid7()
QUEIXA_ID = uuid7()
CONSULTA_ID = uuid7()
SEXTA_10H = em(2026, 11, 20, 10, 0)
SEXTA_8H = em(2026, 11, 20, 8, 0)


class Dialogo:
    """Conduz a conversa avançando o relógio um minuto a cada mensagem do paciente."""

    def __init__(self) -> None:
        self.momento = AGORA
        self.conversa, acao = Conversa.iniciar(WA_ID, self.momento)
        assert chaves(acao) == [ChaveMensagem.BOAS_VINDAS]
        assert acao.comando is None

    def paciente(
        self,
        texto: str | None,
        *,
        depois: timedelta = timedelta(minutes=1),
        regras: RegrasConversa = REGRAS,
    ) -> AcaoConversa:
        self.momento += depois
        return self.conversa.registrar_resposta(
            texto, recebida_em=self.momento, agora=self.momento, regras=regras
        )

    @property
    def etapa(self) -> EtapaConversa:
        return self.conversa.etapa

    def identificar_existente(self, consulta_futura: datetime | None = None) -> AcaoConversa:
        acao = self.paciente("12.345.678-9 SP")
        assert acao.comando == BuscarPaciente(RG)
        return self.conversa.paciente_encontrado(
            paciente_id=PACIENTE_ID, nome_paciente="Maria", consulta_futura=consulta_futura
        )

    def ate_data_hora(self, prioridade: Prioridade = Prioridade.ROTINA) -> AcaoConversa:
        self.identificar_existente()
        acao = self.paciente("estou com dor de dente")
        assert acao.comando == ClassificarQueixa(
            paciente_id=PACIENTE_ID, texto="estou com dor de dente"
        )
        return self.conversa.queixa_registrada(queixa_id=QUEIXA_ID, prioridade=prioridade)


def chaves(acao: AcaoConversa) -> list[ChaveMensagem]:
    return [mensagem.chave for mensagem in acao.mensagens]


def agendar(dialogo: Dialogo, inicio: datetime) -> AcaoConversa:
    return dialogo.conversa.consulta_agendada(
        consulta_id=CONSULTA_ID, inicio=inicio, momento=dialogo.momento
    )


class TestPacienteExistente:
    def test_do_rg_ao_agendamento(self) -> None:
        dialogo = Dialogo()
        acao = dialogo.identificar_existente()
        assert chaves(acao) == [ChaveMensagem.PACIENTE_ENCONTRADO]
        assert acao.mensagens[0].nome_paciente == "Maria"
        assert dialogo.conversa.dados.documento is None

        acao = dialogo.paciente("estou com dor de dente")
        assert isinstance(acao.comando, ClassificarQueixa)
        acao = dialogo.conversa.queixa_registrada(
            queixa_id=QUEIXA_ID, prioridade=Prioridade.URGENCIA
        )
        assert chaves(acao) == [ChaveMensagem.PEDIR_DATA_HORA]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_DATA_HORA

        acao = dialogo.paciente("sexta às 10h")
        assert acao.comando == InterpretarDataHora("sexta às 10h")
        acao = dialogo.conversa.horario_disponivel(SEXTA_10H)
        assert acao.comando == AgendarHorario(
            paciente_id=PACIENTE_ID,
            queixa_id=QUEIXA_ID,
            inicio=SEXTA_10H,
            prioridade=Prioridade.URGENCIA,
        )

        acao = agendar(dialogo, SEXTA_10H)
        assert chaves(acao) == [ChaveMensagem.AGENDADO]
        assert acao.mensagens[0].data_hora == SEXTA_10H
        assert dialogo.etapa is EtapaConversa.CONCLUIDA
        assert dialogo.conversa.encerrada
        assert dialogo.conversa.dados.consulta_id == CONSULTA_ID

    def test_consulta_futura_e_nova_consulta(self) -> None:
        dialogo = Dialogo()
        acao = dialogo.identificar_existente(consulta_futura=SEXTA_10H)
        assert chaves(acao) == [ChaveMensagem.CONSULTA_FUTURA]
        assert acao.mensagens[0].data_hora == SEXTA_10H
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_DECISAO_NOVA_CONSULTA

        acao = dialogo.paciente("sim")
        assert chaves(acao) == [ChaveMensagem.PEDIR_PROBLEMA]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_PROBLEMA

    def test_consulta_futura_mantida(self) -> None:
        dialogo = Dialogo()
        dialogo.identificar_existente(consulta_futura=SEXTA_10H)
        acao = dialogo.paciente("não, obrigado")
        assert chaves(acao) == [ChaveMensagem.NOVA_CONSULTA_RECUSADA]
        assert acao.mensagens[0].data_hora == SEXTA_10H
        assert dialogo.etapa is EtapaConversa.CONCLUIDA


class TestPacienteNovo:
    def test_cadastro_completo_de_adulto(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("rg 12.345.678-9 ssp/sp")
        acao = dialogo.conversa.paciente_nao_encontrado()
        assert chaves(acao) == [ChaveMensagem.PEDIR_NOME]

        assert chaves(dialogo.paciente("meu nome é maria da silva")) == [
            ChaveMensagem.PEDIR_DATA_NASCIMENTO
        ]
        assert chaves(dialogo.paciente("15/03/1990")) == [ChaveMensagem.PEDIR_CONSENTIMENTO]
        acao = dialogo.paciente("Sim")
        assert acao.comando == CadastrarPaciente(
            documento=RG,
            nome="Maria da Silva",
            data_nascimento=date(1990, 3, 15),
            responsavel=None,
        )

        acao = dialogo.conversa.cadastro_concluido(
            paciente_id=PACIENTE_ID, nome_paciente="Maria", numero_prontuario=NumeroProntuario(42)
        )
        assert chaves(acao) == [ChaveMensagem.CADASTRO_CONCLUIDO]
        assert acao.mensagens[0].prontuario == NumeroProntuario(42)
        assert acao.mensagens[0].nome_paciente == "Maria"
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_PROBLEMA
        dados = dialogo.conversa.dados
        assert (dados.documento, dados.nome, dados.data_nascimento) == (None, None, None)

        dialogo.paciente("quero fazer uma limpeza")
        acao = dialogo.conversa.queixa_registrada(queixa_id=QUEIXA_ID, prioridade=Prioridade.ROTINA)
        assert chaves(acao) == [ChaveMensagem.PEDIR_DATA_HORA]

    def test_menor_de_idade_pede_responsavel(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12345678 SP")
        dialogo.conversa.paciente_nao_encontrado()
        dialogo.paciente("Pedro da Silva")
        assert chaves(dialogo.paciente("01/06/2015")) == [ChaveMensagem.PEDIR_RESPONSAVEL]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_RESPONSAVEL
        assert chaves(dialogo.paciente("Joana da Silva")) == [ChaveMensagem.PEDIR_CONSENTIMENTO]
        acao = dialogo.paciente("sim")
        assert isinstance(acao.comando, CadastrarPaciente)
        assert acao.comando.responsavel == "Joana da Silva"
        assert acao.comando.data_nascimento == date(2015, 6, 1)

    def test_consentimento_recusado_apaga_os_dados(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12345678 SP")
        dialogo.conversa.paciente_nao_encontrado()
        dialogo.paciente("Maria da Silva")
        dialogo.paciente("15/03/1990")
        acao = dialogo.paciente("Não")
        assert chaves(acao) == [ChaveMensagem.SEM_CONSENTIMENTO]
        assert dialogo.etapa is EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO
        assert dialogo.conversa.dados == DadosConversa()
        (evento,) = dialogo.conversa.coletar_eventos()
        assert isinstance(evento, ConsentimentoRecusado)

        # Um "obrigado" depois do fim não recebe resposta; uma nova mensagem recomeça.
        assert dialogo.paciente("obrigado") == AcaoConversa()
        assert chaves(dialogo.paciente("oi")) == [ChaveMensagem.BOAS_VINDAS]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_RG

    def test_dados_pessoais_fora_do_repr(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12.345.678-9 SP")
        dialogo.conversa.paciente_nao_encontrado()
        dialogo.paciente("Maria da Silva")
        dialogo.paciente("15/03/1990")
        texto = repr(dialogo.conversa)
        assert "Maria" not in texto
        assert "1990" not in texto
        assert "123456789" not in texto
        assert WA_ID.valor not in texto


class TestRespostasInvalidas:
    def test_tres_respostas_invalidas_encaminham_para_atendimento_humano(self) -> None:
        dialogo = Dialogo()
        for _ in range(2):
            acao = dialogo.paciente("não sei meu rg")
            assert chaves(acao) == [ChaveMensagem.NAO_ENTENDI]
            assert acao.mensagens[0].etapa is EtapaConversa.AGUARDANDO_RG
        acao = dialogo.paciente("???")
        assert chaves(acao) == [ChaveMensagem.ATENDIMENTO_HUMANO]
        assert dialogo.etapa is EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO
        (evento,) = dialogo.conversa.coletar_eventos()
        assert isinstance(evento, AtendimentoHumanoNecessario)
        assert evento.etapa is EtapaConversa.AGUARDANDO_RG
        assert evento.paciente_id is None

        # A equipe assume a conversa: o agente fica em silêncio até a expiração.
        assert dialogo.paciente("alô?") == AcaoConversa()
        assert chaves(dialogo.paciente("oi", depois=timedelta(hours=3))) == [
            ChaveMensagem.BOAS_VINDAS
        ]

    def test_resposta_valida_zera_as_tentativas(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("abc")
        dialogo.paciente("abc")
        dialogo.paciente("12345678 SP")
        dialogo.conversa.paciente_nao_encontrado()
        assert dialogo.conversa.tentativas_invalidas == 0
        assert chaves(dialogo.paciente("Maria")) == [ChaveMensagem.NAO_ENTENDI]

    def test_mensagem_sem_texto_pede_texto_sem_contar_tentativa(self) -> None:
        dialogo = Dialogo()
        for _ in range(5):
            assert chaves(dialogo.paciente(None)) == [ChaveMensagem.PEDIR_TEXTO]
        assert dialogo.conversa.tentativas_invalidas == 0
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_RG

    def test_queixa_sem_letras_suficientes(self) -> None:
        dialogo = Dialogo()
        dialogo.identificar_existente()
        assert chaves(dialogo.paciente("??")) == [ChaveMensagem.NAO_ENTENDI]

    def test_data_hora_nao_entendida(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        acao = dialogo.conversa.data_hora_nao_entendida(dialogo.momento, REGRAS)
        assert chaves(acao) == [ChaveMensagem.NAO_ENTENDI]
        assert acao.mensagens[0].etapa is EtapaConversa.AGUARDANDO_DATA_HORA


class TestExpiracao:
    def test_expiracao_reinicia_do_comeco(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12345678 SP")
        dialogo.conversa.paciente_nao_encontrado()
        dialogo.paciente("Maria da Silva")
        acao = dialogo.paciente("15/03/1990", depois=timedelta(minutes=121))
        assert chaves(acao) == [ChaveMensagem.BOAS_VINDAS]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_RG
        assert dialogo.conversa.dados == DadosConversa()

    def test_expirar_pelo_agendador_descarta_o_cadastro_parcial(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12345678 SP")
        dialogo.conversa.paciente_nao_encontrado()
        dialogo.paciente("Maria da Silva")
        assert dialogo.conversa.expirou(dialogo.momento + timedelta(hours=3), REGRAS)
        dialogo.conversa.expirar(dialogo.momento + timedelta(hours=3))
        assert dialogo.conversa.encerrada
        assert dialogo.conversa.dados == DadosConversa()
        assert chaves(dialogo.paciente("oi", depois=timedelta(hours=4))) == [
            ChaveMensagem.BOAS_VINDAS
        ]

    def test_janela_de_atendimento_conta_da_ultima_mensagem(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12345678 SP")
        janela = dialogo.conversa.janela_atendimento()
        assert janela.ultima_mensagem_paciente == dialogo.momento


class TestSugestaoDeHorario:
    def test_confirmacao_sim(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        dialogo.paciente("sexta")
        acao = dialogo.conversa.horario_sugerido(
            SEXTA_8H, motivo=MotivoSugestao.PREFERENCIA_INCOMPLETA, regras=REGRAS
        )
        assert chaves(acao) == [ChaveMensagem.SUGESTAO_HORARIO]
        assert acao.mensagens[0].data_hora == SEXTA_8H
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO

        acao = dialogo.paciente("sim, pode marcar")
        assert isinstance(acao.comando, AgendarHorario)
        assert acao.comando.inicio == SEXTA_8H
        assert chaves(agendar(dialogo, SEXTA_8H)) == [ChaveMensagem.AGENDADO]

    def test_nova_data_na_confirmacao(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        dialogo.paciente("sexta às 9h")
        acao = dialogo.conversa.horario_sugerido(
            SEXTA_10H, motivo=MotivoSugestao.HORARIO_INDISPONIVEL, regras=REGRAS
        )
        assert chaves(acao) == [ChaveMensagem.HORARIO_INDISPONIVEL]

        acao = dialogo.paciente("prefiro segunda às 14h")
        assert acao.comando == InterpretarDataHora("prefiro segunda às 14h")
        segunda = em(2026, 11, 23, 14, 0)
        acao = dialogo.conversa.horario_disponivel(segunda)
        assert isinstance(acao.comando, AgendarHorario)
        assert acao.comando.inicio == segunda

    def test_recusa_da_sugestao_pede_outra_data(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        dialogo.paciente("sexta")
        dialogo.conversa.horario_sugerido(
            SEXTA_8H, motivo=MotivoSugestao.PREFERENCIA_INCOMPLETA, regras=REGRAS
        )
        acao = dialogo.paciente("não")
        assert chaves(acao) == [ChaveMensagem.PEDIR_DATA_HORA]
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_DATA_HORA
        assert dialogo.conversa.dados.horario_sugerido is None

    def test_sem_confirmacao_agenda_direto(self) -> None:
        regras = RegrasConversa(confirmar_sugestao=False)
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        dialogo.paciente("sexta", regras=regras)
        acao = dialogo.conversa.horario_sugerido(
            SEXTA_8H, motivo=MotivoSugestao.PREFERENCIA_INCOMPLETA, regras=regras
        )
        assert acao.mensagens == ()
        assert isinstance(acao.comando, AgendarHorario)

    def test_sem_horario_livre_encaminha_para_a_equipe(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora(Prioridade.URGENCIA)
        dialogo.paciente("qualquer dia")
        acao = dialogo.conversa.sem_horario_disponivel(dialogo.momento)
        assert chaves(acao) == [ChaveMensagem.SEM_HORARIO]
        assert dialogo.etapa is EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO
        (evento,) = dialogo.conversa.coletar_eventos()
        assert isinstance(evento, AtendimentoHumanoNecessario)
        assert evento.paciente_id == PACIENTE_ID
        assert evento.prioridade is Prioridade.URGENCIA


class TestEmergencia:
    def test_emergencia_oferece_o_primeiro_horario_livre(self) -> None:
        dialogo = Dialogo()
        acao = dialogo.ate_data_hora(Prioridade.EMERGENCIA)
        assert chaves(acao) == [ChaveMensagem.EMERGENCIA]
        assert acao.comando == OferecerPrimeiroHorario()
        assert dialogo.etapa is EtapaConversa.AGUARDANDO_DATA_HORA

        # Mesmo sem exigir confirmação, a oferta do primeiro horário pergunta ao paciente.
        acao = dialogo.conversa.horario_sugerido(
            SEXTA_8H,
            motivo=MotivoSugestao.PRIMEIRO_LIVRE,
            regras=RegrasConversa(confirmar_sugestao=False),
        )
        assert chaves(acao) == [ChaveMensagem.SUGESTAO_HORARIO]
        acao = dialogo.paciente("sim")
        assert isinstance(acao.comando, AgendarHorario)
        assert acao.comando.prioridade is Prioridade.EMERGENCIA


class TestTransicoesInvalidas:
    def test_retorno_fora_da_etapa(self) -> None:
        dialogo = Dialogo()
        with pytest.raises(TransicaoInvalidaError):
            dialogo.conversa.horario_disponivel(SEXTA_10H)
        with pytest.raises(TransicaoInvalidaError):
            dialogo.conversa.queixa_registrada(queixa_id=QUEIXA_ID, prioridade=Prioridade.ROTINA)

    def test_paciente_nao_encontrado_exige_rg(self) -> None:
        with pytest.raises(TransicaoInvalidaError):
            Dialogo().conversa.paciente_nao_encontrado()

    def test_falha_inesperada_encaminha_para_a_equipe(self) -> None:
        dialogo = Dialogo()
        dialogo.paciente("12.345.678-9 SP")
        acao = dialogo.conversa.encaminhar_para_equipe("Falha ao buscar.", dialogo.momento)
        assert chaves(acao) == [ChaveMensagem.ATENDIMENTO_HUMANO]
        assert dialogo.etapa is EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO
        assert dialogo.conversa.dados.documento is None
        (evento,) = dialogo.conversa.coletar_eventos()
        assert isinstance(evento, AtendimentoHumanoNecessario)
        assert evento.etapa is EtapaConversa.AGUARDANDO_RG
        with pytest.raises(TransicaoInvalidaError):
            dialogo.conversa.encaminhar_para_equipe("De novo.", dialogo.momento)

    def test_conversa_concluida_recomeca_com_nova_mensagem(self) -> None:
        dialogo = Dialogo()
        dialogo.ate_data_hora()
        dialogo.paciente("sexta 10h")
        dialogo.conversa.horario_disponivel(SEXTA_10H)
        agendar(dialogo, SEXTA_10H)
        assert dialogo.paciente("Obrigada! Até sexta 👍") == AcaoConversa()
        assert dialogo.paciente("ok, até lá") == AcaoConversa()
        assert dialogo.etapa is EtapaConversa.CONCLUIDA
        assert chaves(dialogo.paciente("quero marcar outra consulta")) == [
            ChaveMensagem.BOAS_VINDAS
        ]


def test_regras_validas() -> None:
    with pytest.raises(DadoInvalidoError, match="positiva"):
        RegrasConversa(expiracao=timedelta(0))
    with pytest.raises(DadoInvalidoError, match="tentativas"):
        RegrasConversa(max_tentativas=0)
