from app.connectors.base import BaseConnector
from app.connectors.modbus_connector import ModbusConnector
from app.connectors.mqtt_connector import MqttConnector
from app.connectors.opcua_connector import OpcUaConnector
from app.connectors.simulator import SimulatorConnector

CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "simulator": SimulatorConnector,
    "opcua": OpcUaConnector,
    "modbus": ModbusConnector,
    "mqtt": MqttConnector,
}


def get_connector_class(protocol: str) -> type[BaseConnector]:
    try:
        return CONNECTOR_CLASSES[protocol]
    except KeyError as exc:
        raise ValueError(
            f"Unknown protocol '{protocol}'. Available: {', '.join(CONNECTOR_CLASSES)}. "
            "Add a new one by subclassing app.connectors.base.BaseConnector and registering it here."
        ) from exc
