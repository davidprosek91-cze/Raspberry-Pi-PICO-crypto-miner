#!/usr/bin/env python3
"""
Havirov Coin – Kompletní aplikace (GUI + server + miner)
Opravená verze s robustním TCP serverem, synchronizací a detailními chybovými hláškami.
Veškerý text je 2× větší a tučný (font 28 bodů).
"""

import sys
import os
import random
import time
import re
import requests
import socket
import threading
import webbrowser
import json
import tempfile
import select
import errno
import traceback
import hashlib
from datetime import datetime
from collections import deque
from queue import Queue, Empty
from pathlib import Path
from flask import Flask, request, jsonify
import fcntl
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QTableWidget,
    QTableWidgetItem, QGridLayout, QFrame, QScrollArea, QGroupBox,
    QFormLayout, QMessageBox, QHeaderView, QSizePolicy,
    QInputDialog, QDialog, QTextEdit, QSplitter, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QObject, QUrl
from PyQt5.QtGui import QFont

# Pokus o import WebEngine – pokud chybí, použijeme externí prohlížeč (bez varování)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False

import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

import serial
import serial.tools.list_ports

# ============================================================
#  POTLAČENÍ WAYLAND VAROVÁNÍ
# ============================================================
os.environ["QT_QPA_PLATFORM"] = "xcb"

# ============================================================
#  FAUCETPAY KONFIGURACE
# ============================================================

FAUCETPAY_API_KEY = "69ed69cf56555931401881143a3897f149aefa7afaf30303d32cb64b25d3fbd3"
FAUCETPAY_MERCHANT_ID = "davepro777cze"
FAUCETPAY_API_URL = "https://faucetpay.io/api/v1"

BASE_RATE = 1e-12
SPREAD = 0.05
TRANSACTION_FEE = 0.03
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "havirov_state.json")

# Kurz CZK/USDT (pevný, lze dynamicky aktualizovat)
CZK_RATE = 25.0

# Flask port
FLASK_CALLBACK_PORT = 9998

# ============================================================
#  FAUCETPAY API FUNKCE
# ============================================================

