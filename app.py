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
    QInputDialog, QDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QObject
from PyQt5.QtGui import QFont

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

# ============================================================
#  FAUCETPAY API FUNKCE
# ============================================================

def faucetpay_get_balance():
    """Získá aktuální zůstatek USDT z FaucetPay."""
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

def faucetpay_deposit(amount_usdt):
    """Otevře FaucetPay Merchant formulář pro deposit."""
    html_content = f'''
    <html>
    <head>
        <meta charset="UTF-8">
        <title>FaucetPay Deposit</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .info {{ background: #f0f8ff; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>FaucetPay Deposit</h1>
            <div class="info">
                <p>Částka k vkladu: <strong>{amount_usdt:.8f} USDT</strong></p>
                <p>Účet: <strong>{FAUCETPAY_MERCHANT_ID}</strong></p>
            </div>
            <form id="depositForm" action="https://faucetpay.io/merchant/webscr" method="post">
                <input type="hidden" name="merchant_username" value="{FAUCETPAY_MERCHANT_ID}">
                <input type="hidden" name="item_description" value="Deposit USDT to Havirov Coin">
                <input type="hidden" name="amount1" value="{amount_usdt:.8f}">
                <input type="hidden" name="currency1" value="USDT">
                <input type="hidden" name="currency2" value="">
                <input type="hidden" name="custom" value="deposit_{int(time.time())}">
                <input type="hidden" name="callback_url" value="http://localhost:9999/callback">
                <input type="hidden" name="success_url" value="http://localhost:9999/success">
                <input type="hidden" name="cancel_url" value="http://localhost:9999/cancel">
                <input type="submit" value="Pokračovat na FaucetPay" style="
                    background: #ff7e05; color: white; border: none;
                    padding: 15px 30px; font-size: 18px; border-radius: 25px;
                    cursor: pointer; font-weight: bold;
                ">
            </form>
            <p style="margin-top: 20px; color: #666;">Pokud nejste přesměrováni, klikněte na tlačítko.</p>
            <p style="color: #999; font-size: 12px;">Po dokončení platby klikněte v aplikaci na "Aktualizovat zůstatek".</p>
        </div>
        <script>
            // Automatické odeslání formuláře po načtení stránky
            setTimeout(function() {{
                document.getElementById('depositForm').submit();
            }}, 1000);
        </script>
    </body>
    </html>
    '''
    fd, path = tempfile.mkstemp(suffix='.html', prefix='faucetpay_deposit_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html_content)
    webbrowser.open('file://' + path)
    return True, f"Otevřen formulář pro vklad {amount_usdt:.8f} USDT.\nPo dokončení platby klikněte na 'Aktualizovat zůstatek'."

def faucetpay_withdraw(amount_usdt, to_address):
    """Otevře FaucetPay Merchant formulář pro výběr."""
    html_content = f'''
    <html>
    <head>
        <meta charset="UTF-8">
        <title>FaucetPay Withdraw</title>
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
            .container {{ max-width: 600px; margin: 0 auto; }}
            .info {{ background: #f0f8ff; padding: 20px; border-radius: 10px; margin-bottom: 20px; }}
            .address {{ background: #eef2f7; padding: 10px; border-radius: 8px; font-family: monospace; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>FaucetPay Withdraw</h1>
            <div class="info">
                <p>Částka k výběru: <strong>{amount_usdt:.8f} USDT</strong></p>
                <p>Cílová adresa: <br><span class="address">{to_address}</span></p>
                <p>Účet: <strong>{FAUCETPAY_MERCHANT_ID}</strong></p>
            </div>
            <form id="withdrawForm" action="https://faucetpay.io/merchant/webscr" method="post">
                <input type="hidden" name="merchant_username" value="{FAUCETPAY_MERCHANT_ID}">
                <input type="hidden" name="item_description" value="Withdraw USDT from Havirov Coin">
                <input type="hidden" name="amount1" value="{amount_usdt:.8f}">
                <input type="hidden" name="currency1" value="USDT">
                <input type="hidden" name="currency2" value="">
                <input type="hidden" name="custom" value="withdraw_{int(time.time())}">
                <input type="hidden" name="callback_url" value="http://localhost:9999/callback">
                <input type="hidden" name="success_url" value="http://localhost:9999/success">
                <input type="hidden" name="cancel_url" value="http://localhost:9999/cancel">
                <input type="submit" value="Pokračovat na FaucetPay" style="
                    background: #ff7e05; color: white; border: none;
                    padding: 15px 30px; font-size: 18px; border-radius: 25px;
                    cursor: pointer; font-weight: bold;
                ">
            </form>
            <p style="margin-top: 20px; color: #666;">Pokud nejste přesměrováni, klikněte na tlačítko.</p>
            <p style="color: #999; font-size: 12px;">Po dokončení platby klikněte v aplikaci na "Aktualizovat zůstatek".</p>
        </div>
        <script>
            setTimeout(function() {{
                document.getElementById('withdrawForm').submit();
            }}, 1000);
        </script>
    </body>
    </html>
    '''
    fd, path = tempfile.mkstemp(suffix='.html', prefix='faucetpay_withdraw_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(html_content)
    webbrowser.open('file://' + path)
    return True, f"Otevřen formulář pro výběr {amount_usdt:.8f} USDT.\nPo dokončení platby klikněte na 'Aktualizovat zůstatek'."

def faucetpay_get_buy_rate():
    return BASE_RATE * (1 + SPREAD)

def faucetpay_get_sell_rate():
    return BASE_RATE * (1 - SPREAD)

# ============================================================
#  UKLÁDÁNÍ A NAČÍTÁNÍ STAVU
# ============================================================

def save_state():
    """Uloží aktuální stav aplikace do JSON souboru s file lockingem pro synchronizaci uživatelů."""
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
                    for d in state.devices if d.get('connected')]
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
    """Načte stav aplikace z JSON souboru s file lockingem."""
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
        # Obnovíme zařízení (jen informace, připojení se řeší znovu)
        devices_data = data.get('devices', [])
        for dev_info in devices_data:
            existing = next((d for d in state.devices if d['name'] == dev_info['name']), None)
            if not existing:
                state.devices.append({
                    'name': dev_info['name'],
                    'port': dev_info.get('port', 'N/A'),
                    'connected': False,  # neobnovujeme připojení
                    'thread': None,
                    'network': dev_info.get('port', '').startswith('tcp:')
                })
        print(f"Stav načten: {state.block_height} bloků, {state.wallet_balance:.2f} HAV")
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

            # Uložíme stav po každém novém bloku
            save_state()
            self.new_block.emit(block)
            self.new_transaction.emit(tx)

# ============================================================
#  TCP SERVER PRO PŘÍJEM DAT Z MINERŮ
# ============================================================

class TcpServer(QThread):
    data_received = pyqtSignal(str, str)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)
    devices_changed = pyqtSignal()

    def __init__(self, host='0.0.0.0', port=9998):
        super().__init__()
        self.host = host
        self.port = port
        self._running = True
        self._clients = {}
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
            self.server_socket.settimeout(1.0)
            while self._running:
                try:
                    conn, addr = self.server_socket.accept()
                    if self._running:
                        client_thread = threading.Thread(target=self._handle_client, args=(conn, addr))
                        client_thread.daemon = True
                        client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Chyba v TCP serveru: {e}")
        except Exception as e:
            print(f"Chyba při naslouchání na portu {self.port}: {e}")
        finally:
            if self.server_socket:
                self.server_socket.close()

    def _handle_client(self, conn, addr):
        device_name = None
        try:
            data = conn.recv(1024).decode('utf-8', errors='ignore').strip()
            if data.startswith('DEVICE:'):
                device_name = data.split(':', 1)[1].strip()
            else:
                device_name = f'Miner-{addr[0]}-{addr[1]}'
            with self._lock:
                self._clients[conn] = device_name
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

            while self._running:
                line = conn.recv(4096).decode('utf-8', errors='ignore').strip()
                if not line:
                    break
                if line:
                    self.data_received.emit(device_name, line)
        except Exception as e:
            print(f"Chyba u klienta {addr}: {e}")
        finally:
            with self._lock:
                self._clients.pop(conn, None)
            if device_name:
                with state._lock:
                    dev = next((d for d in state.devices if d['name'] == device_name), None)
                    if dev:
                        dev['connected'] = False
                    save_state()
                self.client_disconnected.emit(device_name)
                self.devices_changed.emit()
            try:
                conn.close()
            except:
                pass

