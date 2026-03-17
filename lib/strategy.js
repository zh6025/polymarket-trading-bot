// grid/strategy.js

class GridTradingStrategy {
    constructor(gridSize, takeProfit, stopLoss) {
        this.gridSize = gridSize;  // Distance between grid levels
        this.takeProfit = takeProfit;  // Take profit percentage
        this.stopLoss = stopLoss;  // Stop loss percentage
        this.gridLevels = [];
        this.currentLevel = 0;
    }

    generateGrid(currentPrice) {
        // Generate grid levels based on current price
        for (let i = 0; i < 10; i++) {
            this.gridLevels.push(currentPrice + (i * this.gridSize));
        }
    }

    signalGeneration(currentPrice) {
        if (currentPrice >= this.gridLevels[this.currentLevel] * (1 + this.takeProfit)) {
            this.currentLevel = Math.min(this.currentLevel + 1, this.gridLevels.length - 1);
            return 'Sell';
        } else if (currentPrice <= this.gridLevels[this.currentLevel] * (1 - this.stopLoss)) {
            this.currentLevel = Math.max(this.currentLevel - 1, 0);
            return 'Buy';
        }
        return 'Hold';
    }
}

module.exports = GridTradingStrategy;