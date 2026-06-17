Havirov Coin
Desktopová aplikace pro správu vlastní kryptoměny HAV s integrací hardwarových těžařů (RPI PICO / Arduino), okamžitým převodem na USDT přes FaucetPay, stakingem a živým obchodováním.

🚀 Funkce
Dashboard – přehled aktuální ceny, celkového množství HAV, počtu aktivních zařízení a objemu obchodů.

Mining – připojení RPI PICO přes sériový port, zobrazení surových dat z hardwaru (žádný hash rate, jen čistý výstup). Detekce nalezených bloků a automatické přičítání odměn.

Peněženka – zobrazení zůstatku HAV a jeho hodnoty v USDT, historie transakcí, odesílání HAV na libovolnou adresu.

Swap – nákup/prodej HAV za USDT s dynamickým kurzem (spread 5 %), transakční poplatek 3 %. Deposit a Withdraw USDT na/v z FaucetPay účtu.

Pool – staking HAV s APY 7 % za 7 dní, historie staků.

Trading – graf vývoje ceny HAV/USDT s vyznačeným spreadem. Cena se pohybuje podle objemu obchodů (nákup zvyšuje, prodej snižuje).

Statistiky – přehled bloků, obtížnosti, celkové zásoby a tržních informací (bid/ask, spread, poplatek).

Blockchain – výpis posledních 20 bloků včetně hash, těžaře a odměny.

🖥️ Technologie
Python 3.8+

PyQt5 – grafické rozhraní

Matplotlib – vykreslování grafů

PySerial – komunikace po sériové lince

Requests – volání FaucetPay API

Vlastní architektura vláken – GUI běží odděleně od jádra těžby, aby aplikace zůstala plynulá i při velkém počtu zařízení.

⚙️ Instalace
1. Naklonování repozitáře
bash
git clone https://github.com/davepro777cze/havirov-coin.git
cd havirov-coin
2. Instalace závislostí
bash
pip install PyQt5 matplotlib pyserial requests
Na Linuxu (Debian/Ubuntu) je potřeba doinstalovat podporu QtSvg:

bash
sudo apt-get install python3-pyqt5.qtsvg
3. Spuštění
bash
python3 app.py
🔧 Konfigurace
V souboru app.py na začátku naleznete konstanty pro FaucetPay:

python
FAUCETPAY_API_KEY = "69ed69cf56555931401881143a3897f149aefa7afaf30303d32cb64b25d3fbd3"
FAUCETPAY_MERCHANT_ID = "davepro777cze"
Pokud chcete použít vlastní účet, změňte tyto hodnoty a případně upravte koncové body API.

Další parametry:

python
BASE_RATE = 1e-12          # střední kurz 1 HAV = 1e-12 USDT
SPREAD = 0.05              # 5% spread (nákup o 5 % dražší, prodej o 5 % levnější)
TRANSACTION_FEE = 0.03     # 3% poplatek z každé transakce
🧵 Architektura vláken
Aplikace používá tři typy vláken pro zajištění plynulého chodu:

Vlákno	Účel
GUI vlákno	Hlavní vlákno PyQt5 – zpracovává události, vykresluje rozhraní.
SerialReaderThread	Pro každý připojený port jedno vlákno – čte data ze sériové linky a posílá je do fronty.
MiningCore	Jedno sdílené vlákno – odebírá zprávy z fronty, parsuje je, detekuje bloky, aktualizuje stav a vysílá signály pro aktualizaci UI.
Díky tomuto oddělení se GUI nezasekává ani při velkém počtu připojených těžařů nebo vysoké frekvenci dat.

📡 Komunikace s RPI PICO
RPI PICO musí odesílat data ve formátu:

text
HASHRATE: 1234567
BLOCK FOUND!
Aplikace nezobrazuje hash rate, ale surová data včetně časového razítka. Tím je zajištěna plná transparentnost a možnost ladění přímo z výstupu hardwaru.

🧪 Testování bez HW
Pokud nemáte k dispozici RPI PICO, můžete funkčnost otestovat kliknutím na „Připojit zařízení“ a vybrat libovolný virtuální port (např. /dev/ttyUSB0). Data pak můžete simulovat odesláním řádku např. pomocí echo "BLOCK FOUND!" > /dev/ttyUSB0 (pokud port existuje). Alternativně lze upravit kód a vložit testovací data přímo do fronty.

📝 Poznámky k vydání
Verze: 1.0.0

Datum: červen 2026

Stav: Ostrá verze – připraveno pro nasazení na produkčním zařízení.

📄 Licence
Tento projekt je poskytován pod licencí MIT. Můžete jej volně používat, upravovat a distribuovat.

👤 Autor
DavePro777 – davepro777cze (FaucetPay Merchant ID)

GitHub: davepro777cze
