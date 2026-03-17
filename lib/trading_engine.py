import time

class TradeExecution:
    def __init__(self):
        self.orders = []
        self.positions = {}
        self.pnl = 0.0

    def execute_order(self, order_type, symbol, quantity, price):
        order = {
            'type': order_type,
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'timestamp': time.time()
        }
        self.orders.append(order)
        self.update_position(symbol, quantity, price)

    def update_position(self, symbol, quantity, price):
        if symbol not in self.positions:
            self.positions[symbol] = 0
        self.positions[symbol] += quantity
        self.calculate_pnl(symbol, price, quantity)

    def calculate_pnl(self, symbol, price, quantity):
        if symbol in self.positions:
            cost = price * quantity
            self.pnl += cost  # Simplified PnL calculation for demonstration

    def get_positions(self):
        return self.positions

    def get_pnl(self):
        return self.pnl

# Example of usage:
if __name__ == '__main__':
    trader = TradeExecution()
    trader.execute_order('buy', 'BTC', 0.1, 60000)
    trader.execute_order('sell', 'BTC', 0.05, 61000)
    print('Current Positions:', trader.get_positions())
    print('Current PnL:', trader.get_pnl())