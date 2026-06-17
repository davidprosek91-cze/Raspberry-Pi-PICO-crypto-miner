#!/usr/bin/env python3
"""
Havirov Coin – Miner pro automatické připojení všech RPI PICO / Arduino
Posílá surová data z každého sériového portu na hlavní server (localhost:9999)
"""

import serial
import serial.tools.list_ports
import socket
import time
import threading
import sys
import os

# ============================================================
#  KONFIGURACE
# ============================================================

SERVER_HOST = 'localhost'
SERVER_PORT = 9999
BAUDRATE = 115200
RECONNECT_DELAY = 5

# ============================================================
#  MINER KLIENT
# ============================================================

class MinerClient:
    def __init__(self, device_name, server_host=SERVER_HOST, server_port=SERVER_PORT):
        self.device_name = device_name
        self.server_host = server_host
        self.server_port = server_port
        self.sock = None
        self._running = True
        self._lock = threading.Lock()

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.server_host, self.server_port))
            self.sock.sendall(f"DEVICE: {self.device_name}\n".encode('utf-8'))
            return True
        except Exception as e:
            print(f"Chyba připojení k serveru: {e}")
            self.sock = None
            return False

    def send_line(self, line):
        if self.sock is None:
            return False
        try:
            self.sock.sendall((line + '\n').encode('utf-8'))
            return True
        except Exception:
            self.sock = None
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def stop(self):
        self._running = False

    def is_connected(self):
        return self.sock is not None


def run_miner(port, device_name):
    client = MinerClient(device_name)
    ser = None
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=1)
        print(f"Připojeno k {port} jako {device_name}")

        while client._running and not client.is_connected():
            print(f"Pokus o připojení k serveru {SERVER_HOST}:{SERVER_PORT}...")
            if client.connect():
                print("Připojeno k serveru.")
            else:
                time.sleep(RECONNECT_DELAY)

        while client._running:
            if ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    if not client.send_line(line):
                        print("Ztráta spojení se serverem, pokus o reconnect...")
                        client.close()
                        while client._running and not client.is_connected():
                            if client.connect():
                                print("Znovu připojeno.")
                                break
                            time.sleep(RECONNECT_DELAY)
            else:
                time.sleep(0.01)
    except serial.SerialException as e:
        print(f"Chyba sériového portu {port}: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        if ser and ser.is_open:
            ser.close()
        client.close()
        print(f"Ukončen miner pro {device_name}")


def main():
    print("Spouštím Havirov Coin Miner")
    print(f"Server: {SERVER_HOST}:{SERVER_PORT}")
    print("Hledám sériové porty...")

    ports = serial.tools.list_ports.comports()
    if not ports:
        print("Nebyl nalezen žádný sériový port.")
        sys.exit(1)

    target_ports = []
    for p in ports:
        if 'ttyACM' in p.device or 'ttyUSB' in p.device:
            target_ports.append(p.device)

    if not target_ports:
        print("Nenalezen žádný port typu ttyACM nebo ttyUSB.")
        print("Dostupné porty:")
        for p in ports:
            print(f"  {p.device} - {p.description}")
        sys.exit(1)

    print(f"Nalezeno {len(target_ports)} portů: {', '.join(target_ports)}")

    threads = []
    for port in target_ports:
        device_name = f"RPI_{port.replace('/', '_')}"
        t = threading.Thread(target=run_miner, args=(port, device_name), daemon=True)
        t.start()
        threads.append(t)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nUkončuji všechny minery...")
        sys.exit(0)

if __name__ == '__main__':
    main()
