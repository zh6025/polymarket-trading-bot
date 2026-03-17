// lib/config.js

const dotenv = require('dotenv');
dotenv.config();

const requiredEnvVars = ['API_KEY', 'DB_URL'];

requiredEnvVars.forEach((varName) => {
    if (!process.env[varName]) {
        throw new Error(`Missing required environment variable: ${varName}`);
    }
});

const config = {
    apiKey: process.env.API_KEY,
    dbUrl: process.env.DB_URL,
};

module.exports = config;