def faucetpay_get_balance():
    try:
        response = requests.post(
            f"{FAUCETPAY_API_URL}/balance",
            data={"api_key": FAUCETPAY_API_KEY, "currency": "USDT"},
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == 200:
                balance_satoshi = int(data.get("balance", 0))
                return balance_satoshi / 100000000
        return 0.0
    except Exception as e:
        print(f"Chyba při získávání zůstatku: {e}")
        return 0.0

def faucetpay_deposit(amount_usdt, custom_tag=""):
    callback_url = f"http://localhost:{FLASK_CALLBACK_PORT}/callback"
    success_url = f"http://localhost:{FLASK_CALLBACK_PORT}/success"
    cancel_url = f"http://localhost:{FLASK_CALLBACK_PORT}/cancel"
    html_content = f'''
    <html>
    <head><meta charset="UTF-8"><title>FaucetPay Deposit</title>
    <style>body{{font-family:Arial;text-align:center;padding:50px;}}
    .container{{max-width:600px;margin:0 auto;}}
    .info{{background:#f0f8ff;padding:20px;border-radius:10px;margin-bottom:20px;}}
    </style></head>
    <body><div class="container"><h1>FaucetPay Deposit</h1>
    <div class="info"><p>Částka k vkladu: <strong>{amount_usdt:.8f} USDT</strong></p>
    <p>Účet: <strong>{FAUCETPAY_MERCHANT_ID}</strong></p></div>
    <form id="depositForm" action="https://faucetpay.io/merchant/webscr" method="post">
    <input type="hidden" name="merchant_username" value="{FAUCETPAY_MERCHANT_ID}">
    <input type="hidden" name="item_description" value="Nákup HAV">
    <input type="hidden" name="amount1" value="{amount_usdt:.8f}">
    <input type="hidden" name="currency1" value="USDT">
    <input type="hidden" name="currency2" value="">
    <input type="hidden" name="custom" value="{custom_tag}">
    <input type="hidden" name="callback_url" value="{callback_url}">
    <input type="hidden" name="success_url" value="{success_url}">
    <input type="hidden" name="cancel_url" value="{cancel_url}">
    <input type="submit" value="Pokračovat na FaucetPay" style="background:#ff7e05;color:white;border:none;padding:15px 30px;font-size:18px;border-radius:25px;cursor:pointer;font-weight:bold;">
    </form>
    <p style="margin-top:20px;color:#666;">Pokud nejste přesměrováni, klikněte na tlačítko.</p>
    <p style="color:#999;font-size:12px;">Po dokončení platby se automaticky přičtou HAV.</p>
    </div>
    
    <script>setTimeout(function(){{document.getElementById('depositForm').submit();}},1000);</script>
    </body></html>
    '''
    fd, path = tempfile.mkstemp(suffix='.html', prefix='faucetpay_deposit_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html_content)
    webbrowser.open('file://' + path)
    return True, f"Otevřen formulář pro vklad {amount_usdt:.8f} USDT.\nPo dokončení platby se automaticky provedou HAV."

def faucetpay_withdraw(amount_usdt, to_address, custom_tag=""):
    callback_url = f"http://localhost:{FLASK_CALLBACK_PORT}/callback"
    success_url = f"http://localhost:{FLASK_CALLBACK_PORT}/success"
    cancel_url = f"http://localhost:{FLASK_CALLBACK_PORT}/cancel"
    html_content = f'''
    <html>
    <head><meta charset="UTF-8"><title>FaucetPay Withdraw</title>
    <style>body{{font-family:Arial;text-align:center;padding:50px;}}
    .container{{max-width:600px;margin:0 auto;}}
    .info{{background:#f0f8ff;padding:20px;border-radius:10px;margin-bottom:20px;}}
    .address{{background:#eef2f7;padding:10px;border-radius:8px;font-family:monospace;}}
    </style></head>
    <body><div class="container"><h1>FaucetPay Withdraw</h1>
    <div class="info"><p>Částka k výběru: <strong>{amount_usdt:.8f} USDT</strong></p>
    <p>Cílová adresa: <br><span class="address">{to_address}</span></p>
    <p>Účet: <strong>{FAUCETPAY_MERCHANT_ID}</strong></p></div>
    <form id="withdrawForm" action="https://faucetpay.io/merchant/webscr" method="post">
    <input type="hidden" name="merchant_username" value="{FAUCETPAY_MERCHANT_ID}">
    <input type="hidden" name="item_description" value="Prodej HAV">
    <input type="hidden" name="amount1" value="{amount_usdt:.8f}">
    <input type="hidden" name="currency1" value="USDT">
    <input type="hidden" name="currency2" value="">
    <input type="hidden" name="custom" value="{custom_tag}">
    <input type="hidden" name="callback_url" value="{callback_url}">
    <input type="hidden" name="success_url" value="{success_url}">
    <input type="hidden" name="cancel_url" value="{cancel_url}">
    <input type="submit" value="Pokračovat na FaucetPay" style="background:#ff7e05;color:white;border:none;padding:15px 30px;font-size:18px;border-radius:25px;cursor:pointer;font-weight:bold;">
    </form>
    <p style="margin-top:20px;color:#666;">Pokud nejste přesměrováni, klikněte na tlačítko.</p>
    <p style="color:#999;font-size:12px;">Po dokončení výběru se automaticky odečtou HAV.</p>
    </div>
    <script>setTimeout(function(){{document.getElementById('withdrawForm').submit();}},1000);</script>
    </body></html>
    '''
    fd, path = tempfile.mkstemp(suffix='.html', prefix='faucetpay_withdraw_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html_content)
    webbrowser.open('file://' + path)
    return True, f"Otevřen formulář pro výběr {amount_usdt:.8f} USDT na adresu {to_address}.\nPo dokončení se automaticky odečtou HAV."

def faucetpay_get_buy_rate():
    return BASE_RATE * (1 + SPREAD)

def faucetpay_get_sell_rate():
    return BASE_RATE * (1 - SPREAD)

# ============================================================
#  UKLÁDÁNÍ A NAČÍTÁNÍ STAVU
# ============================================================

def save_state():
    data = {
        'wallet_balance': state.wallet_balance,
        'total_supply': state.total_supply,
        'block_height': state.block_height,
        'difficulty': state.difficulty,
        'block_reward': state.block_reward,
        'transactions': state.transactions,
        'wallet_address': state.wallet_address,
        'reward_distribution': state.reward_distribution,
        'usdt_balance': state.usdt_balance,
        'pool': state.pool,
        'price_history': list(state.price_history),
        'blockchain': state.blockchain,
        'devices': [{'name': d['name'], 'port': d.get('port', 'N/A'), 'connected': d['connected']} 
                    for d in state.devices if d.get('connected')],
        'positions': state.positions,
        'trade_history': state.trade_history,
        'leverage': state.leverage
    }
    try:
        tmp_file = STATE_FILE + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp_file, STATE_FILE)
    except Exception as e:
        print(f"Chyba při ukládání stavu: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        state.wallet_balance = data.get('wallet_balance', 0.0)
        state.total_supply = data.get('total_supply', 0.0)
        state.block_height = data.get('block_height', 0)
        state.difficulty = data.get('difficulty', 0.5)
        state.block_reward = data.get('block_reward', 1.0)
        state.transactions = data.get('transactions', [])
        state.wallet_address = data.get('wallet_address', state._gen_address())
        state.reward_distribution = data.get('reward_distribution', {})
        state.usdt_balance = data.get('usdt_balance', 0.0)
        state.pool = data.get('pool', state.pool)
        state.price_history = deque(data.get('price_history', [BASE_RATE]*50), maxlen=50)
        state.blockchain = data.get('blockchain', [])
        devices_data = data.get('devices', [])
        for dev_info in devices_data:
            existing = next((d for d in state.devices if d['name'] == dev_info['name']), None)
            if not existing:
                state.devices.append({
                    'name': dev_info['name'],
                    'port': dev_info.get('port', 'N/A'),
                    'connected': False,
                    'thread': None,
                    'network': dev_info.get('port', '').startswith('tcp:')
                })
        state.positions = data.get('positions', [])
        state.trade_history = data.get('trade_history', [])
        state.leverage = data.get('leverage', 1)
        print(f"Stav načten: {state.block_height} bloků, {state.wallet_balance:.2f} HAV, USDT: {state.usdt_balance:.2f}")
    except Exception as e:
        print(f"Chyba při načítání stavu: {e}")

# ============================================================
#  STAV APLIKACE
# ============================================================

class HavirovState:
    def __init__(self):
        self.devices = []
        self.blockchain = []
        self.wallet_balance = 0.0
        self.total_supply = 0.0
        self.block_height = 0
        self.difficulty = 0.5
        self.block_reward = 1.0
        self.transactions = []
        self.wallet_address = self._gen_address()
        self.reward_distribution = {}
        self.usdt_balance = 0.0

        self.pool = {
            'total_liquidity': 0.0,
            'user_stake': 0.0,
            'stake_time': None,
            'reward': 0.0,
            'claimed': False,
            'lock_period': 7,
            'apy': 7.0,
            'history': []
        }

        self.price_history = deque(maxlen=50)
        for _ in range(50):
            self.price_history.append(BASE_RATE)

        # Trading vlastnosti – používáme USDT z účtu FaucetPay
        self.positions = []          # otevřené pozice
        self.trade_history = []      # historie obchodů
        self.leverage = 1            # páka

        self._lock = threading.Lock()

    def _gen_address(self):
        return '0x' + ''.join(random.choice('0123456789abcdef') for _ in range(40))

    def get_pool_reward(self):
        if not self.pool['stake_time'] or self.pool['user_stake'] == 0:
            return 0.0
        elapsed = (time.time() - self.pool['stake_time']) / (24 * 3600)
        if elapsed >= self.pool['lock_period']:
            return self.pool['user_stake'] * (self.pool['apy'] / 100.0)
        return 0.0

    def get_pool_status(self):
        if not self.pool['stake_time'] or self.pool['user_stake'] == 0:
            return 'Žádný aktivní stake'
        elapsed = (time.time() - self.pool['stake_time']) / (24 * 3600)
        if elapsed >= self.pool['lock_period']:
            return 'Odemčeno'
        return 'Uzamčeno'

    def get_pool_countdown(self):
        if not self.pool['stake_time'] or self.pool['user_stake'] == 0:
            return '—'
        lock_end = self.pool['stake_time'] + self.pool['lock_period'] * 24 * 3600
        remaining = lock_end - time.time()
        if remaining <= 0:
            return 'Odemčeno!'
        days = int(remaining // (24 * 3600))
        hours = int((remaining % (24 * 3600)) // 3600)
        mins = int((remaining % 3600) // 60)
        secs = int(remaining % 60)
        return f'{days}d {hours}h {mins}m {secs}s'

state = HavirovState()

# ============================================================
#  POMOCNÉ FUNKCE
# ============================================================

def format_time(ts):
    return datetime.fromtimestamp(ts).strftime('%H:%M:%S')

def format_date(ts):
    return datetime.fromtimestamp(ts).strftime('%d.%m.%Y %H:%M:%S')

def random_hash():
    return '0x' + ''.join(random.choice('0123456789abcdef') for _ in range(8))

def apply_fee(amount):
    return amount * (1 - TRANSACTION_FEE)

# ============================================================
#  GRAF (MATPLOTLIB)
# ============================================================

class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=3, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

    def clear(self):
        self.ax.clear()

# ============================================================
#  JÁDRO TĚŽBY (SAMOSTATNÉ VLÁKNO)
# ============================================================

class MiningCore(QThread):
    new_block = pyqtSignal(dict)
    new_transaction = pyqtSignal(dict)
    devices_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = True
        self._queue = Queue()
        self._lock = threading.Lock()

    def stop(self):
        self._running = False
        self.wait()

    def enqueue_data(self, device_name, line):
        self._queue.put((device_name, line))

    def run(self):
        while self._running:
            try:
                for _ in range(10):
                    item = self._queue.get_nowait()
                    self._process_line(item[0], item[1])
                    self._queue.task_done()
            except Empty:
                pass
            time.sleep(0.01)

    def _process_line(self, device_name, line):
        if 'BLOCK FOUND!' in line:
            reward = state.block_reward
            with state._lock:
                state.wallet_balance += reward
                state.total_supply += reward
                state.block_height += 1

                if device_name in state.reward_distribution:
                    state.reward_distribution[device_name] += reward
                else:
                    state.reward_distribution[device_name] = reward

                block = {
                    'height': state.block_height,
                    'hash': random_hash(),
                    'miner': device_name,
                    'reward': reward,
                    'tx_count': 1,
                    'timestamp': time.time()
                }
                state.blockchain.insert(0, block)
                if len(state.blockchain) > 20:
                    state.blockchain.pop()

                tx = {
                    'type': 'Odměna z těžby',
                    'amount': reward,
                    'address': device_name,
                    'time': datetime.now().strftime('%H:%M:%S')
                }
                state.transactions.insert(0, tx)
                if len(state.transactions) > 20:
                    state.transactions.pop()

            save_state()
            self.new_block.emit(block)
            self.new_transaction.emit(tx)

# ============================================================
#  TCP SERVER PRO PŘÍJEM DAT Z MINERŮ (port 9997)
# ============================================================

class TcpServer(QThread):
    data_received = pyqtSignal(str, str)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)
    devices_changed = pyqtSignal()

    def __init__(self, host='0.0.0.0', port=9997):
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._clients = {}
        self._client_sockets = []
        self._lock = threading.Lock()
        self.server_socket = None

    def stop(self):
        self._running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        self.wait()

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.server_socket.setblocking(False)
            print(f"[TCP] Server naslouchá na {self.host}:{self.port}")

            while self._running:
                rlist = [self.server_socket] + self._client_sockets
                try:
                    readable, _, _ = select.select(rlist, [], [], 1.0)
                except Exception as e:
                    if self._running:
                        print(f"[TCP] Chyba select: {e}")
                    continue

                for sock in readable:
                    if sock is self.server_socket:
                        try:
                            conn, addr = self.server_socket.accept()
                            conn.setblocking(False)
                            with self._lock:
                                self._client_sockets.append(conn)
                                self._clients[conn] = None
                            thread = threading.Thread(target=self._handle_client, args=(conn, addr))
                            thread.daemon = True
                            thread.start()
                        except Exception as e:
                            print(f"[TCP] Chyba při accept: {e}")
                    else:
                        try:
                            data = sock.recv(4096)
                            if not data:
                                self._close_client(sock)
                                continue
                            lines = data.decode('utf-8', errors='ignore').splitlines()
                            for line in lines:
                                line = line.strip()
                                if line:
                                    with self._lock:
                                        device_name = self._clients.get(sock, 'Neznámý')
                                    if device_name:
                                        self.data_received.emit(device_name, line)
                                    else:
                                        if line.startswith('DEVICE:'):
                                            device_name = line.split(':', 1)[1].strip()
                                            with self._lock:
                                                self._clients[sock] = device_name
                                            self.client_connected.emit(device_name)
                                            self.devices_changed.emit()
                                            with state._lock:
                                                existing = next((d for d in state.devices if d['name'] == device_name), None)
                                                if not existing:
                                                    state.devices.append({
                                                        'name': device_name,
                                                        'port': f'tcp:{addr[0]}:{addr[1]}',
                                                        'connected': True,
                                                        'thread': None,
                                                        'network': True
                                                    })
                                                else:
                                                    existing['connected'] = True
                                                save_state()
                        except socket.error as e:
                            error_code = e.errno if hasattr(e, 'errno') else None
                            if error_code in (errno.ECONNRESET, errno.EPIPE):
                                print(f"[TCP] Klient {sock.getpeername()} resetoval spojení")
                            elif error_code == errno.ETIMEDOUT:
                                print(f"[TCP] Timeout u klienta {sock.getpeername()}")
                            else:
                                print(f"[TCP] Chyba při čtení od {sock.getpeername()}: {e}")
                            self._close_client(sock)
        except Exception as e:
            print(f"[TCP] Chyba v hlavní smyčce: {e}")
            traceback.print_exc()
        finally:
            if self.server_socket:
                self.server_socket.close()

    def _handle_client(self, conn, addr):
        while self._running:
            time.sleep(0.1)
            with self._lock:
                device_name = self._clients.get(conn)
                if device_name:
                    self._send_current_state(conn, device_name)
                    break

    def _send_current_state(self, conn, device_name):
        with state._lock:
            for dev, val in state.device_data.items():
                if dev != device_name:
                    try:
                        conn.sendall(f"STATE: {dev}: {val}\n".encode('utf-8'))
                    except Exception as e:
                        print(f"[TCP] Chyba při odesílání stavu: {e}")
                        break

    def _close_client(self, sock):
        with self._lock:
            if sock in self._client_sockets:
                self._client_sockets.remove(sock)
            device_name = self._clients.pop(sock, None)
        try:
            sock.close()
        except:
            pass
        if device_name:
            self.client_disconnected.emit(device_name)
            self.devices_changed.emit()
            with state._lock:
                dev = next((d for d in state.devices if d['name'] == device_name), None)
                if dev:
                    dev['connected'] = False
                save_state()

    def send_to_all(self, msg, exclude=None):
        with self._lock:
            for sock, name in self._clients.items():
                if name and name != exclude:
                    try:
                        sock.sendall((msg + '\n').encode('utf-8'))
                    except:
                        pass

    def broadcast_device_data(self, device_name, value, sender=None):
        msg = f"UPDATE: {device_name}: {value}"
        self.send_to_all(msg, exclude=sender)

state.device_data = {}

# ============================================================
#  SÉRIOVÝ READER
# ============================================================

class SerialReaderThread(QThread):
    error_occurred = pyqtSignal(str)
    data_received = pyqtSignal(str, str)

    def __init__(self, port, baudrate=115200, device_name=None, core=None):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.device_name = device_name or port
        self._running = True
        self.ser = None
        self.core = core

    def run(self):
        while self._running:
            try:
                self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
                print(f"[SER] Připojeno k {self.port} jako {self.device_name}")
                while self._running:
                    if self.ser.in_waiting:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        if line:
                            if self.core:
                                self.core.enqueue_data(self.device_name, line)
                            self.data_received.emit(self.device_name, line)
                    else:
                        time.sleep(0.01)
            except serial.SerialException as e:
                print(f"[SER] Chyba sériového portu {self.port}: {e}")
                self.error_occurred.emit(str(e))
                time.sleep(5)
            except Exception as e:
                print(f"[SER] Neočekávaná chyba: {e}")
                self.error_occurred.emit(str(e))
                time.sleep(5)
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        print(f"[SER] Reader pro {self.device_name} ukončen.")

    def stop(self):
        self._running = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        self.wait()

# ============================================================
#  HLAVNÍ OKNO
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Havirov Coin - Ostrá verze')
        self.setMinimumSize(1200, 800)

        load_state()

        self.mining_core = MiningCore()
        self.mining_core.new_block.connect(self._on_new_block)
        self.mining_core.new_transaction.connect(self._on_new_transaction)
        self.mining_core.devices_changed.connect(self._on_devices_changed)
        self.mining_core.start()

        self.tcp_server = TcpServer(host='0.0.0.0', port=9997)
        self.tcp_server.data_received.connect(self._on_tcp_data)
        self.tcp_server.devices_changed.connect(self._on_devices_changed)
        self.tcp_server.client_connected.connect(self._on_client_connected)
        self.tcp_server.client_disconnected.connect(self._on_client_disconnected)
        self.tcp_server.start()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel('Havirov Coin')
        title.setStyleSheet('color: #ff7e05;')
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel(datetime.now().strftime('%H:%M:%S')))
        main_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet('''
            QTabBar::tab { padding: 15px 30px; border-radius: 20px; font-weight: bold; font-size: 28px; }
            QTabBar::tab:selected { background: #ff7e05; color: white; }
            QTabBar::tab:hover { background: #e9edf4; }
        ''')
        main_layout.addWidget(self.tabs)

        self.tab_dashboard = DashboardTab()
        self.tab_mining = MiningTab(self)
        self.tab_wallet = WalletTab()
        self.tab_swap = SwapTab()
        self.tab_pool = PoolTab()
        self.tab_trading = TradingTab()
        self.tab_stats = StatsTab()
        self.tab_blockchain = BlockchainTab()

        self.tabs.addTab(self.tab_dashboard, 'Dashboard')
        self.tabs.addTab(self.tab_mining, 'Mining')
        self.tabs.addTab(self.tab_wallet, 'Peněženka')
        self.tabs.addTab(self.tab_swap, 'Swap')
        self.tabs.addTab(self.tab_pool, 'Pool')
        self.tabs.addTab(self.tab_trading, 'Trading')
        self.tabs.addTab(self.tab_stats, 'Statistiky')
        self.tabs.addTab(self.tab_blockchain, 'Blockchain')

        footer = QLabel('Havirov Coin · Ostrá verze · Připojení RPI PICO přes sériový port nebo TCP')
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet('color: #7b8a9b; padding: 8px;')
        main_layout.addWidget(footer)

        self.timer = QTimer()
        self.timer.timeout.connect(self._periodic_update)
        self.timer.start(1000)

        self.showMaximized()

    def _periodic_update(self):
        self.tab_wallet.refresh()
        self.tab_pool.refresh()
        self.tab_stats.refresh()
        self.tab_blockchain.refresh()

    def _on_new_block(self, block):
        self.tab_dashboard.refresh()
        self.tab_blockchain.refresh()
        self.tab_wallet.refresh()
        self.tab_stats.refresh()

    def _on_new_transaction(self, tx):
        self.tab_wallet.refresh()
        save_state()

    def _on_devices_changed(self):
        self.tab_mining.refresh_device_table()
        self.tab_dashboard.refresh()
        save_state()

    def _on_tcp_data(self, device_name, line):
        with state._lock:
            state.device_data[device_name] = line
        self.tcp_server.broadcast_device_data(device_name, line, sender=device_name)
        self.mining_core.enqueue_data(device_name, line)
        self.tab_mining.add_raw_line(device_name, line)

    def _on_client_connected(self, device_name):
        self._on_devices_changed()

    def _on_client_disconnected(self, device_name):
        self._on_devices_changed()

    def closeEvent(self, event):
        save_state()
        self.mining_core.stop()
        self.tcp_server.stop()
        for dev in state.devices:
            if dev.get('thread'):
                dev['thread'].stop()
        event.accept()

# ============================================================
#  DASHBOARD TAB
# ============================================================

class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        card_grid = QGridLayout()
        card_grid.setSpacing(10)
        self.cards = {}
        labels = [
            ('price', 'Aktuální cena', f'{BASE_RATE:.12f} USDT'),
            ('wallet_balance', 'Můj zůstatek', '0 HAV'),
            ('active_miners', 'Aktivních zařízení', '0'),
            ('pool_tvl', 'Celkem v Poolu', '0 HAV')
        ]
        for i, (key, title, default) in enumerate(labels):
            card = self._make_card(title, default)
            row = i // 2
            col = i % 2
            card_grid.addWidget(card, row, col)
            self.cards[key] = card
        layout.addLayout(card_grid)

        graph_layout = QHBoxLayout()
        graph_layout.setSpacing(10)

        left = QGroupBox('Cena HAV / USDT (24h)')
        left.setStyleSheet('QGroupBox { font-weight: bold; padding: 10px; }')
        left_layout = QVBoxLayout(left)
        self.price_canvas = MplCanvas(self, width=8, height=3)
        left_layout.addWidget(self.price_canvas)
        graph_layout.addWidget(left)

        layout.addLayout(graph_layout)

        dist_group = QGroupBox('Distribuce odměn')
        dist_group.setStyleSheet('QGroupBox { font-weight: bold; padding: 10px; }')
        dist_layout = QHBoxLayout(dist_group)

        self.reward_table = QTableWidget()
        self.reward_table.setColumnCount(3)
        self.reward_table.setHorizontalHeaderLabels(['Miner', 'Odměna (HAV)', 'Podíl'])
        self.reward_table.horizontalHeader().setStretchLastSection(True)
        self.reward_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        dist_layout.addWidget(self.reward_table, 2)

        self.reward_pie_canvas = MplCanvas(self, width=3, height=2.5)
        dist_layout.addWidget(self.reward_pie_canvas, 1)

        layout.addWidget(dist_group)
        layout.setStretchFactor(dist_group, 1)

        self.refresh()

    def _make_card(self, title, default):
        card = QFrame()
        card.setStyleSheet('QFrame { background: white; border-radius: 12px; padding: 10px 16px; border: 1px solid #e9edf4; }')
        layout = QVBoxLayout(card)
        layout.setSpacing(4)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet('color: #7b8a9b;')
        layout.addWidget(lbl_title)
        val_label = QLabel(default)
        layout.addWidget(val_label)
        sub_label = QLabel('—')
        sub_label.setStyleSheet('color: #7b8a9b;')
        layout.addWidget(sub_label)

        card._val_label = val_label
        card._sub_label = sub_label
        return card

    def refresh(self):
        active = sum(1 for d in state.devices if d['connected'])
        current_price = state.price_history[-1] if state.price_history else BASE_RATE

        self.cards['price']._val_label.setText(f'{current_price:.12f} USDT')
        self.cards['price']._sub_label.setText(f'nákup {current_price*(1+SPREAD):.12f} / prodej {current_price*(1-SPREAD):.12f}')

        self.cards['wallet_balance']._val_label.setText(f'{state.wallet_balance:.2f} HAV')
        czk_value = state.wallet_balance * current_price * CZK_RATE
        self.cards['wallet_balance']._sub_label.setText(f'{czk_value:.8f} CZK')

        self.cards['active_miners']._val_label.setText(str(active))
        self.cards['active_miners']._sub_label.setText(f'{active} zařízení připojeno' if active else '—')
        self.cards['pool_tvl']._val_label.setText(f'{state.pool["total_liquidity"]:.2f} HAV')
        self.cards['pool_tvl']._sub_label.setText(f'APY {state.pool["apy"]}% / 7d')

        self._update_price_chart()
        self._update_reward_table()

    def _update_price_chart(self):
        data = list(state.price_history)
        if len(data) < 2:
            data = [BASE_RATE] * 50
        self.price_canvas.ax.clear()
        self.price_canvas.ax.plot(data, color='#ff7e05', linewidth=2)
        self.price_canvas.ax.fill_between(range(len(data)), data, color='#ff7e05', alpha=0.15)
        self.price_canvas.ax.grid(True, color='#e9edf4', linestyle='-', linewidth=0.5)
        self.price_canvas.ax.set_ylabel('USDT')
        self.price_canvas.draw()

    def _update_reward_table(self):
        dist = state.reward_distribution
        entries = list(dist.items())
        if not entries:
            self.reward_table.setRowCount(0)
            self._update_pie_chart([])
            return
        total = sum(v for _, v in entries)
        self.reward_table.setRowCount(len(entries))
        for i, (name, reward) in enumerate(entries):
            self.reward_table.setItem(i, 0, QTableWidgetItem(name))
            self.reward_table.setItem(i, 1, QTableWidgetItem(f'{reward:.2f}'))
            share = (reward / total * 100) if total > 0 else 0
            self.reward_table.setItem(i, 2, QTableWidgetItem(f'{share:.1f} %'))
        self.reward_table.resizeColumnsToContents()
        self._update_pie_chart(entries)

    def _update_pie_chart(self, entries):
        self.reward_pie_canvas.ax.clear()
        if not entries:
            self.reward_pie_canvas.ax.text(0.5, 0.5, 'Žádná data', ha='center', va='center')
            self.reward_pie_canvas.draw()
            return
        labels = [e[0] for e in entries]
        values = [e[1] for e in entries]
        colors = ['#ff7e05', '#0d6efd', '#198754', '#ffc107', '#6f42c1', '#dc3545']
        self.reward_pie_canvas.ax.pie(values, labels=labels, colors=colors[:len(values)], autopct='%1.0f%%', startangle=90)
        self.reward_pie_canvas.ax.axis('equal')
        self.reward_pie_canvas.draw()

# ============================================================
#  MINING TAB – BEZ CPU TLAČÍTEK
# ============================================================

class MiningTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        header = QHBoxLayout()
        header.addWidget(QLabel('Připojená zařízení'))
        header.addStretch()
        self.miner_count_label = QLabel('0')
        self.miner_count_label.setStyleSheet('background: #6c757d; color: white; border-radius: 12px; padding: 4px 18px;')
        header.addWidget(self.miner_count_label)
        left_layout.addLayout(header)

        self.device_table = QTableWidget()
        self.device_table.setColumnCount(3)
        self.device_table.setHorizontalHeaderLabels(['Zařízení', 'Port', 'Stav'])
        self.device_table.horizontalHeader().setStretchLastSection(True)
        self.device_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.device_table)
        layout.addWidget(left, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        right_layout.addWidget(QLabel('Surová data z HW'))

        self.raw_data_display = QTextEdit()
        self.raw_data_display.setReadOnly(True)
        self.raw_data_display.setFont(QFont('Courier New', 18))
        self.raw_data_display.setStyleSheet('background: #1e1e1e; color: #d4d4d4; border-radius: 8px; padding: 8px;')
        right_layout.addWidget(self.raw_data_display)

        ctrl_layout = QHBoxLayout()
        self.connect_btn = QPushButton('Připojit zařízení (sériový port)')
        self.connect_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7e05, stop:1 #f97316);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e66e00, stop:1 #e06600);
            }
            QPushButton:pressed {
                background: #cc5c00;
            }
        ''')
        self.connect_btn.clicked.connect(self._connect_device)
        ctrl_layout.addWidget(self.connect_btn)

        self.connect_all_btn = QPushButton('Připojit všechny RPI PICO')
        self.connect_all_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d6efd, stop:1 #0b5ed7);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0b5ed7, stop:1 #0a58ca);
            }
            QPushButton:pressed {
                background: #084298;
            }
        ''')
        self.connect_all_btn.clicked.connect(self._connect_all_devices)
        ctrl_layout.addWidget(self.connect_all_btn)

        self.disconnect_btn = QPushButton('Odpojit vše')
        self.disconnect_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc3545, stop:1 #c82333);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c82333, stop:1 #b02a37);
            }
            QPushButton:pressed {
                background: #a71d2a;
            }
        ''')
        self.disconnect_btn.clicked.connect(self._disconnect_all)
        self.disconnect_btn.hide()
        ctrl_layout.addWidget(self.disconnect_btn)

        self.clear_btn = QPushButton('Vymazat data')
        self.clear_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6c757d, stop:1 #5a6268);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6268, stop:1 #4e555b);
            }
            QPushButton:pressed {
                background: #42484e;
            }
        ''')
        self.clear_btn.clicked.connect(lambda: self.raw_data_display.clear())
        ctrl_layout.addWidget(self.clear_btn)

        right_layout.addLayout(ctrl_layout)

        self.device_status = QLabel('Stav: 0 zařízení připojeno')
        self.device_status.setStyleSheet('background: #cfe2ff; border-radius: 8px; padding: 8px;')
        right_layout.addWidget(self.device_status)

        layout.addWidget(right, 2)

        self.reader_threads = []
        self._raw_buffer = []
        self._raw_timer = QTimer()
        self._raw_timer.timeout.connect(self._flush_raw_buffer)
        self._raw_timer.start(500)

        self.refresh_device_table()

    def _connect_device(self):
        ports = serial.tools.list_ports.comports()
        if not ports:
            QMessageBox.warning(self, 'Žádné porty', 'Nebyl nalezen žádný sériový port.')
            return
        items = [f"{p.device} - {p.description}" for p in ports]
        port, ok = QInputDialog.getItem(self, 'Vyberte sériový port', 'Dostupné porty:', items, 0, False)
        if not ok or not port:
            return
        device_name = port.split(' - ')[0] if ' - ' in port else port

        if any(d['port'] == device_name for d in state.devices):
            QMessageBox.information(self, 'Již připojeno', f'Zařízení {device_name} je již připojeno.')
            return

        dev = {
            'name': f'RPI {device_name}',
            'port': device_name,
            'connected': True,
            'thread': None,
            'network': False
        }
        state.devices.append(dev)

        thread = SerialReaderThread(device_name, 115200, dev['name'], self.main_window.mining_core)
        thread.error_occurred.connect(lambda err: self._serial_error(err, dev))
        thread.data_received.connect(self._on_serial_data)
        thread.start()
        dev['thread'] = thread
        self.reader_threads.append(thread)

        self.main_window.mining_core.devices_changed.emit()
        self.refresh_device_table()
        save_state()
        QMessageBox.information(self, 'Připojeno', f'Zařízení {device_name} bylo připojeno.')

    def _connect_all_devices(self):
        ports = serial.tools.list_ports.comports()
        if not ports:
            QMessageBox.warning(self, 'Žádné porty', 'Nebyl nalezen žádný sériový port.')
            return

        connected_count = 0
        for p in ports:
            port = p.device
            if any(d['port'] == port for d in state.devices):
                continue

            dev = {
                'name': f'RPI {port}',
                'port': port,
                'connected': True,
                'thread': None,
                'network': False
            }
            state.devices.append(dev)

            thread = SerialReaderThread(port, 115200, dev['name'], self.main_window.mining_core)
            thread.error_occurred.connect(lambda err, d=dev: self._serial_error(err, d))
            thread.data_received.connect(self._on_serial_data)
            thread.start()
            dev['thread'] = thread
            self.reader_threads.append(thread)
            connected_count += 1

        if connected_count > 0:
            self.main_window.mining_core.devices_changed.emit()
            self.refresh_device_table()
            save_state()
            QMessageBox.information(self, 'Připojeno', f'Připojeno {connected_count} zařízení.')
        else:
            QMessageBox.information(self, 'Žádná nová zařízení', 'Všechny dostupné porty jsou již připojeny.')

    def _on_serial_data(self, device_name, line):
        with state._lock:
            state.device_data[device_name] = line
        if self.main_window:
            self.main_window.tcp_server.broadcast_device_data(device_name, line, sender=None)
        self.add_raw_line(device_name, line)

    def _serial_error(self, error, device):
        QMessageBox.warning(self, 'Chyba sériového portu', f'Chyba na zařízení {device["port"]}: {error}')
        device['connected'] = False
        if device['thread']:
            device['thread'].stop()
            device['thread'] = None
        self.main_window.mining_core.devices_changed.emit()
        self.refresh_device_table()
        save_state()

    def _disconnect_all(self):
        for dev in state.devices:
            if dev.get('thread'):
                dev['thread'].stop()
                dev['thread'] = None
            dev['connected'] = False
        state.devices.clear()
        self.reader_threads.clear()
        self.main_window.mining_core.devices_changed.emit()
        self.refresh_device_table()
        if self.main_window:
            self.main_window.tab_dashboard.refresh()
        save_state()

    def refresh_device_table(self):
        active = [d for d in state.devices if d['connected']]
        self.miner_count_label.setText(str(len(active)))
        self.device_status.setText(f'Stav: {len(active)} zařízení připojeno')
        self.device_status.setStyleSheet('background: #d1e7dd; border-radius: 8px; padding: 8px;' if active else 'background: #cfe2ff; border-radius: 8px; padding: 8px;')
        self.disconnect_btn.setVisible(bool(active))

        self.device_table.setUpdatesEnabled(False)
        self.device_table.setRowCount(len(active))
        for i, d in enumerate(active):
            self.device_table.setItem(i, 0, QTableWidgetItem(d['name']))
            self.device_table.setItem(i, 1, QTableWidgetItem(d.get('port', 'N/A')))
            self.device_table.setItem(i, 2, QTableWidgetItem('🟢 Aktivní'))
        self.device_table.resizeColumnsToContents()
        self.device_table.setUpdatesEnabled(True)

    def add_raw_line(self, device_name, line):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self._raw_buffer.append(f'[{timestamp}] [{device_name}] {line}')
        if len(self._raw_buffer) > 500:
            self._flush_raw_buffer()

    def _flush_raw_buffer(self):
        if not self._raw_buffer:
            return
        lines = self._raw_buffer
        self._raw_buffer = []
        for line in lines[:100]:
            self.raw_data_display.append(line)
        if len(lines) > 100:
            self._raw_buffer.extend(lines[100:])
        cursor = self.raw_data_display.textCursor()
        cursor.movePosition(cursor.End)
        self.raw_data_display.setTextCursor(cursor)

