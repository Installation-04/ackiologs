from fastapi import Request

from app.core.supervisor import ConnectorSupervisor
from app.ingest.pipeline import IngestPipeline


def get_supervisor(request: Request) -> ConnectorSupervisor:
    return request.app.state.supervisor


def get_pipeline(request: Request) -> IngestPipeline:
    return request.app.state.pipeline
