"""Telemetria de produto desativada para o indice local."""

from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class SemTelemetria(ProductTelemetryClient):
    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        pass