# ============================================================
#  WALLET TAB
# ============================================================

class WalletTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setAlignment(Qt.AlignTop)
        left_layout.setSpacing(10)

        left_layout.addWidget(QLabel('Moje peněženka'))

        addr_layout = QHBoxLayout()
        self.address_label = QLabel(state.wallet_address)
        self.address_label.setStyleSheet('background: #eef2f7; padding: 6px 18px; border-radius: 20px; font-family: monospace;')
        self.address_label.setWordWrap(True)
        addr_layout.addWidget(self.address_label)
        copy_btn = QPushButton('Kopírovat')
        copy_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d6efd, stop:1 #0b5ed7);
                color: white; font-weight: bold;
                padding: 10px 20px; border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0b5ed7, stop:1 #0a58ca);
            }
            QPushButton:pressed {
                background: #084298;
            }
        ''')
        copy_btn.clicked.connect(self._copy_address)
        addr_layout.addWidget(copy_btn)
        self.copy_feedback = QLabel('')
        self.copy_feedback.setStyleSheet('color: green;')
        addr_layout.addWidget(self.copy_feedback)
        addr_layout.addStretch()
        left_layout.addLayout(addr_layout)

        new_addr_btn = QPushButton('Nová adresa')
        new_addr_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6c757d, stop:1 #5a6268);
                color: white; font-weight: bold;
                padding: 10px 20px; border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6268, stop:1 #4e555b);
            }
            QPushButton:pressed {
                background: #42484e;
            }
        ''')
        new_addr_btn.clicked.connect(self._new_address)
        left_layout.addWidget(new_addr_btn)

        self.balance_label = QLabel('0.00 HAV')
        left_layout.addWidget(self.balance_label)

        current_price = state.price_history[-1] if state.price_history else BASE_RATE
        usdt_value = state.wallet_balance * current_price
        self.usd_label = QLabel(f'≈ {usdt_value:.12f} USDT')
        self.usd_label.setStyleSheet('color: #198754;')
        left_layout.addWidget(self.usd_label)

        send_btn = QPushButton('Odeslat HAV')
        send_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7e05, stop:1 #f97316);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e66e00, stop:1 #e06600);
            }
            QPushButton:pressed {
                background: #cc5c00;
            }
        ''')
        send_btn.clicked.connect(self._show_send_dialog)
        left_layout.addWidget(send_btn)

        layout.addWidget(left, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel('Historie transakcí'))

        self.tx_table = QTableWidget()
        self.tx_table.setColumnCount(4)
        self.tx_table.setHorizontalHeaderLabels(['Typ', 'Částka', 'Adresa', 'Čas'])
        self.tx_table.horizontalHeader().setStretchLastSection(True)
        self.tx_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.tx_table)

        layout.addWidget(right, 2)
        self.refresh()

    def refresh(self):
        self.address_label.setText(state.wallet_address)
        self.balance_label.setText(f'{state.wallet_balance:.2f} HAV')
        current_price = state.price_history[-1] if state.price_history else BASE_RATE
        usdt = state.wallet_balance * current_price
        self.usd_label.setText(f'≈ {usdt:.12f} USDT')

        self.tx_table.setUpdatesEnabled(False)
        self.tx_table.setRowCount(len(state.transactions))
        for i, tx in enumerate(state.transactions):
            self.tx_table.setItem(i, 0, QTableWidgetItem(tx['type']))
            self.tx_table.setItem(i, 1, QTableWidgetItem(f'{tx["amount"]:.2f} HAV'))
            self.tx_table.setItem(i, 2, QTableWidgetItem(tx['address']))
            self.tx_table.setItem(i, 3, QTableWidgetItem(tx['time']))
        self.tx_table.resizeColumnsToContents()
        self.tx_table.setUpdatesEnabled(True)

    def _copy_address(self):
        QApplication.clipboard().setText(state.wallet_address)
        self.copy_feedback.setText('Zkopírováno!')
        QTimer.singleShot(3000, lambda: self.copy_feedback.setText(''))

    def _new_address(self):
        state.wallet_address = state._gen_address()
        self.address_label.setText(state.wallet_address)
        self.copy_feedback.setText('Nová adresa vytvořena')
        QTimer.singleShot(3000, lambda: self.copy_feedback.setText(''))
        save_state()

    def _show_send_dialog(self):
        dialog = SendDialog(self)
        if dialog.exec_():
            addr, amount = dialog.get_data()
            if addr and amount > 0:
                if amount > state.wallet_balance:
                    QMessageBox.warning(self, 'Chyba', 'Nedostatek HAV.')
                    return
                state.wallet_balance -= amount
                state.transactions.insert(0, {'type': 'Odesláno', 'amount': amount, 'address': addr,
                                              'time': datetime.now().strftime('%H:%M:%S')})
                if len(state.transactions) > 20:
                    state.transactions.pop()
                save_state()
                self.refresh()

class SendDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Odeslat HAV')
        self.setFixedSize(700, 400)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel('Adresa příjemce'))
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText('0x...')
        layout.addWidget(self.address_edit)

        layout.addWidget(QLabel('Částka (HAV)'))
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText('0.00')
        layout.addWidget(self.amount_edit)

        self.message = QLabel('Zadejte adresu a částku.')
        self.message.setStyleSheet('background: #cfe2ff; padding: 8px; border-radius: 8px;')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton('Zavřít')
        cancel_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6c757d, stop:1 #5a6268);
                color: white; font-weight: bold;
                padding: 10px 20px; border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6268, stop:1 #4e555b);
            }
            QPushButton:pressed {
                background: #42484e;
            }
        ''')
        cancel_btn.clicked.connect(self.reject)
        send_btn = QPushButton('Odeslat')
        send_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7e05, stop:1 #f97316);
                color: white; font-weight: bold;
                padding: 10px 20px; border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e66e00, stop:1 #e06600);
            }
            QPushButton:pressed {
                background: #cc5c00;
            }
        ''')
        send_btn.clicked.connect(self._send)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(send_btn)
        layout.addLayout(btn_layout)

        self._data = (None, 0)

    def _send(self):
        addr = self.address_edit.text().strip()
        try:
            amount = float(self.amount_edit.text().strip())
        except ValueError:
            self.message.setText('Zadejte platnou částku.')
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px;')
            return
        if not addr or len(addr) < 10:
            self.message.setText('Zadejte platnou adresu.')
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px;')
            return
        if amount <= 0:
            self.message.setText('Zadejte kladnou částku.')
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px;')
            return
        self._data = (addr, amount)
        self.accept()

    def get_data(self):
        return self._data

# ============================================================
#  SWAP TAB – NAKUP/PRODEJ PŘES FAUCETPAY MERCHANT API
# ============================================================

class SwapTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        left = QGroupBox('Obchod HAV / USDT přes FaucetPay')
        left.setStyleSheet('QGroupBox { font-weight: bold; padding: 16px; }')
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel('Množství HAV'))
        amt_layout = QHBoxLayout()
        self.amount_input = QLineEdit('10000')
        amt_layout.addWidget(self.amount_input)
        amt_layout.addWidget(QLabel('HAV'))
        left_layout.addLayout(amt_layout)

        left_layout.addWidget(QLabel('⬇', alignment=Qt.AlignCenter))

        left_layout.addWidget(QLabel('Odpovídající hodnota v USDT'))
        result_layout = QHBoxLayout()
        self.result_input = QLineEdit('0.00000001')
        self.result_input.setReadOnly(True)
        result_layout.addWidget(self.result_input)
        result_layout.addWidget(QLabel('USDT'))
        left_layout.addLayout(result_layout)

        rate_info = QLabel()
        rate_info.setStyleSheet('color: #0d6efd;')
        left_layout.addWidget(rate_info)
        self.rate_info_label = rate_info

        fee_label = QLabel(f'Poplatek za transakci: {TRANSACTION_FEE*100:.0f} %')
        fee_label.setStyleSheet('color: #6c757d;')
        left_layout.addWidget(fee_label)

        self.balance_label = QLabel(f'FaucetPay USDT zůstatek: 0.00000000')
        self.balance_label.setStyleSheet('color: #0d6efd;')
        left_layout.addWidget(self.balance_label)

        # Tlačítko pro nákup HAV (zaplatí USDT)
        buy_btn = QPushButton('Koupit HAV (zaplatit USDT)')
        buy_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #198754, stop:1 #157347);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #157347, stop:1 #146c43);
            }
            QPushButton:pressed {
                background: #0f5132;
            }
        ''')
        buy_btn.clicked.connect(self._buy_hav)
        left_layout.addWidget(buy_btn)

        # Tlačítko pro prodej HAV (obdrží USDT)
        sell_btn = QPushButton('Prodat HAV (obdržet USDT)')
        sell_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7e05, stop:1 #f97316);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e66e00, stop:1 #e06600);
            }
            QPushButton:pressed {
                background: #cc5c00;
            }
        ''')
        sell_btn.clicked.connect(self._sell_hav)
        left_layout.addWidget(sell_btn)

        left_layout.addStretch()
        layout.addWidget(left)

        self.amount_input.textChanged.connect(self._update_swap)
        self._refresh_balance()
        self._update_swap()

    def _update_swap(self):
        try:
            amt = float(self.amount_input.text() or 0)
            sell_rate = faucetpay_get_sell_rate()
            usdt = amt * sell_rate
            self.result_input.setText(f'{usdt:.12f}')

            buy_rate = faucetpay_get_buy_rate()
            self.rate_info_label.setText(
                f'Nákup: {buy_rate:.12f} USDT/HAV | Prodej: {sell_rate:.12f} USDT/HAV'
            )
        except ValueError:
            pass

    def _refresh_balance(self):
        balance = faucetpay_get_balance()
        state.usdt_balance = balance
        self.balance_label.setText(f'FaucetPay USDT zůstatek: {balance:.8f}')
        save_state()

    def _buy_hav(self):
        """Nákup HAV – otevře deposit formulář na FaucetPay."""
        try:
            amt_hav = float(self.amount_input.text() or 0)
            if amt_hav <= 0:
                QMessageBox.warning(self, 'Chyba', 'Zadejte kladné množství HAV.')
                return

            buy_rate = faucetpay_get_buy_rate()
            usdt_needed = amt_hav * buy_rate
            # Připočteme transakční poplatek (zaplatí uživatel)
            usdt_with_fee = usdt_needed / (1 - TRANSACTION_FEE)

            # Vygenerujeme deposit formulář s custom tagem "buy_HAV"
            custom = f"buy_HAV_{int(time.time())}"
            success, msg = faucetpay_deposit(usdt_with_fee, custom_tag=custom)
            if success:
                QMessageBox.information(self, 'Info', msg)
            else:
                QMessageBox.warning(self, 'Chyba', msg)
        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Zadejte platné číslo.')

    def _sell_hav(self):
        """Prodej HAV – zeptá se na adresu pro výběr USDT a otevře withdraw formulář."""
        try:
            amt_hav = float(self.amount_input.text() or 0)
            if amt_hav <= 0:
                QMessageBox.warning(self, 'Chyba', 'Zadejte kladné množství HAV.')
                return
            if amt_hav > state.wallet_balance:
                QMessageBox.warning(self, 'Chyba', 'Nedostatek HAV v peněžence.')
                return

            sell_rate = faucetpay_get_sell_rate()
            usdt_raw = amt_hav * sell_rate
            usdt_final = apply_fee(usdt_raw)  # poplatek za transakci

            # Zeptáme se na adresu pro výběr USDT
            address, ok = QInputDialog.getText(self, 'Adresa pro výběr USDT',
                                               'Zadejte adresu, na kterou chcete obdržet USDT:',
                                               text='')
            if not ok or not address.strip():
                return
            address = address.strip()

            custom = f"sell_HAV_{int(time.time())}"
            success, msg = faucetpay_withdraw(usdt_final, address, custom_tag=custom)
            if success:
                QMessageBox.information(self, 'Info', msg)
            else:
                QMessageBox.warning(self, 'Chyba', msg)
        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Zadejte platné číslo.')

    def refresh(self):
        self._update_swap()
        self._refresh_balance()

# ============================================================
#  POOL TAB
# ============================================================

class PoolTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        left = QGroupBox('Liquidity Pool · Staking')
        left.setStyleSheet('QGroupBox { font-weight: bold; padding: 16px; }')
        left_layout = QVBoxLayout(left)

        stats_layout = QHBoxLayout()
        self.pool_tvl = QLabel('0')
        self.pool_user = QLabel('0')
        self.pool_reward = QLabel('0')

        stats_layout.addWidget(self._stat_item('Celková likvidita', self.pool_tvl, '(HAV)'))
        stats_layout.addWidget(self._stat_item('Váš stake', self.pool_user, '(HAV)'))
        stats_layout.addWidget(self._stat_item('Odměna', self.pool_reward, '(HAV)'))
        left_layout.addLayout(stats_layout)

        left_layout.addWidget(QLabel('-' * 40))

        info_layout = QFormLayout()
        info_layout.addRow(QLabel('APY:'), QLabel('7 % / 7 dní', styleSheet='color: #198754;'))
        info_layout.addRow(QLabel('Doba uzamčení:'), QLabel('7 dní'))
        self.status_label = QLabel('Žádný stake')
        self.status_label.setStyleSheet('background: #6c757d; color: white; border-radius: 12px; padding: 4px 16px;')
        info_layout.addRow(QLabel('Stav:'), self.status_label)
        self.countdown_label = QLabel('—')
        self.countdown_label.setStyleSheet('font-family: monospace; color: #ff7e05;')
        info_layout.addRow(QLabel('Čas do odemčení:'), self.countdown_label)
        left_layout.addLayout(info_layout)

        ctrl_layout = QHBoxLayout()
        self.stake_input = QLineEdit('10')
        self.stake_input.setFixedWidth(150)
        max_btn = QPushButton('Max')
        max_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6c757d, stop:1 #5a6268);
                color: white; font-weight: bold;
                padding: 10px 20px; border-radius: 16px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5a6268, stop:1 #4e555b);
            }
            QPushButton:pressed {
                background: #42484e;
            }
        ''')
        max_btn.clicked.connect(self._set_max)
        ctrl_layout.addWidget(self.stake_input)
        ctrl_layout.addWidget(max_btn)
        left_layout.addLayout(ctrl_layout)

        stake_btn = QPushButton('Stake')
        stake_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #198754, stop:1 #157347);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #157347, stop:1 #146c43);
            }
            QPushButton:pressed {
                background: #0f5132;
            }
        ''')
        stake_btn.clicked.connect(self._stake)
        left_layout.addWidget(stake_btn)

        unstake_btn = QPushButton('Unstake')
        unstake_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #dc3545, stop:1 #c82333);
                color: white; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #c82333, stop:1 #b02a37);
            }
            QPushButton:pressed {
                background: #a71d2a;
            }
        ''')
        unstake_btn.clicked.connect(self._unstake)
        left_layout.addWidget(unstake_btn)

        claim_btn = QPushButton('Vybrat odměnu')
        claim_btn.setStyleSheet('''
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffc107, stop:1 #e0a800);
                color: black; font-weight: bold;
                padding: 15px 30px; border-radius: 25px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e0a800, stop:1 #c99700);
            }
            QPushButton:pressed {
                background: #b88600;
            }
        ''')
        claim_btn.clicked.connect(self._claim)
        left_layout.addWidget(claim_btn)

        self.pool_message = QLabel('')
        self.pool_message.setWordWrap(True)
        left_layout.addWidget(self.pool_message)

        layout.addWidget(left, 2)

        right = QGroupBox('Historie staků')
        right.setStyleSheet('QGroupBox { font-weight: bold; padding: 16px; }')
        right_layout = QVBoxLayout(right)

        self.stake_history_table = QTableWidget()
        self.stake_history_table.setColumnCount(3)
        self.stake_history_table.setHorizontalHeaderLabels(['Čas', 'Částka', 'Typ'])
        self.stake_history_table.horizontalHeader().setStretchLastSection(True)
        self.stake_history_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.stake_history_table)

        right_layout.addWidget(QLabel('Odměna 7% po 7 dnech.', styleSheet='color: #7b8a9b;'))

        layout.addWidget(right, 1)
        self.refresh()

    def _stat_item(self, label, value_widget, unit):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel(label, styleSheet='color: #7b8a9b;'))
        hl = QHBoxLayout()
        hl.addWidget(value_widget)
        hl.addWidget(QLabel(unit, styleSheet='color: #7b8a9b;'))
        l.addLayout(hl)
        return w

    def refresh(self):
        pool = state.pool
        self.pool_tvl.setText(f'{pool["total_liquidity"]:.2f}')
        self.pool_user.setText(f'{pool["user_stake"]:.2f}')
        reward = state.get_pool_reward()
        self.pool_reward.setText(f'{reward:.2f}')

        status = state.get_pool_status()
        self.status_label.setText(status)
        self.status_label.setStyleSheet('background: #198754; color: white; border-radius: 12px; padding: 4px 16px;' if status == 'Odemčeno' else 'background: #6c757d; color: white; border-radius: 12px; padding: 4px 16px;')
        self.countdown_label.setText(state.get_pool_countdown())

        history = pool['history']
        self.stake_history_table.setUpdatesEnabled(False)
        self.stake_history_table.setRowCount(len(history))
        for i, h in enumerate(history[:10]):
            self.stake_history_table.setItem(i, 0, QTableWidgetItem(format_date(h['time'])))
            self.stake_history_table.setItem(i, 1, QTableWidgetItem(f'{h["amount"]:.2f} HAV'))
            self.stake_history_table.setItem(i, 2, QTableWidgetItem(h['type']))
        self.stake_history_table.resizeColumnsToContents()
        self.stake_history_table.setUpdatesEnabled(True)

    def _set_max(self):
        self.stake_input.setText(f'{state.wallet_balance:.2f}')

    def _stake(self):
        try:
            amount = float(self.stake_input.text() or 0)
        except ValueError:
            self._show_message('Zadejte platnou částku.', 'warning')
            return
        if amount <= 0:
            self._show_message('Zadejte kladnou částku.', 'warning')
            return
        if amount > state.wallet_balance:
            self._show_message('Nedostatek HAV.', 'danger')
            return

        state.wallet_balance -= amount
        state.pool['user_stake'] += amount
        state.pool['total_liquidity'] += amount
        state.pool['stake_time'] = time.time()
        state.pool['reward'] = 0
        state.pool['claimed'] = False
        state.pool['history'].insert(0, {'time': time.time(), 'amount': amount, 'type': 'Stake'})
        if len(state.pool['history']) > 20:
            state.pool['history'].pop()

        state.transactions.insert(0, {'type': 'Stake', 'amount': amount, 'address': 'Pool',
                                      'time': datetime.now().strftime('%H:%M:%S')})
        if len(state.transactions) > 20:
            state.transactions.pop()

        save_state()
        self._show_message(f'Stake {amount} HAV vložen.', 'success')
        self.refresh()

    def _unstake(self):
        if state.pool['user_stake'] == 0:
            self._show_message('Nemáte žádný stake.', 'warning')
            return
        reward = state.get_pool_reward()
        total = state.pool['user_stake'] + reward
        state.wallet_balance += total
        state.pool['user_stake'] = 0
        state.pool['total_liquidity'] -= state.pool['user_stake']
        state.pool['stake_time'] = None
        state.pool['reward'] = 0
        state.pool['claimed'] = False
        state.pool['history'].insert(0, {'time': time.time(), 'amount': total, 'type': 'Unstake + odměna'})
        if len(state.pool['history']) > 20:
            state.pool['history'].pop()

        state.transactions.insert(0, {'type': 'Unstake', 'amount': total, 'address': 'Pool',
                                      'time': datetime.now().strftime('%H:%M:%S')})
        if len(state.transactions) > 20:
            state.transactions.pop()

        save_state()
        self._show_message(f'Vybráno {total:.2f} HAV (vč. odměny {reward:.2f}).', 'success')
        self.refresh()

    def _claim(self):
        reward = state.get_pool_reward()
        if reward == 0:
            self._show_message('Žádná odměna.', 'warning')
            return
        state.wallet_balance += reward
        state.pool['reward'] = 0
        state.pool['claimed'] = True
        state.pool['stake_time'] = time.time()

        state.transactions.insert(0, {'type': 'Odměna z Poolu', 'amount': reward, 'address': 'Pool',
                                      'time': datetime.now().strftime('%H:%M:%S')})
        if len(state.transactions) > 20:
            state.transactions.pop()

        save_state()
        self._show_message(f'Odměna {reward:.2f} HAV přičtena.', 'success')
        self.refresh()

    def _show_message(self, text, level='info'):
        colors = {'info': '#cfe2ff', 'success': '#d1e7dd', 'warning': '#fff3cd', 'danger': '#f8d7da'}
        self.pool_message.setStyleSheet(f'background: {colors.get(level, "#cfe2ff")}; padding: 8px; border-radius: 8px;')
        self.pool_message.setText(text)
        QTimer.singleShot(5000, lambda: self.pool_message.setText(''))

