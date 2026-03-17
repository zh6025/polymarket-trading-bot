// lib/risk.js

/**
 * Risk Management Module
 * This module provides functionality for risk management, position control, and circuit breaker logic.
 */

class RiskManagement {
    constructor(maxRiskPercentage) {
        this.maxRiskPercentage = maxRiskPercentage; // Maximum risk per trade as a percentage of the account
        this.currentExposure = 0; // Current market exposure
    }

    calculateRisk(positionSize, entryPrice, accountBalance) {
        const potentialLoss = positionSize * entryPrice * this.maxRiskPercentage / 100;
        return potentialLoss;
    }

    managePosition(positionSize, entryPrice, accountBalance) {
        const risk = this.calculateRisk(positionSize, entryPrice, accountBalance);
        if (risk > accountBalance * this.maxRiskPercentage / 100) {
            throw new Error('Risk exceeds maximum allowed risk.');
        }
        this.currentExposure += risk;
    }
}

class CircuitBreaker {
    constructor(threshold) {
        this.threshold = threshold; // Price movement threshold to trigger circuit breaker
        this.isTriggered = false;
    }

    checkCircuitBreaker(priceMovement) {
        if (Math.abs(priceMovement) >= this.threshold) {
            this.isTriggered = true;
            return true; // Circuit breaker triggered
        }
        return false; // Not triggered
    }

    resetCircuitBreaker() {
        this.isTriggered = false;
    }
}

module.exports = { RiskManagement, CircuitBreaker };