# ============================================================
#  HLAVNÍ OKNO
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Havirov Coin - Ostrá verze')
        self.setMinimumSize(1200, 800)

        # Načtení uloženého stavu
        load_state()

        self.mining_core = MiningCore()
        self.mining_core.new_block.connect(self._on_new_block)
        self.mining_core.new_transaction.connect(self._on_new_transaction)
        self.mining_core.devices_changed.connect(self._on_devices_changed)
        self.mining_core.start()

        self.tcp_server = TcpServer(host='0.0.0.0', port=9998)
        self.tcp_server.data_received.connect(self._on_tcp_data)
        self.tcp_server.devices_changed.connect(self._on_devices_changed)
        self.tcp_server.start()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel('Havirov Coin')
        title.setFont(QFont('Segoe UI', 24, QFont.Bold))
        title.setStyleSheet('color: #ff7e05;')
        badge = QLabel('PROD')
        badge.setStyleSheet('background: #198754; color: white; border-radius: 12px; padding: 4px 16px; font-weight: bold; font-size: 15px;')
        header.addWidget(title)
        header.addWidget(badge)
        header.addStretch()
        header.addWidget(QLabel(datetime.now().strftime('%H:%M:%S')))
        main_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet('''
            QTabBar::tab { padding: 8px 24px; border-radius: 20px; font-weight: 700; font-size: 14px; }
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
        footer.setStyleSheet('color: #7b8a9b; font-size: 13px; padding: 8px; font-weight: 500;')
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
        self.mining_core.enqueue_data(device_name, line)
        self.tab_mining.add_raw_line(device_name, line)

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
            ('total_supply', 'Celkem HAV', '0'),
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
        left.setStyleSheet('QGroupBox { font-weight: 700; padding: 10px; font-size: 14px; }')
        left_layout = QVBoxLayout(left)
        self.price_canvas = MplCanvas(self, width=8, height=3)
        left_layout.addWidget(self.price_canvas)
        graph_layout.addWidget(left)

        layout.addLayout(graph_layout)

        dist_group = QGroupBox('Distribuce odměn')
        dist_group.setStyleSheet('QGroupBox { font-weight: 700; padding: 10px; font-size: 14px; }')
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
        lbl_title.setStyleSheet('color: #7b8a9b; font-size: 13px; font-weight: 600;')
        layout.addWidget(lbl_title)
        val_label = QLabel(default)
        val_label.setFont(QFont('Segoe UI', 22, QFont.Bold))
        layout.addWidget(val_label)
        sub_label = QLabel('—')
        sub_label.setStyleSheet('color: #7b8a9b; font-size: 12px; font-weight: 500;')
        layout.addWidget(sub_label)

        card._val_label = val_label
        card._sub_label = sub_label
        return card

    def refresh(self):
        active = sum(1 for d in state.devices if d['connected'])
        current_price = state.price_history[-1] if state.price_history else BASE_RATE

        self.cards['price']._val_label.setText(f'{current_price:.12f} USDT')
        self.cards['price']._sub_label.setText(f'nákup {current_price*(1+SPREAD):.12f} / prodej {current_price*(1-SPREAD):.12f}')
        self.cards['total_supply']._val_label.setText(f'{state.total_supply:,.0f}')
        self.cards['total_supply']._sub_label.setText('—')
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
            self.reward_pie_canvas.ax.text(0.5, 0.5, 'Žádná data', ha='center', va='center', fontsize=14)
            self.reward_pie_canvas.draw()
            return
        labels = [e[0] for e in entries]
        values = [e[1] for e in entries]
        colors = ['#ff7e05', '#0d6efd', '#198754', '#ffc107', '#6f42c1', '#dc3545']
        self.reward_pie_canvas.ax.pie(values, labels=labels, colors=colors[:len(values)], autopct='%1.0f%%', startangle=90)
        self.reward_pie_canvas.ax.axis('equal')
        self.reward_pie_canvas.draw()

# ============================================================
#  MINING TAB
# ============================================================

class SerialReaderThread(QThread):
    error_occurred = pyqtSignal(str)

    def __init__(self, port, baudrate=115200, device_name=None, core=None):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.device_name = device_name or port
        self._running = True
        self.ser = None
        self.core = core

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            while self._running:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    if line and self.core:
                        self.core.enqueue_data(self.device_name, line)
                else:
                    time.sleep(0.01)
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    def stop(self):
        self._running = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.wait()

class MiningTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        header = QHBoxLayout()
        header.addWidget(QLabel('Připojená zařízení', font=QFont('Segoe UI', 14, QFont.Bold)))
        header.addStretch()
        self.miner_count_label = QLabel('0')
        self.miner_count_label.setStyleSheet('background: #6c757d; color: white; border-radius: 12px; padding: 4px 18px; font-weight: bold; font-size: 14px;')
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

        right_layout.addWidget(QLabel('Surová data z HW', font=QFont('Segoe UI', 14, QFont.Bold)))

        self.raw_data_display = QTextEdit()
        self.raw_data_display.setReadOnly(True)
        self.raw_data_display.setFont(QFont('Courier New', 10))
        self.raw_data_display.setStyleSheet('background: #1e1e1e; color: #d4d4d4; border-radius: 8px; padding: 8px;')
        right_layout.addWidget(self.raw_data_display)

        ctrl_layout = QHBoxLayout()
        self.connect_btn = QPushButton('Připojit zařízení (sériový port)')
        self.connect_btn.setStyleSheet('QPushButton { background: #ff7e05; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #e66e00; }')
        self.connect_btn.clicked.connect(self._connect_device)
        ctrl_layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton('Odpojit vše')
        self.disconnect_btn.setStyleSheet('QPushButton { background: #dc3545; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #c82333; }')
        self.disconnect_btn.clicked.connect(self._disconnect_all)
        self.disconnect_btn.hide()
        ctrl_layout.addWidget(self.disconnect_btn)

        self.clear_btn = QPushButton('Vymazat data')
        self.clear_btn.setStyleSheet('QPushButton { background: #6c757d; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #5a6268; }')
        self.clear_btn.clicked.connect(lambda: self.raw_data_display.clear())
        ctrl_layout.addWidget(self.clear_btn)

        right_layout.addLayout(ctrl_layout)

        self.device_status = QLabel('Stav: 0 zařízení připojeno')
        self.device_status.setStyleSheet('background: #cfe2ff; border-radius: 8px; padding: 8px; font-size: 14px; font-weight: 600;')
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
        thread.start()
        dev['thread'] = thread
        self.reader_threads.append(thread)

        self.main_window.mining_core.devices_changed.emit()
        self.refresh_device_table()
        save_state()
        QMessageBox.information(self, 'Připojeno', f'Zařízení {device_name} bylo připojeno.')

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
        self.device_status.setStyleSheet('background: #d1e7dd; border-radius: 8px; padding: 8px; font-size: 14px; font-weight: 600;' if active else 'background: #cfe2ff; border-radius: 8px; padding: 8px; font-size: 14px; font-weight: 600;')
        self.disconnect_btn.setVisible(bool(active))

        self.device_table.setUpdatesEnabled(False)
        self.device_table.setRowCount(len(active))
        for i, d in enumerate(active):
            self.device_table.setItem(i, 0, QTableWidgetItem(d['name']))
            self.device_table.setItem(i, 1, QTableWidgetItem(d.get('port', 'N/A')))
            self.device_table.setItem(i, 2, QTableWidgetItem('🟢 Aktivní'))
        self.device_table.resizeColumnsToContents()
        self.device_table.setUpdatesEnabled(True)
        self.device_table.setFont(QFont('Segoe UI', 12))
        self.device_table.horizontalHeader().setFont(QFont('Segoe UI', 12, QFont.Bold))

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

        left_layout.addWidget(QLabel('Moje peněženka', font=QFont('Segoe UI', 18, QFont.Bold)))

        addr_layout = QHBoxLayout()
        self.address_label = QLabel(state.wallet_address)
        self.address_label.setStyleSheet('background: #eef2f7; padding: 6px 18px; border-radius: 20px; font-family: monospace; font-size: 14px;')
        self.address_label.setWordWrap(True)
        addr_layout.addWidget(self.address_label)
        copy_btn = QPushButton('Kopírovat')
        copy_btn.setStyleSheet('QPushButton { background: #0d6efd; color: white; font-weight: bold; font-size: 13px; padding: 6px 14px; border-radius: 16px; } QPushButton:hover { background: #0b5ed7; }')
        copy_btn.clicked.connect(self._copy_address)
        addr_layout.addWidget(copy_btn)
        self.copy_feedback = QLabel('')
        self.copy_feedback.setStyleSheet('color: green; font-size: 13px; font-weight: 600;')
        addr_layout.addWidget(self.copy_feedback)
        addr_layout.addStretch()
        left_layout.addLayout(addr_layout)

        new_addr_btn = QPushButton('Nová adresa')
        new_addr_btn.setStyleSheet('QPushButton { background: #6c757d; color: white; font-weight: bold; font-size: 13px; padding: 6px 14px; border-radius: 16px; } QPushButton:hover { background: #5a6268; }')
        new_addr_btn.clicked.connect(self._new_address)
        left_layout.addWidget(new_addr_btn)

        self.balance_label = QLabel('0.00 HAV')
        self.balance_label.setFont(QFont('Segoe UI', 28, QFont.Bold))
        left_layout.addWidget(self.balance_label)

        current_price = state.price_history[-1] if state.price_history else BASE_RATE
        usdt_value = state.wallet_balance * current_price
        self.usd_label = QLabel(f'≈ {usdt_value:.12f} USDT')
        self.usd_label.setStyleSheet('color: #198754; font-size: 16px; font-weight: 600;')
        left_layout.addWidget(self.usd_label)

        send_btn = QPushButton('Odeslat HAV')
        send_btn.setStyleSheet('QPushButton { background: #ff7e05; color: white; font-weight: bold; font-size: 14px; padding: 8px 20px; border-radius: 20px; } QPushButton:hover { background: #e66e00; }')
        send_btn.clicked.connect(self._show_send_dialog)
        left_layout.addWidget(send_btn)

        layout.addWidget(left, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel('Historie transakcí', font=QFont('Segoe UI', 16, QFont.Bold)))

        self.tx_table = QTableWidget()
        self.tx_table.setColumnCount(4)
        self.tx_table.setHorizontalHeaderLabels(['Typ', 'Částka', 'Adresa', 'Čas'])
        self.tx_table.horizontalHeader().setStretchLastSection(True)
        self.tx_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tx_table.setFont(QFont('Segoe UI', 12))
        self.tx_table.horizontalHeader().setFont(QFont('Segoe UI', 12, QFont.Bold))
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
        self.setFixedSize(450, 280)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel('Adresa příjemce', font=QFont('Segoe UI', 12, QFont.Bold)))
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText('0x...')
        self.address_edit.setFont(QFont('Segoe UI', 12))
        layout.addWidget(self.address_edit)

        layout.addWidget(QLabel('Částka (HAV)', font=QFont('Segoe UI', 12, QFont.Bold)))
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText('0.00')
        self.amount_edit.setFont(QFont('Segoe UI', 12))
        layout.addWidget(self.amount_edit)

        self.message = QLabel('Zadejte adresu a částku.')
        self.message.setStyleSheet('background: #cfe2ff; padding: 8px; border-radius: 8px; font-weight: 600; font-size: 13px;')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton('Zavřít')
        cancel_btn.setStyleSheet('QPushButton { background: #6c757d; color: white; font-weight: bold; font-size: 13px; padding: 6px 16px; border-radius: 16px; }')
        cancel_btn.clicked.connect(self.reject)
        send_btn = QPushButton('Odeslat')
        send_btn.setStyleSheet('QPushButton { background: #ff7e05; color: white; font-weight: bold; font-size: 13px; padding: 6px 16px; border-radius: 16px; }')
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
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px; font-weight: 600;')
            return
        if not addr or len(addr) < 10:
            self.message.setText('Zadejte platnou adresu.')
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px; font-weight: 600;')
            return
        if amount <= 0:
            self.message.setText('Zadejte kladnou částku.')
            self.message.setStyleSheet('background: #f8d7da; padding: 8px; border-radius: 8px; font-weight: 600;')
            return
        self._data = (addr, amount)
        self.accept()

    def get_data(self):
        return self._data

# ============================================================
#  SWAP TAB
# ============================================================

class SwapTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        left = QGroupBox('Swap HAV / USDT')
        left.setStyleSheet('QGroupBox { font-weight: 700; padding: 16px; font-size: 14px; }')
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel('Množství HAV', font=QFont('Segoe UI', 13, QFont.Bold)))
        amt_layout = QHBoxLayout()
        self.amount_input = QLineEdit('10000')
        self.amount_input.setFont(QFont('Segoe UI', 14))
        amt_layout.addWidget(self.amount_input)
        amt_layout.addWidget(QLabel('HAV', font=QFont('Segoe UI', 13, QFont.Bold)))
        left_layout.addLayout(amt_layout)

        left_layout.addWidget(QLabel('⬇', alignment=Qt.AlignCenter, font=QFont('Segoe UI', 14, QFont.Bold)))

        left_layout.addWidget(QLabel('Obdržíte', font=QFont('Segoe UI', 13, QFont.Bold)))
        result_layout = QHBoxLayout()
        self.result_input = QLineEdit('0.00000001')
        self.result_input.setReadOnly(True)
        self.result_input.setFont(QFont('Segoe UI', 14))
        result_layout.addWidget(self.result_input)
        result_layout.addWidget(QLabel('USDT', font=QFont('Segoe UI', 13, QFont.Bold)))
        left_layout.addLayout(result_layout)

        rate_info = QLabel()
        rate_info.setStyleSheet('font-weight: 600; color: #0d6efd; font-size: 13px;')
        left_layout.addWidget(rate_info)
        self.rate_info_label = rate_info

        fee_label = QLabel(f'Poplatek za transakci: {TRANSACTION_FEE*100:.0f} %')
        fee_label.setStyleSheet('color: #6c757d; font-size: 12px;')
        left_layout.addWidget(fee_label)

        recipient_label = QLabel(f'Příjemce USDT: FaucetPay {FAUCETPAY_MERCHANT_ID}')
        recipient_label.setStyleSheet('font-weight: 700; color: #0d6efd; font-size: 14px; background: #e9edf4; padding: 4px; border-radius: 6px;')
        left_layout.addWidget(recipient_label)

        self.balance_label = QLabel(f'FaucetPay USDT zůstatek: 0.00000000')
        self.balance_label.setStyleSheet('font-weight: 700; color: #0d6efd; font-size: 14px;')
        left_layout.addWidget(self.balance_label)

        swap_btn = QPushButton('Swap HAV → USDT (prodej)')
        swap_btn.setStyleSheet('QPushButton { background: #ff7e05; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #e66e00; }')
        swap_btn.clicked.connect(self._do_sell)
        left_layout.addWidget(swap_btn)

        buy_btn = QPushButton('Swap USDT → HAV (nákup)')
        buy_btn.setStyleSheet('QPushButton { background: #198754; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #157347; }')
        buy_btn.clicked.connect(self._do_buy)
        left_layout.addWidget(buy_btn)

        layout.addWidget(left, 1)

        right = QGroupBox('Deposit / Withdraw USDT')
        right.setStyleSheet('QGroupBox { font-weight: 700; padding: 16px; font-size: 14px; }')
        right_layout = QVBoxLayout(right)

        right_layout.addWidget(QLabel('FaucetPay účet', font=QFont('Segoe UI', 13, QFont.Bold)))
        right_layout.addWidget(QLabel(f'ID: {FAUCETPAY_MERCHANT_ID}', styleSheet='font-family: monospace; font-size: 14px; background: #eef2f7; padding: 4px; border-radius: 4px;'))

        right_layout.addWidget(QLabel('-' * 30))

        # Deposit
        right_layout.addWidget(QLabel('Vklad (Deposit)', font=QFont('Segoe UI', 12, QFont.Bold)))
        dep_layout = QHBoxLayout()
        self.deposit_input = QLineEdit()
        self.deposit_input.setPlaceholderText('Množství USDT')
        self.deposit_input.setFont(QFont('Segoe UI', 12))
        dep_layout.addWidget(self.deposit_input)
        dep_btn = QPushButton('Otevřít FaucetPay Deposit')
        dep_btn.setStyleSheet('QPushButton { background: #0d6efd; color: white; font-weight: bold; font-size: 13px; padding: 6px 14px; border-radius: 16px; } QPushButton:hover { background: #0b5ed7; }')
        dep_btn.clicked.connect(self._do_deposit)
        dep_layout.addWidget(dep_btn)
        right_layout.addLayout(dep_layout)

        # Withdraw
        right_layout.addWidget(QLabel('Výběr (Withdraw)', font=QFont('Segoe UI', 12, QFont.Bold)))
        wd_layout = QHBoxLayout()
        self.withdraw_input = QLineEdit()
        self.withdraw_input.setPlaceholderText('Množství USDT')
        self.withdraw_input.setFont(QFont('Segoe UI', 12))
        wd_layout.addWidget(self.withdraw_input)
        self.withdraw_address = QLineEdit()
        self.withdraw_address.setPlaceholderText('Cílová adresa')
        self.withdraw_address.setFont(QFont('Segoe UI', 12))
        wd_layout.addWidget(self.withdraw_address)
        wd_btn = QPushButton('Otevřít FaucetPay Withdraw')
        wd_btn.setStyleSheet('QPushButton { background: #dc3545; color: white; font-weight: bold; font-size: 13px; padding: 6px 14px; border-radius: 16px; } QPushButton:hover { background: #c82333; }')
        wd_btn.clicked.connect(self._do_withdraw)
        wd_layout.addWidget(wd_btn)
        right_layout.addLayout(wd_layout)

        right_layout.addWidget(QLabel('-' * 30))
        self.message_label = QLabel('')
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet('padding: 8px; border-radius: 6px; font-weight: 600;')
        right_layout.addWidget(self.message_label)

        refresh_btn = QPushButton('Aktualizovat zůstatek')
        refresh_btn.setStyleSheet('QPushButton { background: #6c757d; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #5a6268; }')
        refresh_btn.clicked.connect(self._refresh_balance)
        right_layout.addWidget(refresh_btn)

        layout.addWidget(right, 1)

        self.amount_input.textChanged.connect(self._update_swap)
        self._refresh_balance()
        self._update_swap()

    def _update_swap(self):
        try:
            amt = float(self.amount_input.text() or 0)
            sell_rate = faucetpay_get_sell_rate()
            usdt = amt * sell_rate
            usdt_after_fee = apply_fee(usdt)
            self.result_input.setText(f'{usdt_after_fee:.12f}')

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

    def _do_sell(self):
        try:
            amt = float(self.amount_input.text() or 0)
            if amt <= 0:
                QMessageBox.warning(self, 'Chyba', 'Zadejte kladné množství.')
                return
            if amt > state.wallet_balance:
                QMessageBox.warning(self, 'Chyba', 'Nedostatek HAV v peněžence.')
                return

            sell_rate = faucetpay_get_sell_rate()
            usdt_raw = amt * sell_rate
            usdt_final = apply_fee(usdt_raw)

            state.wallet_balance -= amt
            state.usdt_balance += usdt_final

            price_change = -usdt_final * 0.001
            new_price = max(BASE_RATE * 0.5, state.price_history[-1] + price_change)
            state.price_history.append(new_price)

            state.transactions.insert(0, {
                'type': 'Prodej HAV→USDT',
                'amount': amt,
                'address': f'FaucetPay ({FAUCETPAY_MERCHANT_ID})',
                'time': datetime.now().strftime('%H:%M:%S')
            })
            if len(state.transactions) > 20:
                state.transactions.pop()

            save_state()
            self._show_message(
                f'Prodej {amt} HAV za {usdt_final:.12f} USDT (poplatek {usdt_raw-usdt_final:.12f} USDT)',
                'success'
            )
            self._refresh_balance()
            self._update_swap()

        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Zadejte platné číslo.')

    def _do_buy(self):
        try:
            amt = float(self.amount_input.text() or 0)
            if amt <= 0:
                QMessageBox.warning(self, 'Chyba', 'Zadejte kladné množství.')
                return

            buy_rate = faucetpay_get_buy_rate()
            usdt_needed = amt * buy_rate
            usdt_with_fee = usdt_needed / (1 - TRANSACTION_FEE)

            if usdt_with_fee > state.usdt_balance:
                QMessageBox.warning(self, 'Chyba', f'Nedostatek USDT na FaucetPay účtě. Potřebujete {usdt_with_fee:.8f} USDT.')
                return

            state.usdt_balance -= usdt_with_fee
            state.wallet_balance += amt

            price_change = usdt_with_fee * 0.001
            new_price = min(BASE_RATE * 2, state.price_history[-1] + price_change)
            state.price_history.append(new_price)

            state.transactions.insert(0, {
                'type': 'Nákup USDT→HAV',
                'amount': amt,
                'address': f'FaucetPay ({FAUCETPAY_MERCHANT_ID})',
                'time': datetime.now().strftime('%H:%M:%S')
            })
            if len(state.transactions) > 20:
                state.transactions.pop()

            save_state()
            self._show_message(
                f'Nákup {amt} HAV za {usdt_with_fee:.12f} USDT (poplatek {usdt_with_fee-usdt_needed:.12f} USDT)',
                'success'
            )
            self._refresh_balance()
            self._update_swap()

        except ValueError:
            QMessageBox.warning(self, 'Chyba', 'Zadejte platné číslo.')

    def _do_deposit(self):
        try:
            amount = float(self.deposit_input.text() or 0)
            if amount <= 0:
                self._show_message('Zadejte kladnou částku pro vklad.', 'warning')
                return

            success, msg = faucetpay_deposit(amount)
            if success:
                self._show_message(msg, 'success')
            else:
                self._show_message(msg, 'danger')
        except ValueError:
            self._show_message('Zadejte platné číslo.', 'warning')

    def _do_withdraw(self):
        try:
            amount = float(self.withdraw_input.text() or 0)
            if amount <= 0:
                self._show_message('Zadejte kladnou částku pro výběr.', 'warning')
                return

            to_addr = self.withdraw_address.text().strip()
            if not to_addr:
                self._show_message('Zadejte cílovou adresu.', 'warning')
                return

            success, msg = faucetpay_withdraw(amount, to_addr)
            if success:
                self._show_message(msg, 'success')
            else:
                self._show_message(msg, 'danger')
        except ValueError:
            self._show_message('Zadejte platné číslo.', 'warning')

    def _show_message(self, text, level='info'):
        colors = {
            'info': '#cfe2ff',
            'success': '#d1e7dd',
            'warning': '#fff3cd',
            'danger': '#f8d7da'
        }
        self.message_label.setStyleSheet(f'background: {colors.get(level, "#cfe2ff")}; padding: 8px; border-radius: 6px; font-weight: 600; font-size: 13px;')
        self.message_label.setText(text)
        QTimer.singleShot(10000, lambda: self.message_label.setText(''))

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
        left.setStyleSheet('QGroupBox { font-weight: 700; padding: 16px; font-size: 14px; }')
        left_layout = QVBoxLayout(left)

        stats_layout = QHBoxLayout()
        self.pool_tvl = QLabel('0')
        self.pool_tvl.setFont(QFont('Segoe UI', 22, QFont.Bold))
        self.pool_user = QLabel('0')
        self.pool_user.setFont(QFont('Segoe UI', 22, QFont.Bold))
        self.pool_reward = QLabel('0')
        self.pool_reward.setFont(QFont('Segoe UI', 22, QFont.Bold))

        stats_layout.addWidget(self._stat_item('Celková likvidita', self.pool_tvl, '(HAV)'))
        stats_layout.addWidget(self._stat_item('Váš stake', self.pool_user, '(HAV)'))
        stats_layout.addWidget(self._stat_item('Odměna', self.pool_reward, '(HAV)'))
        left_layout.addLayout(stats_layout)

        left_layout.addWidget(QLabel('-' * 40))

        info_layout = QFormLayout()
        info_layout.addRow(QLabel('APY:'), QLabel('7 % / 7 dní', styleSheet='font-weight: 700; color: #198754; font-size: 14px;'))
        info_layout.addRow(QLabel('Doba uzamčení:'), QLabel('7 dní', styleSheet='font-weight: 700; font-size: 14px;'))
        self.status_label = QLabel('Žádný stake')
        self.status_label.setStyleSheet('background: #6c757d; color: white; border-radius: 12px; padding: 4px 16px; font-weight: bold; font-size: 14px;')
        info_layout.addRow(QLabel('Stav:'), self.status_label)
        self.countdown_label = QLabel('—')
        self.countdown_label.setStyleSheet('font-family: monospace; font-weight: 700; color: #ff7e05; font-size: 15px;')
        info_layout.addRow(QLabel('Čas do odemčení:'), self.countdown_label)
        left_layout.addLayout(info_layout)

        ctrl_layout = QHBoxLayout()
        self.stake_input = QLineEdit('10')
        self.stake_input.setFixedWidth(120)
        self.stake_input.setFont(QFont('Segoe UI', 14))
        max_btn = QPushButton('Max')
        max_btn.setStyleSheet('QPushButton { background: #6c757d; color: white; font-weight: bold; font-size: 13px; padding: 4px 12px; border-radius: 12px; } QPushButton:hover { background: #5a6268; }')
        max_btn.clicked.connect(self._set_max)
        ctrl_layout.addWidget(self.stake_input)
        ctrl_layout.addWidget(max_btn)
        left_layout.addLayout(ctrl_layout)

        stake_btn = QPushButton('Stake')
        stake_btn.setStyleSheet('QPushButton { background: #198754; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #157347; }')
        stake_btn.clicked.connect(self._stake)
        left_layout.addWidget(stake_btn)

        unstake_btn = QPushButton('Unstake')
        unstake_btn.setStyleSheet('QPushButton { background: #dc3545; color: white; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #c82333; }')
        unstake_btn.clicked.connect(self._unstake)
        left_layout.addWidget(unstake_btn)

        claim_btn = QPushButton('Vybrat odměnu')
        claim_btn.setStyleSheet('QPushButton { background: #ffc107; color: black; font-weight: bold; font-size: 14px; padding: 8px 16px; border-radius: 20px; } QPushButton:hover { background: #e0a800; }')
        claim_btn.clicked.connect(self._claim)
        left_layout.addWidget(claim_btn)

        self.pool_message = QLabel('')
        self.pool_message.setWordWrap(True)
        left_layout.addWidget(self.pool_message)

        layout.addWidget(left, 2)

        right = QGroupBox('Historie staků')
        right.setStyleSheet('QGroupBox { font-weight: 700; padding: 16px; font-size: 14px; }')
        right_layout = QVBoxLayout(right)

        self.stake_history_table = QTableWidget()
        self.stake_history_table.setColumnCount(3)
        self.stake_history_table.setHorizontalHeaderLabels(['Čas', 'Částka', 'Typ'])
        self.stake_history_table.horizontalHeader().setStretchLastSection(True)
        self.stake_history_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stake_history_table.setFont(QFont('Segoe UI', 12))
        self.stake_history_table.horizontalHeader().setFont(QFont('Segoe UI', 12, QFont.Bold))
        right_layout.addWidget(self.stake_history_table)

        right_layout.addWidget(QLabel('Odměna 7% po 7 dnech.', styleSheet='color: #7b8a9b; font-size: 13px; font-weight: 500;'))

        layout.addWidget(right, 1)
        self.refresh()

    def _stat_item(self, label, value_widget, unit):
        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel(label, styleSheet='color: #7b8a9b; font-size: 13px; font-weight: 600;'))
        hl = QHBoxLayout()
        hl.addWidget(value_widget)
        hl.addWidget(QLabel(unit, styleSheet='color: #7b8a9b; font-size: 13px; font-weight: 600;'))
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
        self.status_label.setStyleSheet('background: #198754; color: white; border-radius: 12px; padding: 4px 16px; font-weight: bold; font-size: 14px;' if status == 'Odemčeno' else 'background: #6c757d; color: white; border-radius: 12px; padding: 4px 16px; font-weight: bold; font-size: 14px;')
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
        self.pool_message.setStyleSheet(f'background: {colors.get(level, "#cfe2ff")}; padding: 8px; border-radius: 8px; font-weight: 600; font-size: 14px;')
        self.pool_message.setText(text)
        QTimer.singleShot(5000, lambda: self.pool_message.setText(''))

# ============================================================
#  TRADING TAB
# ============================================================

class TradingTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel('HAV / USDT - Reálný čas', font=QFont('Segoe UI', 18, QFont.Bold)))

        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel('Aktuální cena:'))
        self.price_label = QLabel(f'{BASE_RATE:.12f} USDT')
        self.price_label.setStyleSheet('font-weight: 700; font-size: 18px; color: #ff7e05;')
        info_layout.addWidget(self.price_label)
        info_layout.addStretch()
        info_layout.addWidget(QLabel('Spread:'))
        self.spread_label = QLabel(f'{SPREAD*100:.0f} %')
        self.spread_label.setStyleSheet('font-weight: 600; font-size: 14px;')
        info_layout.addWidget(self.spread_label)
        info_layout.addStretch()
        info_layout.addWidget(QLabel('Poplatek:'))
        self.fee_label = QLabel(f'{TRANSACTION_FEE*100:.0f} %')
        self.fee_label.setStyleSheet('font-weight: 600; font-size: 14px;')
        info_layout.addWidget(self.fee_label)
        layout.addLayout(info_layout)

        self.canvas = MplCanvas(self, width=8, height=5)
        layout.addWidget(self.canvas)

        info = QLabel('Cena se pohybuje podle objemu obchodů. Nákup zvyšuje cenu, prodej snižuje.')
        info.setStyleSheet('color: #7b8a9b; font-size: 13px; padding: 8px; font-weight: 500;')
        layout.addWidget(info)

        refresh_btn = QPushButton('Aktualizovat data')
        refresh_btn.setStyleSheet('QPushButton { background: #0d6efd; color: white; font-weight: bold; font-size: 14px; padding: 8px 20px; border-radius: 20px; } QPushButton:hover { background: #0b5ed7; }')
        refresh_btn.clicked.connect(self._refresh_data)
        layout.addWidget(refresh_btn)

        self._refresh_data()

    def _refresh_data(self):
        balance = faucetpay_get_balance()
        state.usdt_balance = balance

        if state.price_history:
            current_price = state.price_history[-1]
            self.price_label.setText(f'{current_price:.12f} USDT')

        self._draw_chart()

    def _draw_chart(self):
        data = list(state.price_history)
        if len(data) < 2:
            data = [BASE_RATE] * 50

        self.canvas.ax.clear()
        self.canvas.ax.plot(data, color='#ff7e05', linewidth=2)
        self.canvas.ax.fill_between(range(len(data)), data, color='#ff7e05', alpha=0.15)

        buy_prices = [d * (1 + SPREAD) for d in data]
        sell_prices = [d * (1 - SPREAD) for d in data]
        self.canvas.ax.fill_between(range(len(data)), sell_prices, buy_prices, color='#0d6efd', alpha=0.08)

        self.canvas.ax.grid(True, color='#e9edf4', linestyle='-', linewidth=0.5)
        self.canvas.ax.set_ylabel('USDT')
        self.canvas.ax.set_title('Vývoj ceny HAV/USDT (stínovaná oblast = spread)')
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
        group.setStyleSheet('QGroupBox { font-weight: 700; padding: 10px; font-size: 14px; }')
        g_layout = QVBoxLayout(group)

        info_grid = QGridLayout()
        info_grid.addWidget(QLabel('Střední kurz:'), 0, 0)
        self.mid_label = QLabel(f'{BASE_RATE:.12f} USDT')
        self.mid_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_grid.addWidget(self.mid_label, 0, 1)

        info_grid.addWidget(QLabel('Nákup (ask):'), 1, 0)
        self.ask_label = QLabel(f'{BASE_RATE*(1+SPREAD):.12f} USDT')
        self.ask_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_grid.addWidget(self.ask_label, 1, 1)

        info_grid.addWidget(QLabel('Prodej (bid):'), 2, 0)
        self.bid_label = QLabel(f'{BASE_RATE*(1-SPREAD):.12f} USDT')
        self.bid_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_grid.addWidget(self.bid_label, 2, 1)

        info_grid.addWidget(QLabel('Spread:'), 3, 0)
        self.spread_info_label = QLabel(f'{SPREAD*100:.0f} %')
        self.spread_info_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_grid.addWidget(self.spread_info_label, 3, 1)

        info_grid.addWidget(QLabel('Transakční poplatek:'), 4, 0)
        self.fee_info_label = QLabel(f'{TRANSACTION_FEE*100:.0f} %')
        self.fee_info_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_grid.addWidget(self.fee_info_label, 4, 1)

        g_layout.addLayout(info_grid)
        layout.addWidget(group)

        self.refresh()

    def _make_card(self, title, default):
        card = QFrame()
        card.setStyleSheet('QFrame { background: white; border-radius: 12px; padding: 10px 16px; border: 1px solid #e9edf4; }')
        layout = QVBoxLayout(card)
        layout.addWidget(QLabel(title, styleSheet='color: #7b8a9b; font-size: 13px; font-weight: 600;'))
        label = QLabel(default)
        label.setFont(QFont('Segoe UI', 22, QFont.Bold))
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

        layout.addWidget(QLabel('Blockchain', font=QFont('Segoe UI', 18, QFont.Bold)))

        self.block_table = QTableWidget()
        self.block_table.setColumnCount(6)
        self.block_table.setHorizontalHeaderLabels(['Výška', 'Hash', 'Těžař', 'Odměna', 'Tx', 'Čas'])
        self.block_table.horizontalHeader().setStretchLastSection(True)
        self.block_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.block_table.setFont(QFont('Segoe UI', 12))
        self.block_table.horizontalHeader().setFont(QFont('Segoe UI', 12, QFont.Bold))
        layout.addWidget(self.block_table)

        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel('Obtížnost:'))
        self.diff_label = QLabel('0.50')
        self.diff_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
        info_layout.addWidget(self.diff_label)
        info_layout.addStretch()
        info_layout.addWidget(QLabel('Bloků:'))
        self.blocks_label = QLabel('0')
        self.blocks_label.setFont(QFont('Segoe UI', 13, QFont.Bold))
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
#  FLASK SERVER PRO FAUCETPAY CALLBACKY
# ============================================================

FLASK_CALLBACK_PORT = 9999

flask_app = Flask(__name__)

@flask_app.route('/callback', methods=['POST'])
def faucetpay_callback_route():
    """Přijímá callbacky z FaucetPay po dokončení platby."""
    data = request.form.to_dict()
    print(f"📩 FaucetPay callback: {data}")
    status = data.get('status', '')
    if status.lower() == 'completed':
        amount = float(data.get('amount1', 0))
        currency = data.get('currency1', 'USDT')
        custom = data.get('custom', '')
        print(f"✅ Platba dokončena: {amount} {currency} ({custom})")
        with state._lock:
            state.usdt_balance += amount
            state.transactions.insert(0, {
                'type': f'Vklad USDT ({custom})',
                'amount': amount,
                'address': 'FaucetPay',
                'time': datetime.now().strftime('%H:%M:%S')
            })
            if len(state.transactions) > 20:
                state.transactions.pop()
            save_state()
    return jsonify({"status": "ok"})

@flask_app.route('/success')
def payment_success():
    return '''<html>
<head><meta charset="UTF-8"><title>Platba úspěšná</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#198754}</style>
</head><body><h1>✅ Platba byla úspěšná</h1>
<p>Můžete se vrátit do aplikace a kliknout na <strong>Aktualizovat zůstatek</strong>.</p></body></html>'''

@flask_app.route('/cancel')
def payment_cancel():
    return '''<html>
<head><meta charset="UTF-8"><title>Platba zrušena</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#dc3545}</style>
</head><body><h1>❌ Platba byla zrušena</h1>
<p>Pokud chcete platbu opakovat, zadejte znovu částku v aplikaci.</p></body></html>'''

@flask_app.route('/')
def index():
    return '''<html>
<head><meta charset="UTF-8"><title>Havirov Coin Server</title>
<style>body{font-family:Arial;text-align:center;padding:80px}h1{color:#ff7e05}</style>
</head><body><h1>🪙 Havirov Coin Server</h1>
<p>Flask server běží. Čekám na callbacky z FaucetPay...</p></body></html>'''

class FlaskServerThread(QThread):
    """Spouští Flask server v samostatném vlákně."""
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
    app.setFont(QFont('Segoe UI', 11, QFont.Normal))

    app.setStyleSheet('''
        QMainWindow { background: #f0f4fa; }
        QGroupBox { border: 1px solid #e9edf4; border-radius: 12px; background: white; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; font-weight: 700; font-size: 14px; }
        QPushButton { border-radius: 20px; padding: 8px 18px; font-weight: 700; font-size: 14px; }
        QPushButton:hover { background: #e9edf4; }
        QTableWidget { border: none; background: white; border-radius: 8px; gridline-color: #e9edf4; font-size: 13px; }
        QTableWidget::item { padding: 6px; }
        QHeaderView::section { background: #f8faff; padding: 6px; border: none; font-weight: 700; font-size: 13px; }
        QLineEdit, QSpinBox, QDoubleSpinBox { border: 1px solid #d1d9e6; border-radius: 8px; padding: 6px 10px; background: white; font-size: 13px; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #ff7e05; }
        QLabel { font-size: 13px; }
    ''')

    flask_thread = FlaskServerThread()
    flask_thread.daemon = True
    flask_thread.start()

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