# ============================================================
#  TRADING CHART CANVAS (svíčkový graf + objem)
# ============================================================

class TradingChartCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(12, 7), dpi=100, facecolor='#131722')
        self.ax_price = self.fig.add_subplot(2, 1, 1, facecolor='#131722')
        self.ax_volume = self.fig.add_subplot(2, 1, 2, facecolor='#131722', sharex=self.ax_price)
        self.ax_volume.set_facecolor('#131722')
        self.ax_price.tick_params(colors='#787b86')
        self.ax_volume.tick_params(colors='#787b86')
        self.fig.subplots_adjust(hspace=0.05)
        super().__init__(self.fig)
        self.setParent(parent)


# ============================================================
#  TRADING TAB – plnohodnotné obchodování s pozicemi (burza)
#  Využívá USDT z FaucetPay (state.usdt_balance)
# ============================================================

class TradingTab(QWidget):
    def __init__(self):
        super().__init__()
        # Data pro graf
        self.price_points = []
        self.current_timeframe = '1m'
        self.timeframes = ['1m', '5m', '15m', '1h', '4h', '1d']
        self.last_price = None

        self.init_ui()
        self._load_initial_prices()
        self.update_chart()

        # Timery
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(1000)

        self.pos_timer = QTimer()
        self.pos_timer.timeout.connect(self._update_positions)
        self.pos_timer.start(2000)

        self._update_positions()
        self._update_trade_history()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Horní lišta
        top_frame = QFrame()
        top_frame.setStyleSheet('background: #1e222d; padding: 8px 16px;')
        top_layout = QHBoxLayout(top_frame)
        top_layout.setSpacing(20)

        self.price_label = QLabel('0.000000000000')
        self.price_label.setStyleSheet('color: #d1d4dc; font-size: 34px; font-weight: bold;')

        self.change_label = QLabel('+0.00%')
        self.change_label.setStyleSheet('color: #26a69a; font-size: 28px;')

        self.czk_label = QLabel('CZK: 0.00')
        self.czk_label.setStyleSheet('color: #d1d4dc; font-size: 28px; font-weight: bold;')

        self.balance_label = QLabel('Zůstatek USDT: 0.00')
        self.balance_label.setStyleSheet('color: #f8b82e; font-size: 28px; font-weight: bold;')

        self.equity_label = QLabel('Equity: 0.00 USDT')
        self.equity_label.setStyleSheet('color: #d1d4dc; font-size: 24px;')

        top_layout.addWidget(self.price_label)
        top_layout.addWidget(self.change_label)
        top_layout.addWidget(self.czk_label)
        top_layout.addStretch()
        top_layout.addWidget(self.balance_label)
        top_layout.addWidget(self.equity_label)

        main_layout.addWidget(top_frame)

        # Hlavní splitter – graf vlevo, obchodní panel + tabulky vpravo
        splitter = QSplitter(Qt.Horizontal)

        # Levý panel – graf + toolbar
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setStyleSheet('background: #1e222d; padding: 4px 8px;')
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setSpacing(4)

        self.timeframe_buttons = []
        for tf in self.timeframes:
            btn = QPushButton(tf)
            btn.setStyleSheet('''
                QPushButton {
                    background: transparent;
                    color: #787b86;
                    border: none;
                    padding: 6px 14px;
                    font-size: 22px;
                    font-weight: bold;
                }
                QPushButton:hover { color: #d1d4dc; }
                QPushButton:checked {
                    color: #d1d4dc;
                    border-bottom: 3px solid #f8b82e;
                }
            ''')
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, t=tf: self.set_timeframe(t))
            toolbar_layout.addWidget(btn)
            self.timeframe_buttons.append(btn)
        self.timeframe_buttons[0].setChecked(True)

        toolbar_layout.addStretch()
        left_layout.addWidget(toolbar)

        self.canvas = TradingChartCanvas(self)
        left_layout.addWidget(self.canvas)

        splitter.addWidget(left_widget)

        # Pravý panel – obchodování
        right_widget = QWidget()
        right_widget.setStyleSheet('background: #1e222d;')
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(4)

        # --- Obchodní panel ---
        trade_group = QGroupBox('Nový obchod')
        trade_group.setStyleSheet('''
            QGroupBox { 
                color: #d1d4dc; 
                border: 1px solid #2a2e39; 
                border-radius: 8px; 
                margin-top: 8px;
                padding-top: 8px;
                font-weight: bold;
                font-size: 24px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        ''')
        trade_layout = QFormLayout(trade_group)
        trade_layout.setSpacing(4)

        # Množství (v HAV)
        self.amount_input = QLineEdit('1.0')
        self.amount_input.setStyleSheet('background: #2a2e39; color: #d1d4dc; border: none; padding: 6px; border-radius: 4px;')
        trade_layout.addRow(QLabel('Množství (HAV):', styleSheet='color: #787b86; font-size: 22px;'), self.amount_input)

        # Cena (limit / market)
        cena_layout = QHBoxLayout()
        self.price_type_combo = QComboBox()
        self.price_type_combo.addItems(['Market', 'Limit'])
        self.price_type_combo.setStyleSheet('background: #2a2e39; color: #d1d4dc; border: none; padding: 4px; border-radius: 4px;')
        cena_layout.addWidget(self.price_type_combo)

        self.limit_price_input = QLineEdit()
        self.limit_price_input.setPlaceholderText('Cena USDT')
        self.limit_price_input.setStyleSheet('background: #2a2e39; color: #d1d4dc; border: none; padding: 6px; border-radius: 4px;')
        self.limit_price_input.setVisible(False)
        cena_layout.addWidget(self.limit_price_input)

        self.price_type_combo.currentIndexChanged.connect(
            lambda i: self.limit_price_input.setVisible(i == 1)
        )
        trade_layout.addRow(QLabel('Cena:', styleSheet='color: #787b86; font-size: 22px;'), cena_layout)

        # Páka
        leverage_layout = QHBoxLayout()
        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems(['1x', '2x', '5x', '10x'])
        self.leverage_combo.setStyleSheet('background: #2a2e39; color: #d1d4dc; border: none; padding: 4px; border-radius: 4px;')
        self.leverage_combo.currentIndexChanged.connect(self._on_leverage_change)
        leverage_layout.addWidget(self.leverage_combo)
        leverage_layout.addStretch()
        trade_layout.addRow(QLabel('Páka:', styleSheet='color: #787b86; font-size: 22px;'), leverage_layout)

        # Tlačítka Buy / Sell
        btn_layout = QHBoxLayout()
        self.buy_btn = QPushButton('🟢 BUY (LONG)')
        self.buy_btn.setStyleSheet('''
            QPushButton {
                background: #26a69a; 
                color: white; 
                font-weight: bold;
                padding: 10px; 
                border: none; 
                border-radius: 6px;
                font-size: 24px;
            }
            QPushButton:hover { background: #2bbdae; }
            QPushButton:pressed { background: #1a8c7e; }
        ''')
        self.buy_btn.clicked.connect(lambda: self._open_position('long'))

        self.sell_btn = QPushButton('🔴 SELL (SHORT)')
        self.sell_btn.setStyleSheet('''
            QPushButton {
                background: #ef5350; 
                color: white; 
                font-weight: bold;
                padding: 10px; 
                border: none; 
                border-radius: 6px;
                font-size: 24px;
            }
            QPushButton:hover { background: #f0625c; }
            QPushButton:pressed { background: #c62828; }
        ''')
        self.sell_btn.clicked.connect(lambda: self._open_position('short'))

        btn_layout.addWidget(self.buy_btn)
        btn_layout.addWidget(self.sell_btn)
        trade_layout.addRow(btn_layout)

        right_layout.addWidget(trade_group)

        # --- Otevřené pozice ---
        pos_group = QGroupBox('Otevřené pozice')
        pos_group.setStyleSheet(trade_group.styleSheet())
        pos_layout = QVBoxLayout(pos_group)

        self.positions_table = QTableWidget()
        self.positions_table.setColumnCount(7)
        self.positions_table.setHorizontalHeaderLabels(['Směr', 'Vstup', 'Aktuální', 'Množství', 'Margin', 'PnL', 'Zavřít'])
        self.positions_table.horizontalHeader().setStretchLastSection(True)
        self.positions_table.setStyleSheet('''
            QTableWidget {
                background: #131722;
                color: #d1d4dc;
                border: none;
                font-size: 20px;
                gridline-color: #2a2e39;
            }
            QTableWidget::item { padding: 4px; }
        ''')
        self.positions_table.setFixedHeight(180)
        pos_layout.addWidget(self.positions_table)
        right_layout.addWidget(pos_group)

        # --- Historie obchodů ---
        hist_group = QGroupBox('Historie obchodů')
        hist_group.setStyleSheet(trade_group.styleSheet())
        hist_layout = QVBoxLayout(hist_group)

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(['Čas', 'Směr', 'Cena', 'Množství', 'PnL', 'Status'])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setStyleSheet('''
            QTableWidget {
                background: #131722;
                color: #d1d4dc;
                border: none;
                font-size: 20px;
                gridline-color: #2a2e39;
            }
            QTableWidget::item { padding: 4px; }
        ''')
        self.history_table.setFixedHeight(150)
        hist_layout.addWidget(self.history_table)
        right_layout.addWidget(hist_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([700, 400])

        main_layout.addWidget(splitter)

        self.update_header()

    # ---------- Data pro graf ----------
    def _load_initial_prices(self):
        hist = list(state.price_history)
        if not hist:
            hist = [BASE_RATE]
        now = time.time()
        for i, price in enumerate(hist):
            ts = now - (len(hist) - i) * 1.0
            self.price_points.append((ts, price))
        self.last_price = hist[-1] if hist else BASE_RATE

    def _check_new_price(self):
        if not state.price_history:
            return
        current = state.price_history[-1]
        if current != self.last_price:
            self.price_points.append((time.time(), current))
            self.last_price = current
            if len(self.price_points) > 10000:
                self.price_points = self.price_points[-10000:]

    def get_candles(self, timeframe):
        if len(self.price_points) < 2:
            return []
        mapping = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400}
        interval = mapping.get(timeframe, 60)
        candles = []
        points = sorted(self.price_points, key=lambda x: x[0])
        start_time = points[0][0]
        end_time = points[-1][0]
        current_start = start_time
        while current_start <= end_time:
            current_end = current_start + interval
            segment = [p for p in points if current_start <= p[0] < current_end]
            if len(segment) >= 2:
                o = segment[0][1]
                c = segment[-1][1]
                h = max(p[1] for p in segment)
                l = min(p[1] for p in segment)
                v = len(segment)
                candles.append({'t': current_start, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v})
            current_start = current_end
        return candles

    @staticmethod
    def sma(data, window):
        if len(data) < window:
            return []
        return [sum(data[i-window:i]) / window for i in range(window, len(data)+1)]

    def set_timeframe(self, tf):
        for btn in self.timeframe_buttons:
            btn.setChecked(btn.text() == tf)
        self.current_timeframe = tf
        self.update_chart()

    # ---------- Pravidelná aktualizace ----------
    def update(self):
        self._check_new_price()
        self.update_header()
        if self.last_price != getattr(self, '_last_rendered_price', None):
            self.update_chart()
            self._last_rendered_price = self.last_price
        if not hasattr(self, '_counter'):
            self._counter = 0
        self._counter += 1
        if self._counter % 10 == 0:
            self.update_chart()

    def update_header(self):
        if not self.price_points:
            return
        prices = [p[1] for p in self.price_points]
        current = prices[-1]
        self.price_label.setText(f'{current:.12f}')

        if len(prices) > 1:
            first = prices[0]
            last = prices[-1]
            change = (last - first) / first * 100 if first != 0 else 0
            self.change_label.setText(f'{change:+.2f}%')
            self.change_label.setStyleSheet(
                'color: #26a69a;' if change >= 0 else 'color: #ef5350;'
            )

        # CZK
        czk = current * CZK_RATE
        self.czk_label.setText(f'CZK: {czk:.6f}')

        # Zůstatek a equity – používáme state.usdt_balance
        balance = state.usdt_balance
        self.balance_label.setText(f'Zůstatek USDT: {balance:.2f}')

        total_pnl = sum(p.get('pnl', 0.0) for p in state.positions if not p.get('closed', False))
        equity = balance + total_pnl
        self.equity_label.setText(f'Equity: {equity:.2f} USDT')

    # ---------- Páka ----------
    def _on_leverage_change(self, idx):
        values = [1, 2, 5, 10]
        state.leverage = values[idx]
        save_state()

    # ---------- Otevírání pozic ----------
    def _open_position(self, direction):
        try:
            amount = float(self.amount_input.text())
        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Zadejte platné množství HAV.')
            return
        if amount <= 0:
            QMessageBox.warning(self, 'Chyba', 'Množství musí být kladné.')
            return

        # Aktuální cena (market)
        current_price = self.last_price if self.last_price else BASE_RATE

        # Limit cena
        if self.price_type_combo.currentIndex() == 1:  # Limit
            try:
                limit_price = float(self.limit_price_input.text())
            except ValueError:
                QMessageBox.warning(self, 'Chyba', 'Zadejte platnou limitní cenu.')
                return
            if limit_price <= 0:
                QMessageBox.warning(self, 'Chyba', 'Limitní cena musí být kladná.')
                return
            entry_price = limit_price
        else:
            entry_price = current_price

        # Výpočet marginu
        leverage = state.leverage
        position_value = amount * entry_price
        margin = position_value / leverage

        # Kontrola zůstatku – používáme state.usdt_balance
        if margin > state.usdt_balance:
            QMessageBox.warning(self, 'Chyba', f'Nedostatečný zůstatek USDT. Potřebujete {margin:.2f} USDT (máte {state.usdt_balance:.2f}).')
            return

        # Odebrat margin ze zůstatku
        state.usdt_balance -= margin

        # Vytvořit pozici
        position = {
            'id': int(time.time() * 1000),
            'direction': direction,
            'entry_price': entry_price,
            'amount': amount,
            'margin': margin,
            'leverage': leverage,
            'open_time': time.time(),
            'pnl': 0.0,
            'closed': False
        }
        state.positions.append(position)
        save_state()

        # Záznam do historie
        state.trade_history.append({
            'time': time.time(),
            'direction': direction,
            'price': entry_price,
            'amount': amount,
            'pnl': 0.0,
            'status': 'Otevřeno'
        })
        save_state()

        QMessageBox.information(self, 'Obchod', f'{direction.upper()} pozice otevřena na {entry_price:.12f} USDT, množství {amount} HAV, páka {leverage}x')
        self._update_positions()
        self._update_trade_history()
        self.update_header()

    # ---------- Zavírání pozic ----------
    def _close_position(self, pos_id):
        current_price = self.last_price if self.last_price else BASE_RATE
        pos = next((p for p in state.positions if p['id'] == pos_id), None)
        if not pos or pos.get('closed', False):
            return

        # Výpočet PnL
        if pos['direction'] == 'long':
            pnl = (current_price - pos['entry_price']) * pos['amount'] * pos['leverage']
        else:  # short
            pnl = (pos['entry_price'] - current_price) * pos['amount'] * pos['leverage']

        # Přidat/odebrat PnL k zůstatku USDT
        state.usdt_balance += pos['margin'] + pnl

        # Uzavřít pozici
        pos['closed'] = True
        pos['close_price'] = current_price
        pos['pnl'] = pnl
        pos['close_time'] = time.time()

        # Aktualizovat historii
        for trade in state.trade_history:
            if trade.get('time') == pos['open_time'] and trade.get('status') == 'Otevřeno':
                trade['pnl'] = pnl
                trade['status'] = 'Uzavřeno'
                trade['close_price'] = current_price
                break

        save_state()
        QMessageBox.information(self, 'Obchod', f'Pozice uzavřena, PnL: {pnl:.2f} USDT')
        self._update_positions()
        self._update_trade_history()
        self.update_header()

    # ---------- Aktualizace tabulek ----------
    def _update_positions(self):
        current_price = self.last_price if self.last_price else BASE_RATE

        # Aktualizovat PnL u otevřených pozic
        for pos in state.positions:
            if not pos.get('closed', False):
                if pos['direction'] == 'long':
                    pnl = (current_price - pos['entry_price']) * pos['amount'] * pos['leverage']
                else:
                    pnl = (pos['entry_price'] - current_price) * pos['amount'] * pos['leverage']
                pos['pnl'] = pnl

        # Zobrazit pouze otevřené pozice
        open_positions = [p for p in state.positions if not p.get('closed', False)]

        self.positions_table.setUpdatesEnabled(False)
        self.positions_table.setRowCount(len(open_positions))

        for i, pos in enumerate(open_positions):
            # Směr
            direction_text = '🟢 LONG' if pos['direction'] == 'long' else '🔴 SHORT'
            self.positions_table.setItem(i, 0, QTableWidgetItem(direction_text))

            # Vstupní cena
            self.positions_table.setItem(i, 1, QTableWidgetItem(f'{pos["entry_price"]:.12f}'))

            # Aktuální cena
            self.positions_table.setItem(i, 2, QTableWidgetItem(f'{current_price:.12f}'))

            # Množství
            self.positions_table.setItem(i, 3, QTableWidgetItem(f'{pos["amount"]:.2f}'))

            # Margin
            self.positions_table.setItem(i, 4, QTableWidgetItem(f'{pos["margin"]:.2f}'))

            # PnL
            pnl = pos['pnl']
            pnl_item = QTableWidgetItem(f'{pnl:+.2f}')
            pnl_item.setForeground(Qt.green if pnl >= 0 else Qt.red)
            self.positions_table.setItem(i, 5, pnl_item)

            # Tlačítko Zavřít
            close_btn = QPushButton('✕ Zavřít')
            close_btn.setStyleSheet('''
                QPushButton {
                    background: #ef5350;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 18px;
                }
                QPushButton:hover { background: #f0625c; }
                QPushButton:pressed { background: #c62828; }
            ''')
            close_btn.clicked.connect(lambda checked, pid=pos['id']: self._close_position(pid))
            self.positions_table.setCellWidget(i, 6, close_btn)

        self.positions_table.resizeColumnsToContents()
        self.positions_table.setUpdatesEnabled(True)

    def _update_trade_history(self):
        history = state.trade_history[-20:][::-1]  # posledních 20, nejnovější nahoře

        self.history_table.setUpdatesEnabled(False)
        self.history_table.setRowCount(len(history))

        for i, trade in enumerate(history):
            # Čas
            self.history_table.setItem(i, 0, QTableWidgetItem(format_time(trade['time'])))

            # Směr
            direction_text = '🟢 LONG' if trade['direction'] == 'long' else '🔴 SHORT'
            self.history_table.setItem(i, 1, QTableWidgetItem(direction_text))

            # Cena
            self.history_table.setItem(i, 2, QTableWidgetItem(f'{trade["price"]:.12f}'))

            # Množství
            self.history_table.setItem(i, 3, QTableWidgetItem(f'{trade["amount"]:.2f}'))

            # PnL
            pnl = trade.get('pnl', 0.0)
            pnl_item = QTableWidgetItem(f'{pnl:+.2f}')
            pnl_item.setForeground(Qt.green if pnl >= 0 else Qt.red)
            self.history_table.setItem(i, 4, pnl_item)

            # Status
            self.history_table.setItem(i, 5, QTableWidgetItem(trade['status']))

        self.history_table.resizeColumnsToContents()
        self.history_table.setUpdatesEnabled(True)

    # ---------- Vykreslení grafu ----------
    def update_chart(self):
        candles = self.get_candles(self.current_timeframe)
        if not candles:
            return

        self.canvas.ax_price.clear()
        self.canvas.ax_volume.clear()

        opens = [c['o'] for c in candles]
        highs = [c['h'] for c in candles]
        lows = [c['l'] for c in candles]
        closes = [c['c'] for c in candles]
        volumes = [c['v'] for c in candles]

        # Svíčky
        for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
            color = '#26a69a' if c >= o else '#ef5350'
            self.canvas.ax_price.plot([i, i], [l, h], color=color, linewidth=1)
            self.canvas.ax_price.bar(i, abs(c - o), bottom=min(o, c), color=color, width=0.6)

        # SMA 20 a 50
        if len(closes) > 20:
            sma20 = self.sma(closes, 20)
            self.canvas.ax_price.plot(range(len(sma20)), sma20, color='#f8b82e', linewidth=1.5, label='SMA 20')
        if len(closes) > 50:
            sma50 = self.sma(closes, 50)
            self.canvas.ax_price.plot(range(len(sma50)), sma50, color='#4caf50', linewidth=1.5, label='SMA 50')

        # Objem
        colors_vol = ['#26a69a' if c >= o else '#ef5350' for o, c in zip(opens, closes)]
        self.canvas.ax_volume.bar(range(len(volumes)), volumes, color=colors_vol, alpha=0.5)
        self.canvas.ax_volume.set_ylabel('Objem', color='#787b86')

        self.canvas.ax_price.set_ylabel('Cena', color='#787b86')
        self.canvas.ax_price.grid(True, color='#2a2e39', linestyle='-', linewidth=0.5)
        self.canvas.ax_volume.grid(True, color='#2a2e39', linestyle='-', linewidth=0.5)
        self.canvas.ax_price.legend(loc='upper left', facecolor='#131722', labelcolor='#d1d4dc')

        self.canvas.fig.tight_layout()
        self.canvas.draw()

