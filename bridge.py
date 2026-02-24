import os
import json
import logging
import sys
import concurrent.futures
import serial.tools.list_ports
from fastapi import FastAPI
from pydantic import BaseModel
from paytm_payments import payments

# ---------------- INIT ---------------- #

logging.basicConfig(
    filename="paytm_bridge.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

app = FastAPI(title="Healthligence Paytm Bridge")

# ---------------- UTILITIES ---------------- #

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


def execute_with_timeout(func, timeout=180):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        return future.result(timeout=timeout)


def create_payment_instance(config: dict):
    """
    Create fresh SDK instance with full config.
    This ensures COM port is properly initialized.
    """
    logging.info(f"Creating SDK instance with config: {config}")
    return payments.Payments(**config)


# ---------------- MODELS ---------------- #

class SaleRequest(BaseModel):
    order_id: str
    amount: str
    payment_mode: str = "QR"


class StatusRequest(BaseModel):
    order_id: str


# ---------------- ROUTES ---------------- #

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
        return {
            "status": "error",
            "message": str(e)
        }


@app.post("/sale")
def sale(data: SaleRequest):
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

        logging.info(f"SALE START | ORDER: {data.order_id} | AMOUNT: {data.amount}")

        # 🔥 Fresh SDK instance per transaction
        sdk = create_payment_instance(sale_config)

        def call_sale():
            return sdk.Sale()

        response = execute_with_timeout(call_sale, timeout=180)

        logging.info(f"SALE RESPONSE | ORDER: {data.order_id} | RESPONSE: {response}")

        return response

    except concurrent.futures.TimeoutError:
        logging.error(f"SALE TIMEOUT | ORDER: {data.order_id}")
        return {
            "status": "timeout",
            "message": "Transaction timed out"
        }

    except Exception as e:
        logging.error(f"SALE ERROR | ORDER: {data.order_id} | {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }


@app.post("/status")
def status(data: StatusRequest):
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

        logging.info(f"STATUS START | ORDER: {data.order_id}")

        sdk = create_payment_instance(status_config)

        def call_status():
            return sdk.Status()

        response = execute_with_timeout(call_status, timeout=60)

        logging.info(f"STATUS RESPONSE | ORDER: {data.order_id} | RESPONSE: {response}")

        return response

    except concurrent.futures.TimeoutError:
        logging.error(f"STATUS TIMEOUT | ORDER: {data.order_id}")
        return {
            "status": "timeout",
            "message": "Status request timed out"
        }

    except Exception as e:
        logging.error(f"STATUS ERROR | ORDER: {data.order_id} | {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

# ---------------- SERVER ENTRY ---------------- #

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8899)
