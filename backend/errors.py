"""Erros de domínio e tratamento centralizado de erros HTTP."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("senac_bot.errors")


class RobotError(Exception):
    """Operação recusada pelo controlador ou pelas regras de segurança."""

    status_code = 409

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class EmergencyStopActive(RobotError):
    """A parada de emergência está acionada."""


class HardwareUnavailable(RobotError):
    """O hardware solicitado não está disponível; o simulador pode ser usado."""


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RobotError)
    async def robot_error_handler(_: Request, exc: RobotError) -> JSONResponse:
        logger.warning("Operação recusada: %s", exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Erro inesperado ao processar a requisição.", exc_info=exc)
        return JSONResponse(
            status_code=500, content={"detail": "Erro interno. Tente novamente em instantes."}
        )