# ============================================================
#  STATS TAB
# ============================================================

class StatsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        card_layout = QHBoxLayout()
        self.stats = {}
        labels = [('blocks', 'Bloky', '0'), ('difficulty', 'Obtížnost', '0.50 T'),
                  ('supply', 'Celkové HAV', '0'), ('tx', 'Transakce', '0')]
        for key, title, default in labels:
            card = self._make_card(title, default)
            card_layout.addWidget(card)
            self.stats[key] = card
        layout.addLayout(card_layout)

        group = QGroupBox('Informace o trhu')
        group.setStyleSheet('QGroupBox { font-weight: bold; padding: 10px; }')
        g_layout = QVBoxLayout(group)

        info_grid = QGridLayout()
        info_grid.addWidget(QLabel('Střední kurz:'), 0, 0)
        self.mid_label = QLabel(f'{BASE_RATE:.12f} USDT')
        info_grid.addWidget(self.mid_label, 0, 1)

        info_grid.addWidget(QLabel('Nákup (ask):'), 1, 0)
        self.ask_label = QLabel(f'{BASE_RATE*(1+SPREAD):.12f} USDT')
        info_grid.addWidget(self.ask_label, 1, 1)

        info_grid.addWidget(QLabel('Prodej (bid):'), 2, 0)
        self.bid_label = QLabel(f'{BASE_RATE*(1-SPREAD):.12f} USDT')
        info_grid.addWidget(self.bid_label, 2, 1)

        info_grid.addWidget(QLabel('Spread:'), 3, 0)
        self.spread_info_label = QLabel(f'{SPREAD*100:.0f} %')
        info_grid.addWidget(self.spread_info_label, 3, 1)

        info_grid.addWidget(QLabel('Transakční poplatek:'), 4, 0)
        self.fee_info_label = QLabel(f'{TRANSACTION_FEE*100:.0f} %')
        info_grid.addWidget(self.fee_info_label, 4, 1)

        g_layout.addLayout(info_grid)
        layout.addWidget(group)

        self.refresh()

    def _make_card(self, title, default):
        card = QFrame()
        card.setStyleSheet('QFrame { background: white; border-radius: 12px; padding: 10px 16px; border: 1px solid #e9edf4; }')
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel(title, styleSheet='color: #7b8a9b;'))
        label = QLabel(default)
        layout.addWidget(label)
        card._label = label
        return card

    def refresh(self):
        self.stats['blocks']._label.setText(str(state.block_height))
        self.stats['difficulty']._label.setText(f'{state.difficulty:.2f} T')
        self.stats['supply']._label.setText(f'{state.total_supply:,.0f}')
        self.stats['tx']._label.setText(str(len(state.transactions)))

        current = state.price_history[-1] if state.price_history else BASE_RATE
        self.mid_label.setText(f'{current:.12f} USDT')
        self.ask_label.setText(f'{current*(1+SPREAD):.12f} USDT')
        self.bid_label.setText(f'{current*(1-SPREAD):.12f} USDT')

