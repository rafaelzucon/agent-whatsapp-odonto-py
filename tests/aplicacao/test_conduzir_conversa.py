"""Condução da conversa de ponta a ponta, com fakes em memória (sem banco e sem chaves)."""

from datetime import timedelta

from odonto.aplicacao.excecoes import FalhaIntegracaoError
from odonto.aplicacao.portas.entrada.conversa import ProcessarMensagemCommand
from odonto.aplicacao.portas.saida.ia import ClassificacaoIA
from odonto.aplicacao.portas.saida.notificacao import TipoAlerta
from odonto.dominio.modelo.enums import (
    DirecaoMensagem,
    EtapaConversa,
    OrigemClassificacao,
    Prioridade,
    TipoMensagem,
)
from odonto.dominio.modelo.valores import WaId
from tests.aplicacao.fakes import Ambiente, CanalFalso
from tests.apoio import em

SEXTA_10H = em(2026, 11, 20, 10, 0)
DOR_DE_DENTE_IA = ClassificacaoIA(
    codigo="DOR_DE_DENTE", confianca=0.92, prioridade=Prioridade.URGENCIA, sintomas=("dor",)
)


async def identificar_existente(ambiente: Ambiente) -> None:
    await ambiente.paciente_diz("oi")
    await ambiente.paciente_diz("12.345.678-9 SP")


class TestPacienteNovo:
    async def test_do_primeiro_contato_ate_a_notificacao(self) -> None:
        canal = CanalFalso()
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA, canais=[canal])

        await ambiente.paciente_diz("Oi, boa tarde")
        assert "informe o número do seu RG" in ambiente.enviador.ultimo
        assert "Consultório Sorriso" in ambiente.enviador.ultimo

        await ambiente.paciente_diz("RG 12.345.678-9 SSP/SP")
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_NOME
        await ambiente.paciente_diz("Maria da Silva")
        await ambiente.paciente_diz("15/03/1990")
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_CONSENTIMENTO
        assert ambiente.pacientes == []

        await ambiente.paciente_diz("sim")
        (paciente,) = ambiente.pacientes
        assert paciente.nome == "Maria da Silva"
        assert paciente.telefones == [ambiente.wa_id]
        prontuario = ambiente.prontuario_de(paciente.id)
        assert str(prontuario.numero) == "PR-000001"
        assert "PR-000001" in ambiente.enviador.ultimo
        assert ambiente.conversa.dados.nome is None  # dados de cadastro saem da conversa

        await ambiente.paciente_diz("estou com muita dor de dente")
        (queixa,) = ambiente.prontuario_de(paciente.id).queixas
        assert queixa.problema.codigo == "DOR_DE_DENTE"
        assert queixa.origem is OrigemClassificacao.IA
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_DATA_HORA

        (resultado,) = await ambiente.paciente_diz("sexta às 10h")
        assert resultado.etapa is EtapaConversa.CONCLUIDA
        (consulta,) = ambiente.consultas
        assert consulta.inicio == SEXTA_10H
        assert consulta.prioridade is Prioridade.URGENCIA
        assert ambiente.prontuario_de(paciente.id).queixas[0].consulta_id == consulta.id
        assert "sexta-feira, 20/11/2026 às 10:00" in ambiente.enviador.ultimo
        assert "Rua das Flores, 100" in ambiente.enviador.ultimo

        (aviso,) = canal.avisos
        assert aviso.parametros_template() == (
            "Maria da Silva",
            "sexta-feira, 20/11/2026 às 10:00",
            "Dor de dente",
            "Urgência",
        )
        assert aviso.prontuario == "PR-000001"
        assert canal.alertas == []

        recebidas = ambiente.mensagens(DirecaoMensagem.RECEBIDA)
        enviadas = ambiente.mensagens(DirecaoMensagem.ENVIADA)
        assert len(recebidas) == 7
        assert all(not mensagem.pendente for mensagem in recebidas)
        assert len(enviadas) == len(ambiente.enviador.textos) == 7

    async def test_consentimento_recusado_avisa_o_consultorio(self) -> None:
        canal = CanalFalso()
        ambiente = Ambiente(canais=[canal])
        for texto in ("oi", "12345678 SP", "Maria da Silva", "15/03/1990", "não"):
            await ambiente.paciente_diz(texto)
        assert ambiente.conversa.etapa is EtapaConversa.ENCERRADA_SEM_CONSENTIMENTO
        assert ambiente.pacientes == []
        (alerta,) = canal.alertas
        assert alerta.tipo is TipoAlerta.CONSENTIMENTO_RECUSADO
        assert alerta.paciente == "WhatsApp com final 4321"


