from flask import Flask, jsonify, render_template_string
from lib.data_persistence import DataPersistence
from lib.monitoring import MonitoringDashboard

app = Flask(__name__)
db = DataPersistence()
dashboard = MonitoringDashboard()

@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    return jsonify(dashboard.get_dashboard_data())

@app.route('/api/trades', methods=['GET'])
def get_trades():
    trades = db.get_trades(hours=24)
    return jsonify({'trades': trades, 'count': len(trades)})

@app.route('/api/performance', methods=['GET'])
def get_performance():
    perf = db.get_performance_summary(hours=24)
    return jsonify(perf)

@app.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bot Dashboard</title>
        <style>
            body { font-family: Arial; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
            .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .value { font-size: 28px; font-weight: bold; color: #667eea; }
            .label { font-size: 12px; color: #999; margin-top: 5px; }
            table { width: 100%; margin-top: 30px; border-collapse: collapse; }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            button { background: #667eea; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Trading Bot Dashboard</h1>
            <button onclick="refresh()">Refresh</button>
            <div class="metrics">
                <div class="card">
                    <div class="value" id="trades">-</div>
                    <div class="label">Total Trades</div>
                </div>
                <div class="card">
                    <div class="value" id="buys">-</div>
                    <div class="label">Buy Orders</div>
                </div>
                <div class="card">
                    <div class="value" id="sells">-</div>
                    <div class="label">Sell Orders</div>
                </div>
                <div class="card">
                    <div class="value" id="pnl">-</div>
                    <div class="label">Avg PnL</div>
                </div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Side</th>
                        <th>Size</th>
                        <th>Price</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody id="tbody">
                    <tr><td colspan="4">Loading...</td></tr>
                </tbody>
            </table>
        </div>
        <script>
            function refresh() {
                fetch('/api/metrics').then(r => r.json()).then(data => {
                    document.getElementById('trades').textContent = data.trades.total;
                    document.getElementById('buys').textContent = data.trades.buy_trades;
                    document.getElementById('sells').textContent = data.trades.sell_trades;
                    document.getElementById('pnl').textContent = '$' + data.performance.avg_pnl.toFixed(2);
                });
                fetch('/api/trades').then(r => r.json()).then(data => {
                    let html = '';
                    data.trades.slice(0, 10).forEach(t => {
                        html += '<tr><td>' + t.side + '</td><td>' + t.size + '</td><td>' + t.price + '</td><td>' + t.timestamp + '</td></tr>';
                    });
                    document.getElementById('tbody').innerHTML = html;
                });
            }
            refresh();
            setInterval(refresh, 30000);
        </script>
    </body>
    </html>
    ''')

if __name__ == '__main__':
    print('Dashboard: http://localhost:5000')
    app.run(host='0.0.0.0', port=5000)