# ============================================================
#  BLOCKCHAIN TAB
# ============================================================

class BlockchainTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel('Blockchain'))

        self.block_table = QTableWidget()
        self.block_table.setColumnCount(6)
        self.block_table.setHorizontalHeaderLabels(['Výška', 'Hash', 'Těžař', 'Odměna', 'Tx', 'Čas'])
        self.block_table.horizontalHeader().setStretchLastSection(True)
        self.block_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.block_table)

        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel('Obtížnost:'))
        self.diff_label = QLabel('0.50')
        info_layout.addWidget(self.diff_label)
        info_layout.addStretch()
        info_layout.addWidget(QLabel('Bloků:'))
        self.blocks_label = QLabel('0')
        info_layout.addWidget(self.blocks_label)
        layout.addLayout(info_layout)

        self.refresh()

    def refresh(self):
        self.diff_label.setText(f'{state.difficulty:.2f}')
        self.blocks_label.setText(str(state.block_height))

        blocks = state.blockchain[:15]
        self.block_table.setUpdatesEnabled(False)
        self.block_table.setRowCount(len(blocks))
        for i, b in enumerate(blocks):
            self.block_table.setItem(i, 0, QTableWidgetItem(f'#{b["height"]}'))
            self.block_table.setItem(i, 1, QTableWidgetItem(b['hash']))
            self.block_table.setItem(i, 2, QTableWidgetItem(b['miner']))
            self.block_table.setItem(i, 3, QTableWidgetItem(f'{b["reward"]:.2f} HAV'))
            self.block_table.setItem(i, 4, QTableWidgetItem(str(b['tx_count'])))
            self.block_table.setItem(i, 5, QTableWidgetItem(format_time(b['timestamp'])))
        self.block_table.resizeColumnsToContents()
        self.block_table.setUpdatesEnabled(True)

