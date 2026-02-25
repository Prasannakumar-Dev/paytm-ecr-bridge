import os
import sys
import json
import logging
import threading
import serial.tools.list_ports
from fastapi import FastAPI
from pydantic import BaseModel
from paytm_payments import payments

logging.basicConfig(
    filename="paytm_bridge.log",
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

app = FastAPI(title="Healthligence Paytm Bridge")

device_lock = threading.Lock()


def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_configs():
    config_path = os.path.join(get_base_path(), "config.json")

    if not os.path.isfile(config_path):
        raise Exception(f"config.json missing at {config_path}")

    with open(config_path) as f:
        return json.load(f)


def is_port_available(port_name: str):
    ports = serial.tools.list_ports.comports()
    return any(port.device.upper() == port_name.upper() for port in ports)


class SaleRequest(BaseModel):
    order_id: str
    amount: str
    payment_mode: str = "QR"


class StatusRequest(BaseModel):
    order_id: str


@app.get("/health")
def health():
    try:
        configs = get_configs()
        port = configs["Sale"]["port_name"]

        return {
            "status": "running",
            "device_connected": is_port_available(port),
            "port": port
        }

    except Exception as e:
        logging.error(f"HEALTH ERROR: {str(e)}")
        return {"status": "error", "message": str(e)}


@app.post("/sale")
def sale(data: SaleRequest):

    with device_lock:
        try:
            configs = get_configs()
            sale_config = configs["Sale"]

            port = sale_config["port_name"]

            if not is_port_available(port):
                return {
                    "status": "error",
                    "message": f"Device not connected on {port}"
                }

            # Inject dynamic fields
            sale_config["order_id"] = data.order_id
            sale_config["amount"] = data.amount
            sale_config["payment_mode"] = data.payment_mode

            logging.info(f"SALE START | {sale_config}")

            # 🔥 Create fresh SDK instance every time
            sdk = payments.Payments()

            response = sdk.Sale(**sale_config)

            logging.info(f"SALE RESPONSE | {response}")

            return response

        except Exception as e:
            logging.error(f"SALE ERROR | {str(e)}")
            return {"status": "error", "message": str(e)}


@app.post("/status")
def status(data: StatusRequest):

    with device_lock:  # 🔥 SERIALIZE DEVICE ACCESS
        try:
            configs = get_configs()
            status_config = configs["Status"]

            port = status_config["port_name"]

            if not is_port_available(port):
                return {
                    "status": "error",
                    "message": f"Device not connected on {port}"
                }

            status_config["order_id"] = data.order_id

            logging.info(f"STATUS START | {status_config}")

            sdk = payments.Payments()

            response = sdk.Status(**status_config)

            logging.info(f"STATUS RESPONSE | {response}")

            return response

        except Exception as e:
            logging.error(f"STATUS ERROR | {str(e)}")
            return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    from gen_cert import generate_self_signed_cert

    base = get_base_path()
    cert_dir = os.path.join(base, "certs")
    os.makedirs(cert_dir, exist_ok=True)

    key_path, cert_path = generate_self_signed_cert(cert_dir)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8899,
        workers=1,
        ssl_keyfile=key_path,
        ssl_certfile=cert_path,
    )