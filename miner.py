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
import errno
import traceback

# ============================================================
#  KONFIGURACE
# ============================================================

SERVER_HOST = 'localhost'
SERVER_PORT = 9999
BAUDRATE = 115200
RECONNECT_DELAY = 5          # sekundy mezi pokusy o reconnect
HEARTBEAT_INTERVAL = 30      # každých 30s pošleme prázdný řádek jako keep-alive

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
        self.last_heartbeat = time.time()

    def connect(self):
        """Naváže spojení se serverem a pošle identifikační řádek."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)  # timeout pro connect
            self.sock.connect((self.server_host, self.server_port))
            self.sock.settimeout(None)  # po spojení vrátíme blokující režim
            # Pošleme identifikaci
            self.sock.sendall(f"DEVICE: {self.device_name}\n".encode('utf-8'))
            self.last_heartbeat = time.time()
            return True
        except socket.error as e:
            # Rozpoznáme konkrétní chybový kód
            error_code = e.errno if hasattr(e, 'errno') else None
            if error_code == errno.ECONNREFUSED:
                print(f"[{self.device_name}] Chyba připojení: ECONNREFUSED – server odmítl spojení (port {self.server_port})")
            elif error_code == errno.ETIMEDOUT:
                print(f"[{self.device_name}] Chyba připojení: ETIMEDOUT – vypršel čas na připojení k serveru")
            elif error_code == errno.EHOSTUNREACH:
                print(f"[{self.device_name}] Chyba připojení: EHOSTUNREACH – hostitel nedostupný")
            else:
                print(f"[{self.device_name}] Chyba připojení: kód {error_code} – {e}")
            self.sock = None
            return False
        except Exception as e:
            print(f"[{self.device_name}] Neočekávaná chyba při connect: {e}")
            self.sock = None
            return False

    def send_line(self, line):
        """Odešle jeden řádek dat na server."""
        if self.sock is None:
            return False
        try:
            self.sock.sendall((line + '\n').encode('utf-8'))
            return True
        except socket.error as e:
            error_code = e.errno if hasattr(e, 'errno') else None
            if error_code == errno.ECONNRESET:
                print(f"[{self.device_name}] Chyba odeslání: ECONNRESET – server resetoval spojení")
            elif error_code == errno.EPIPE:
                print(f"[{self.device_name}] Chyba odeslání: EPIPE – socket je uzavřený")
            else:
                print(f"[{self.device_name}] Chyba odeslání: kód {error_code} – {e}")
            self.sock = None
            return False
        except Exception as e:
            print(f"[{self.device_name}] Neočekávaná chyba při send: {e}")
            self.sock = None
            return False

    def close(self):
        """Uzavře socket."""
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

    def keep_alive(self):
        """Pokud uplynul heartbeat interval, pošleme prázdný řádek jako keep-alive."""
        if self.sock and (time.time() - self.last_heartbeat) > HEARTBEAT_INTERVAL:
            try:
                self.sock.sendall(b'\n')
                self.last_heartbeat = time.time()
            except:
                self.sock = None


def run_miner(port, device_name):
    client = MinerClient(device_name)
    ser = None
    try:
        # Otevření sériového portu
        ser = serial.Serial(port, BAUDRATE, timeout=1)
        print(f"[{device_name}] Připojeno k sériovému portu {port}")

        # Hlavní smyčka
        while client._running:
            # Pokud nejsme připojeni k serveru, opakovaně se zkoušíme připojit
            while client._running and not client.is_connected():
                print(f"[{device_name}] Pokus o připojení k serveru {SERVER_HOST}:{SERVER_PORT}...")
                if client.connect():
                    print(f"[{device_name}] Připojeno k serveru.")
                else:
                    time.sleep(RECONNECT_DELAY)

            # Čtení ze sériového portu a odesílání
            while client._running and client.is_connected():
                try:
                    # Kontrola keep-alive
                    client.keep_alive()

                    # Čtení dat ze sériového portu (s timeoutem)
                    if ser.in_waiting:
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            if not client.send_line(line):
                                # Odeslání selhalo – přerušíme vnitřní smyčku, abychom se pokusili o reconnect
                                break
                    else:
                        # Krátké uspání, aby se neblokovalo CPU
                        time.sleep(0.01)
                except serial.SerialException as e:
                    print(f"[{device_name}] Chyba sériového portu: {e}")
                    break
                except Exception as e:
                    print(f"[{device_name}] Neočekávaná chyba v hlavní smyčce: {e}")
                    traceback.print_exc()
                    break

            # Po vypadnutí ze smyčky uzavřeme spojení a chvíli počkáme před dalším reconnectem
            if client._running:
                client.close()
                print(f"[{device_name}] Spojení se serverem ztraceno, reconnect za {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)

    except serial.SerialException as e:
        print(f"[{device_name}] Chyba otevření sériového portu {port}: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        if ser and ser.is_open:
            ser.close()
        client.close()
        print(f"[{device_name}] Ukončen miner.")


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
        print("\nUkončuji všechny minery (Ctrl+C)...")
        # Pro jistotu počkáme, než vlákna dočistí
        for t in threads:
            t.join(timeout=2)
        print("Hotovo.")
        sys.exit(0)

if __name__ == '__main__':
    main()