# ============================================================
#  FLASK SERVER – IPN CALLBACK PODLE OFICIÁLNÍ DOKUMENTACE
# ============================================================

flask_app = Flask(__name__)

@flask_app.route('/callback', methods=['POST'])
def faucetpay_callback_route():
    """Zpracování IPN callbacku z FaucetPay s ověřením tokenu."""
    data = request.form.to_dict()
    print(f"📩 FaucetPay callback POST data: {data}")

    token = data.get('token')
    if not token:
        print("❌ Chybí token v callbacku")
        return jsonify({"status": "error", "message": "Missing token"}), 400

    try:
        # Ověření tokenu přes FaucetPay API
        response = requests.get(f"https://faucetpay.io/merchant/get-payment/{token}", timeout=10)
        if response.status_code != 200:
            print(f"❌ Chyba při ověřování tokenu: {response.status_code}")
            return jsonify({"status": "error", "message": "Token verification failed"}), 400

        payment_info = response.json()
        print(f"📦 Payment info: {payment_info}")

        # Kontrola validity
        if not payment_info.get('valid', False):
            print("❌ Neplatný token")
            return jsonify({"status": "error", "message": "Invalid token"}), 400

        # Ověření merchant_username
        if payment_info.get('merchant_username') != FAUCETPAY_MERCHANT_ID:
            print(f"❌ Neplatný merchant: {payment_info.get('merchant_username')}")
            return jsonify({"status": "error", "message": "Invalid merchant"}), 400

        # Získání důležitých údajů
        amount1 = float(payment_info.get('amount1', 0))
        currency1 = payment_info.get('currency1', '')
        custom = payment_info.get('custom', '')
        transaction_id = payment_info.get('transaction_id', '')

        # Ověření měny (očekáváme USDT)
        if currency1 != 'USDT':
            print(f"❌ Neočekávaná měna: {currency1}")
            return jsonify({"status": "error", "message": "Unexpected currency"}), 400

        print(f"✅ Platba ověřena: {amount1} {currency1}, custom: {custom}")

        # Zpracování podle custom tagu
        with state._lock:
            # Nejprve přičteme USDT (vždy)
            state.usdt_balance += amount1

            if custom.startswith('buy_HAV'):
                # Nákup HAV
                buy_rate = faucetpay_get_buy_rate()
                hav = (amount1 * (1 - TRANSACTION_FEE)) / buy_rate
                state.wallet_balance += hav
                state.total_supply += hav
                state.transactions.insert(0, {
                    'type': 'Nákup HAV (FaucetPay)',
                    'amount': hav,
                    'address': 'FaucetPay',
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'txid': transaction_id
                })
                price_change = amount1 * 0.001
                new_price = min(BASE_RATE * 2, state.price_history[-1] + price_change)
                state.price_history.append(new_price)

            elif custom.startswith('sell_HAV'):
                # Prodej HAV
                sell_rate = faucetpay_get_sell_rate()
                hav = amount1 / (sell_rate * (1 - TRANSACTION_FEE))
                state.wallet_balance -= hav
                if state.wallet_balance < 0:
                    state.wallet_balance = 0
                state.transactions.insert(0, {
                    'type': 'Prodej HAV (FaucetPay)',
                    'amount': hav,
                    'address': 'FaucetPay',
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'txid': transaction_id
                })
                price_change = -amount1 * 0.001
                new_price = max(BASE_RATE * 0.5, state.price_history[-1] + price_change)
                state.price_history.append(new_price)

            else:
                # Neznámý custom – jen přidáme USDT
                state.transactions.insert(0, {
                    'type': 'Vklad USDT (FaucetPay)',
                    'amount': amount1,
                    'address': 'FaucetPay',
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'txid': transaction_id
                })

            # Omezení historie
            if len(state.transactions) > 20:
                state.transactions.pop()

            save_state()

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"❌ Chyba při zpracování callbacku: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@flask_app.route('/success')
def payment_success():
    return '''<html>
<head><meta charset="UTF-8"><title>Platba úspěšná</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#198754}</style>
</head><body><h1>✅ Transakce byla úspěšná</h1>
<p>Můžete se vrátit do aplikace – zůstatek byl aktualizován.</p></body></html>'''