class TestPacienteExistente:
    async def test_identifica_vincula_o_numero_e_agenda(self) -> None:
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA)
        paciente = await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)
        assert "Olá, Maria!" in ambiente.enviador.ultimo
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_PROBLEMA
        assert ambiente.wa_id in ambiente.pacientes[0].telefones

        await ambiente.paciente_diz("dor de dente")
        await ambiente.paciente_diz("sexta às 10h")
        (consulta,) = ambiente.consultas_do(paciente.id)
        assert consulta.inicio == SEXTA_10H
        assert len(ambiente.pacientes) == 1

    async def test_consulta_futura_mantida_encerra(self) -> None:
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA)
        await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)
        await ambiente.paciente_diz("dor de dente")
        await ambiente.paciente_diz("sexta às 10h")

        await ambiente.paciente_diz("oi de novo", depois=timedelta(hours=3))
        await ambiente.paciente_diz("12.345.678-9 SP")
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_DECISAO_NOVA_CONSULTA
        assert "20/11/2026 às 10:00" in ambiente.enviador.ultimo
        await ambiente.paciente_diz("não")
        assert ambiente.conversa.etapa is EtapaConversa.CONCLUIDA
        assert len(ambiente.consultas) == 1


class TestEmergencia:
    async def test_emergencia_avisa_o_consultorio_na_hora(self) -> None:
        canal = CanalFalso()
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA, canais=[canal])
        paciente = await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)

        await ambiente.paciente_diz("dor de dente e o rosto está inchado")
        (alerta,) = canal.alertas
        assert alerta.tipo is TipoAlerta.EMERGENCIA
        assert alerta.paciente == "Maria da Silva"
        assert alerta.prioridade is Prioridade.EMERGENCIA
        assert "rosto esta inchado" in alerta.resumo
        textos = [texto for _, texto in ambiente.enviador.textos[-2:]]
        assert "SAMU (192)" in textos[0]
        assert "primeiro horário livre" in textos[1]
        # 09:03 + 2h de antecedência → primeiro horário da grade: 11:30.
        assert ambiente.conversa.dados.horario_sugerido == em(2026, 11, 18, 11, 30)
        assert ambiente.consultas == []

        await ambiente.paciente_diz("sim")
        (consulta,) = ambiente.consultas_do(paciente.id)
        assert consulta.inicio == em(2026, 11, 18, 11, 30)
        assert consulta.prioridade is Prioridade.EMERGENCIA
        assert len(canal.avisos) == 1


class TestHorarioIndisponivel:
    async def test_horario_ocupado_sugere_o_mais_proximo(self) -> None:
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA)
        paciente = await ambiente.cadastrar_paciente_existente()
        ambiente.ocupar(SEXTA_10H)
        await identificar_existente(ambiente)
        await ambiente.paciente_diz("dor de dente")

        await ambiente.paciente_diz("sexta às 10h")
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO
        sugerido = ambiente.conversa.dados.horario_sugerido
        assert sugerido in {em(2026, 11, 20, 9, 30), em(2026, 11, 20, 10, 30)}
        assert "não está disponível" in ambiente.enviador.ultimo

        await ambiente.paciente_diz("sim")
        (consulta,) = ambiente.consultas_do(paciente.id)
        assert consulta.inicio == sugerido

    async def test_conflito_de_concorrencia_oferece_o_proximo(self) -> None:
        canal = CanalFalso()
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA, canais=[canal])
        paciente = await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)
        await ambiente.paciente_diz("dor de dente")
        # Outro paciente agenda sexta às 10h entre a verificação da agenda e a gravação.
        ambiente.banco.concorrentes.add(SEXTA_10H)

        await ambiente.paciente_diz("sexta às 10h")
        assert ambiente.consultas_do(paciente.id) == []
        assert len(ambiente.consultas) == 1  # só a do outro paciente
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_CONFIRMACAO_SUGESTAO
        sugerido = ambiente.conversa.dados.horario_sugerido
        assert sugerido is not None
        assert sugerido != SEXTA_10H
        assert canal.avisos == []

        await ambiente.paciente_diz("sim")
        (consulta,) = ambiente.consultas_do(paciente.id)
        assert consulta.inicio == sugerido
        assert len(canal.avisos) == 1


