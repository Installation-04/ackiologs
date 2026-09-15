from app.connectors.bacnet_connector import BacnetConnector
from app.connectors.base import BaseConnector
from app.connectors.ethernetip_connector import EtherNetIpConnector
from app.connectors.http_connector import HttpConnector
from app.connectors.modbus_connector import ModbusConnector
from app.connectors.mqtt_connector import MqttConnector
from app.connectors.opcua_connector import OpcUaConnector
from app.connectors.s7_connector import S7Connector
from app.connectors.simulator import SimulatorConnector
from app.connectors.snmp_connector import SnmpConnector
from app.connectors.sql_connector import SqlConnector

CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "simulator": SimulatorConnector,
    "opcua": OpcUaConnector,
    "modbus": ModbusConnector,
    "mqtt": MqttConnector,
    "ethernetip": EtherNetIpConnector,
    "s7": S7Connector,
    "bacnet": BacnetConnector,
    "snmp": SnmpConnector,
    "http": HttpConnector,
    "sql": SqlConnector,
}


def get_connector_class(protocol: str) -> type[BaseConnector]:
    try:
        return CONNECTOR_CLASSES[protocol]
    except KeyError as exc:
        raise ValueError(
            f"Unknown protocol '{protocol}'. Available: {', '.join(CONNECTOR_CLASSES)}. "
            "Add a new one by subclassing app.connectors.base.BaseConnector and registering it here."
        ) from exc