@flask_app.route('/cancel')
def payment_cancel():
    return '''<html>
<head><meta charset="UTF-8"><title>Platba zrušena</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#dc3545}</style>
</head><body><h1>❌ Transakce byla zrušena</h1>
<p>Žádné prostředky nebyly převedeny.</p></body></html>'''

@flask_app.route('/')
def index():
    return '''<html>
<head><meta charset="UTF-8"><title>Havirov Coin Server</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#ff7e05}</style>
</head><body><h1>🪙 Havirov Coin Server</h1>
<p>Flask server běží. Čekám na callbacky z FaucetPay...</p></body></html>'''

class FlaskServerThread(QThread):
    def __init__(self, host='0.0.0.0', port=FLASK_CALLBACK_PORT):
        super().__init__()
        self.host = host
        self.port = port

    def stop(self):
        self.terminate()

    def run(self):
        print(f"🚀 Flask server spuštěn na {self.host}:{self.port}")
        flask_app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

# ============================================================
#  SPUŠTĚNÍ APLIKACE
# ============================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    app.setStyleSheet('''
        * { font-size: 28px; font-weight: bold; }
        QMainWindow { background: #f0f4fa; }
        QGroupBox { border: 1px solid #e9edf4; border-radius: 12px; background: white; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; font-weight: bold; font-size: 28px; }
        QPushButton { border-radius: 20px; padding: 15px 30px; font-weight: bold; font-size: 28px; }
        QPushButton:hover { background: #e9edf4; }
        QTableWidget { border: none; background: white; border-radius: 8px; gridline-color: #e9edf4; font-size: 28px; }
        QTableWidget::item { padding: 10px; }
        QHeaderView::section { background: #f8faff; padding: 10px; border: none; font-weight: bold; font-size: 28px; }
        QLineEdit, QSpinBox, QDoubleSpinBox { border: 1px solid #d1d9e6; border-radius: 8px; padding: 10px 15px; background: white; font-size: 28px; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #ff7e05; }
        QLabel { font-size: 28px; font-weight: bold; }
        QTabBar::tab { padding: 15px 30px; border-radius: 20px; font-weight: bold; font-size: 28px; }
        QTabBar::tab:selected { background: #ff7e05; color: white; }
        QTabBar::tab:hover { background: #e9edf4; }
    ''')

    flask_thread = FlaskServerThread()
    flask_thread.daemon = True
    flask_thread.start()

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