class TestMensagensEspeciais:
    async def test_audio_transcrito_segue_o_fluxo(self) -> None:
        ambiente = Ambiente(transcricao="12.345.678-9 SP")
        await ambiente.cadastrar_paciente_existente()
        await ambiente.paciente_diz("oi")
        await ambiente.paciente_diz(None, tipo=TipoMensagem.AUDIO, midia_id="midia-1")
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_PROBLEMA
        audio = ambiente.mensagens(DirecaoMensagem.RECEBIDA)[-1]
        assert audio.texto == "12.345.678-9 SP"

    async def test_audio_sem_transcricao_pede_texto(self) -> None:
        ambiente = Ambiente(transcricao=None)
        await ambiente.paciente_diz("oi")
        await ambiente.paciente_diz(None, tipo=TipoMensagem.AUDIO, midia_id="midia-1")
        assert "mensagem de texto" in ambiente.enviador.ultimo
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_RG

    async def test_figurinha_pede_texto(self) -> None:
        ambiente = Ambiente()
        await ambiente.paciente_diz("oi")
        await ambiente.paciente_diz("ignorado", tipo=TipoMensagem.OUTRO)
        assert "mensagem de texto" in ambiente.enviador.ultimo

    async def test_webhook_repetido_e_processado_uma_vez(self) -> None:
        ambiente = Ambiente()
        await ambiente.paciente_diz("oi")
        recebida = ambiente.mensagens(DirecaoMensagem.RECEBIDA)[0]
        resultado = await ambiente.conduzir.executar(ProcessarMensagemCommand(recebida.id))
        assert not resultado.processada
        assert len(ambiente.enviador.textos) == 1

    async def test_falha_no_envio_nao_impede_o_processamento(self) -> None:
        ambiente = Ambiente()
        ambiente.enviador.falhar = True
        (resultado,) = await ambiente.paciente_diz("oi")
        assert resultado.processada
        assert resultado.mensagens_enviadas == 0
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_RG
        assert ambiente.mensagens(DirecaoMensagem.ENVIADA) == []

    async def test_fora_da_janela_de_24h_nao_responde(self) -> None:
        ambiente = Ambiente()
        await ambiente.paciente_diz("oi")
        recebida = ambiente.mensagens(DirecaoMensagem.RECEBIDA)[0]
        ambiente.banco.estado.mensagens[recebida.id].processada_em = None
        ambiente.relogio.avancar(timedelta(hours=25))
        resultado = await ambiente.conduzir.executar(ProcessarMensagemCommand(recebida.id))
        assert resultado.processada
        assert resultado.mensagens_enviadas == 0

    async def test_numero_ignorado_nao_gera_mensagem(self) -> None:
        ambiente = Ambiente(numeros_ignorados={"5511912345678"})
        ambiente.wa_id = WaId("5511912345678")
        assert await ambiente.paciente_diz("oi") == []
        assert ambiente.enviador.textos == []


class TestFalhas:
    async def test_falha_inesperada_encaminha_para_a_equipe(self) -> None:
        canal = CanalFalso()
        ambiente = Ambiente(canais=[canal])
        await ambiente.cadastrar_paciente_existente()
        ambiente.banco.estado.catalogo.clear()  # catálogo vazio: configuração inválida
        await identificar_existente(ambiente)

        (resultado,) = await ambiente.paciente_diz("dor de dente")
        assert resultado.etapa is EtapaConversa.ENCAMINHADA_ATENDIMENTO_HUMANO
        assert "equipe" in ambiente.enviador.ultimo
        (alerta,) = canal.alertas
        assert alerta.tipo is TipoAlerta.ATENDIMENTO_HUMANO
        assert alerta.paciente == "Maria da Silva"

    async def test_ia_indisponivel_classifica_por_palavra_chave(self) -> None:
        ambiente = Ambiente(classificacao_ia=FalhaIntegracaoError("timeout"))
        paciente = await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)
        await ambiente.paciente_diz("estou com dor de dente")
        (queixa,) = ambiente.prontuario_de(paciente.id).queixas
        assert queixa.problema.codigo == "DOR_DE_DENTE"
        assert queixa.origem is OrigemClassificacao.PALAVRA_CHAVE

    async def test_data_nao_entendida_usa_a_ia_e_depois_pede_de_novo(self) -> None:
        ambiente = Ambiente(classificacao_ia=DOR_DE_DENTE_IA)
        await ambiente.cadastrar_paciente_existente()
        await identificar_existente(ambiente)
        await ambiente.paciente_diz("dor de dente")
        await ambiente.paciente_diz("quando der")
        assert ambiente.interpretador_ia.chamadas == ["quando der"]
        assert ambiente.conversa.etapa is EtapaConversa.AGUARDANDO_DATA_HORA
        assert ambiente.conversa.tentativas_invalidas == 1
